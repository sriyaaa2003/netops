"""Component-level anomaly scoring from severity counts. No database or HTTP here, so it is easy to test."""
from collections import defaultdict

import numpy as np
from sklearn.ensemble import IsolationForest

LEVELS = ["INFO", "WARNING", "ERROR", "SEVERE", "FATAL", "FAILURE"]
ERROR_LEVELS = ["ERROR", "SEVERE", "FATAL", "FAILURE"]
MIN_COMPONENTS = 5


def build_features(logs):
    """One row per component: how many lines of each severity it logged in the batch."""
    counts = defaultdict(lambda: dict.fromkeys(LEVELS, 0))
    for entry in logs:
        sev = entry.get("severity")
        if sev in LEVELS:
            counts[entry.get("component", "unknown")][sev] += 1
    components = sorted(counts)
    matrix = np.array([[counts[c][s] for s in LEVELS] for c in components], dtype=float)
    return components, matrix


def score(matrix, method="isolation_forest"):
    """Higher means more anomalous. Returns (scores, flagged_mask)."""
    if method == "isolation_forest":
        model = IsolationForest(n_estimators=200, contamination="auto", random_state=0)
        model.fit(np.log1p(matrix))
        return -model.decision_function(np.log1p(matrix)), model.predict(np.log1p(matrix)) == -1
    if method == "error_count":
        errors = matrix[:, [LEVELS.index(s) for s in ERROR_LEVELS]].sum(axis=1)
        med = np.median(errors)
        mad = np.median(np.abs(errors - med)) or 1.0
        z = (errors - med) / (1.4826 * mad)
        return errors, (z > 3.0) & (errors > 0)
    raise ValueError(f"unknown detector {method!r}")
