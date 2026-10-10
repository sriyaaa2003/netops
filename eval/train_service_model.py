"""Train the gradient-boosting detector shipped with the anomaly service on the real BGL log.

Node cards, 1-hour windows, current-window features only (the service sees one window at a time). The first 60% of windows train
the model; the last 40% are the held-out future, scored and written to eval/results/service_model.json.

    python eval/train_service_model.py path/to/BGL.log --cache bgl_full.parquet
"""
import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Containers" / "anomaly-service"))
from bgl_models import load, unit_table  # noqa: E402
from features import COLUMNS  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("log")
ap.add_argument("--cache", default="bgl_full.parquet")
a = ap.parse_args()

X, _ = unit_table(load(a.log, a.cache), 3600, 3)
cols = COLUMNS
assert all(c in X.columns for c in cols), "feature columns drifted between eval and service"
cut = X.w.quantile(0.6)
inner = X.w.quantile(0.48)
tr, te = X[X.w <= cut], X[X.w > cut]
fit, val = X[X.w <= inner], X[(X.w > inner) & (X.w <= cut)]

# the flagging threshold is the F1-optimal one on a validation slice that sits between training and test
m0 = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, random_state=0).fit(fit[cols].to_numpy(), fit.alert)
prec, rec, thr = precision_recall_curve(val.alert, m0.predict_proba(val[cols].to_numpy())[:, 1])
f1 = 2 * prec[:-1] * rec[:-1] / np.maximum(prec[:-1] + rec[:-1], 1e-9)
threshold = float(thr[int(np.argmax(f1))])

model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, random_state=0).fit(tr[cols].to_numpy(), tr.alert)
p = model.predict_proba(te[cols].to_numpy())[:, 1]
rule = te[["ERROR", "SEVERE", "FATAL", "FAILURE"]].sum(axis=1).to_numpy()
flag = p >= threshold
tp = int((flag & (te.alert.to_numpy() == 1)).sum())
res = {"train_units": int(len(tr)), "test_units": int(len(te)), "test_positive_rate": float(te.alert.mean()),
       "threshold": threshold, "flag_precision": tp / max(int(flag.sum()), 1), "flag_recall": tp / max(int(te.alert.sum()), 1),
       "gradient_boosting": {"AUROC": float(roc_auc_score(te.alert, p)), "AP": float(average_precision_score(te.alert, p))},
       "error_count_rule": {"AUROC": float(roc_auc_score(te.alert, rule)), "AP": float(average_precision_score(te.alert, rule))}}
out = Path(__file__).resolve().parents[1]
joblib.dump({"model": model, "columns": cols, "threshold": threshold}, out / "Containers" / "anomaly-service" / "model.joblib", compress=3)
(out / "eval" / "results" / "service_model.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
