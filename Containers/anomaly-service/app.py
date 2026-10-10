import hmac
import os
import sys
import time
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
import requests
from flask import Flask, jsonify, request

from detector import MIN_COMPONENTS, build_features, score
from features import LEVELS

app = Flask(__name__)

LOG_SERVICE_URL = os.environ.get("LOG_SERVICE_URL", "http://log-service:4000")
DETECTOR = os.environ.get("DETECTOR", "boosting")  # or "error_count", "isolation_forest"; see eval/ for the comparison
WINDOW_SECONDS = int(os.environ.get("WINDOW_SECONDS", "3600"))

REQUIRED_ENV = ["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME", "API_KEY"]
missing_env = [key for key in REQUIRED_ENV if not os.environ.get(key)]
if missing_env:
    sys.exit(f"Fatal: missing required environment variable(s): {', '.join(missing_env)}")

API_KEY = os.environ["API_KEY"]
DB_CONFIG = {
    "host": os.environ["DB_HOST"],
    "port": os.environ["DB_PORT"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "dbname": os.environ["DB_NAME"],
}


@app.before_request
def require_key():
    if request.path == "/health":
        return None
    if not hmac.compare_digest(request.headers.get("X-API-Key", ""), API_KEY):
        return jsonify({"error": "missing or wrong X-API-Key"}), 401
    return None


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def init_db(retries=20, delay_seconds=3):
    last_err = None
    for attempt in range(retries):
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS anomalies (
                    id SERIAL PRIMARY KEY,
                    component TEXT NOT NULL,
                    detector TEXT NOT NULL DEFAULT 'isolation_forest',
                    counts JSONB,
                    score DOUBLE PRECISION,
                    had_alert BOOLEAN,
                    window_end TIMESTAMPTZ,
                    detected_at TIMESTAMPTZ DEFAULT now()
                );
                """
            )
            conn.commit()
            cur.close()
            conn.close()
            print("Database ready.")
            return
        except Exception as exc:  # noqa: BLE001 - broad on purpose during startup retry
            last_err = exc
            print(f"DB not ready yet (attempt {attempt + 1}/{retries}): {exc}")
            time.sleep(delay_seconds)
    raise RuntimeError(f"Could not connect to database after retries: {last_err}")


def fetch_window(window_seconds):
    """Logs from the last `window_seconds` of log time (the newest line defines 'now')."""
    headers = {"X-API-Key": API_KEY}
    newest = requests.get(f"{LOG_SERVICE_URL}/logs", params={"limit": 1}, headers=headers, timeout=10)
    newest.raise_for_status()
    rows = newest.json()
    if not rows:
        return [], None
    end = datetime.fromisoformat(rows[0]["log_timestamp"].replace("Z", "+00:00"))
    since = (end - timedelta(seconds=window_seconds)).isoformat()
    resp = requests.get(
        f"{LOG_SERVICE_URL}/logs", params={"limit": 20000, "since": since}, headers=headers, timeout=30
    )
    resp.raise_for_status()
    return resp.json(), end


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "anomaly-service", "detector": DETECTOR})


@app.route("/analyze", methods=["POST"])
def analyze():
    method = request.args.get("detector", DETECTOR)
    window = int(request.args.get("window", WINDOW_SECONDS))
    try:
        logs, window_end = fetch_window(window)
    except requests.RequestException as exc:
        return jsonify({"error": "could not reach log-service", "detail": str(exc)}), 502

    components, matrix = build_features(logs)
    if len(components) < MIN_COMPONENTS:
        return jsonify({"message": f"need logs from at least {MIN_COMPONENTS} components", "flagged": []}), 200

    try:
        scores, mask = score(matrix, method)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    alerted = {e["component"] for e in logs if e.get("alert_label")}
    flagged = []
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        for i in range(len(components)):
            if not mask[i]:
                continue
            counts = {s: int(matrix[i][j]) for j, s in enumerate(LEVELS)}
            cur.execute(
                """INSERT INTO anomalies (component, detector, counts, score, had_alert, window_end)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                (components[i], method, psycopg2.extras.Json(counts), float(scores[i]), components[i] in alerted, window_end),
            )
            flagged.append(cur.fetchone())
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify(
        {
            "detector": method,
            "window_seconds": window,
            "analyzed_logs": len(logs),
            "components_considered": len(components),
            "components_with_alert_label": len(alerted),
            "flagged": flagged,
            # Alert labels come from the dataset and are used only here, to report how the flags compare.
            "flagged_with_alert": sum(1 for f in flagged if f["had_alert"]),
        }
    )


@app.route("/anomalies")
def list_anomalies():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM anomalies ORDER BY detected_at DESC, score DESC LIMIT 200")
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return jsonify(rows)


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
