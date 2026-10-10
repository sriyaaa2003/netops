"""Component-level anomaly scoring. No database or HTTP here, so it is easy to test.

Three detectors, all working on the feature matrix from features.py (severity counts first, then subsystem counts and volume):
  boosting          gradient boosting trained on the real BGL log (eval/train_service_model.py); the default
  error_count       robust z-score of the number of error-class lines (no training)
  isolation_forest  unsupervised, refit on every batch (kept for comparison; weak on BGL, see eval/)
"""
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from features import COLUMNS, LEVELS, build

ERROR_LEVELS = ["ERROR", "SEVERE", "FATAL", "FAILURE"]
MIN_COMPONENTS = 5
MODEL_PATH = Path(__file__).with_name("model.joblib")
_model = None
_threshold = 0.5


def build_features(logs):
    return build(logs)


def _boosting_model():
    global _model, _threshold
    if _model is None:
        if not MODEL_PATH.exists():
            raise ValueError("no trained model: run eval/train_service_model.py or use another detector")
        bundle = joblib.load(MODEL_PATH)
        if bundle["columns"] != COLUMNS:
            raise ValueError("model was trained on different feature columns")
        _model = bundle["model"]
        _threshold = float(bundle.get("threshold", 0.5))      # F1-optimal on a validation slice, see eval/train_service_model.py
    return _model


def score(matrix, method="boosting"):
    """Higher means more anomalous. Returns (scores, flagged_mask)."""
    if method == "boosting":
        p = _boosting_model().predict_proba(matrix)[:, 1]
        return p, p >= _threshold
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
