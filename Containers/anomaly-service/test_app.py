"""HTTP-level tests of the anomaly service with the log service and the database replaced by fakes (no Postgres needed)."""
import importlib
import sys
from datetime import datetime, timezone

import pytest

ENV = {"DB_HOST": "x", "DB_PORT": "1", "DB_USER": "u", "DB_PASSWORD": "p", "DB_NAME": "d", "API_KEY": "secret-key"}


class FakeCursor:
    def __init__(self, store):
        self.store, self.row = store, None

    def execute(self, sql, params=None):
        if sql.strip().upper().startswith("INSERT"):
            component, detector, counts, score, had_alert, window_end = params
            self.row = {"id": len(self.store) + 1, "component": component, "detector": detector, "counts": counts.adapted,
                        "score": score, "had_alert": had_alert}
            self.store.append(self.row)

    def fetchone(self):
        return self.row

    def fetchall(self):
        return list(self.store)

    def close(self):
        pass


class FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self, **_):
        return FakeCursor(self.store)

    def commit(self):
        pass

    def close(self):
        pass


def logs(per_component):
    now = datetime(2005, 6, 3, 12, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    out = []
    for comp, counts in per_component.items():
        for sev, n in counts.items():
            out += [{"component": comp, "severity": sev, "log_timestamp": now, "alert_label": "KERNDTLB" if sev == "FATAL" else None}] * n
    return out


@pytest.fixture()
def client(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    import psycopg2

    store = []
    monkeypatch.setattr(psycopg2, "connect", lambda **_: FakeConn(store))
    sys.modules.pop("app", None)
    app = importlib.import_module("app")
    fleet = {f"R0{i}-M0-N{i}": {"INFO": 40 + i, "WARNING": 1} for i in range(8)}
    fleet["R09-M1-N4"] = {"INFO": 30, "FATAL": 90}

    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    def fake_get(url, params=None, headers=None, timeout=None):
        assert headers["X-API-Key"] == "secret-key"            # the service forwards its key to the log service
        return Resp(logs(fleet)[:1] if params.get("limit") == 1 else logs(fleet))

    monkeypatch.setattr(app.requests, "get", fake_get)
    app.app.testing = True
    return app.app.test_client(), store


def test_health_is_open_but_everything_else_needs_the_key(client):
    c, _ = client
    assert c.get("/health").status_code == 200
    assert c.post("/analyze").status_code == 401
    assert c.get("/anomalies", headers={"X-API-Key": "wrong"}).status_code == 401


@pytest.mark.parametrize("detector", ["error_count", "isolation_forest"])
def test_analyze_flags_the_node_card_full_of_fatal_lines_and_reports_the_label_overlap(client, detector):
    c, store = client
    r = c.post(f"/analyze?detector={detector}", headers={"X-API-Key": "secret-key"})
    body = r.get_json()
    assert r.status_code == 200 and body["detector"] == detector
    assert "R09-M1-N4" in [f["component"] for f in body["flagged"]]
    assert body["flagged_with_alert"] >= 1 and body["components_with_alert_label"] == 1
    assert store and all(row["detector"] == detector for row in store)


def test_unknown_detector_is_a_client_error(client):
    c, _ = client
    assert c.post("/analyze?detector=magic", headers={"X-API-Key": "secret-key"}).status_code == 400


def test_init_db_adds_the_new_columns_to_a_table_made_by_an_older_version(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    import psycopg2

    executed = []

    class RecordingCursor:
        def execute(self, sql, params=None):
            executed.append(" ".join(sql.split()))

        def close(self):
            pass

    class RecordingConn:
        def cursor(self, **_):
            return RecordingCursor()

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(psycopg2, "connect", lambda **_: RecordingConn())
    sys.modules.pop("app", None)
    app = importlib.import_module("app")
    executed.clear()
    app.init_db()
    sql = " ".join(executed)
    assert "CREATE TABLE IF NOT EXISTS anomalies" in sql
    for column in ("detector", "counts", "had_alert", "window_end"):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in sql
