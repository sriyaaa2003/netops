import os
import sys
import time
from collections import defaultdict

import requests
import psycopg2
import psycopg2.extras
from flask import Flask, jsonify
from sklearn.ensemble import IsolationForest

app = Flask(__name__)

LOG_SERVICE_URL = os.environ.get("LOG_SERVICE_URL", "http://log-service:4000")
SEVERITIES = ["INFO", "WARN", "ERROR", "CRITICAL"]

REQUIRED_DB_ENV = ["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"]
missing_env = [key for key in REQUIRED_DB_ENV if not os.environ.get(key)]
if missing_env:
    sys.exit(f"Fatal: missing required environment variable(s): {', '.join(missing_env)}")

DB_CONFIG = {
    "host": os.environ["DB_HOST"],
    "port": os.environ["DB_PORT"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "dbname": os.environ["DB_NAME"],
}


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def init_db(retries=20, delay_seconds=3):
    last_err = None
    for attempt in range(retries):
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS anomalies (
                    id SERIAL PRIMARY KEY,
                    component TEXT NOT NULL,
                    info_count INTEGER,
                    warn_count INTEGER,
                    error_count INTEGER,
                    critical_count INTEGER,
                    score DOUBLE PRECISION,
                    detected_at TIMESTAMPTZ DEFAULT now()
                );
            """)
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


def fetch_recent_logs(limit=500):
    resp = requests.get(f"{LOG_SERVICE_URL}/logs", params={"limit": limit}, timeout=5)
    resp.raise_for_status()
    return resp.json()


def build_feature_table(logs):
    # One row per component: counts of each severity level in the fetched batch.
    counts = defaultdict(lambda: {s: 0 for s in SEVERITIES})
    for entry in logs:
        comp = entry.get("component", "unknown")
        sev = entry.get("severity", "INFO")
        if sev in counts[comp]:
            counts[comp][sev] += 1
    components = list(counts.keys())
    features = [[counts[c][s] for s in SEVERITIES] for c in components]
    return components, features, counts


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "anomaly-service"})


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        logs = fetch_recent_logs()
    except requests.RequestException as exc:
        return jsonify({"error": "could not reach log-service", "detail": str(exc)}), 502

    if len(logs) < 3:
        return jsonify({"message": "not enough log data yet to analyze", "flagged": []}), 200

    components, features, counts = build_feature_table(logs)

    # Isolation Forest needs no labeled "normal" data: it isolates points
    # that are easy to separate from the rest, which tend to be the
    # components behaving differently from their peers in this batch.
    model = IsolationForest(contamination="auto", random_state=42)
    model.fit(features)
    scores = model.decision_function(features)
    predictions = model.predict(features)  # -1 = anomaly, 1 = normal

    flagged = []
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        for comp, score, pred in zip(components, scores, predictions):
            if pred == -1:
                c = counts[comp]
                cur.execute(
                    """INSERT INTO anomalies
                       (component, info_count, warn_count, error_count, critical_count, score)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                    (comp, c["INFO"], c["WARN"], c["ERROR"], c["CRITICAL"], float(score)),
                )
                flagged.append(cur.fetchone())
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify({
        "analyzed_logs": len(logs),
        "components_considered": len(components),
        "flagged": flagged,
    })


@app.route("/anomalies")
def list_anomalies():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM anomalies ORDER BY detected_at DESC LIMIT 200")
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return jsonify(rows)



init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
