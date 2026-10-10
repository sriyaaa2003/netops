"""Supervised, hierarchical and ensemble detectors on the real BlueGene/L log, with a time-ordered split.

Unit = one node card in one window. Features (what the anomaly service can see): counts per severity, counts per subsystem
(KERNEL, APP, ...), number of lines, number of distinct message openings, and the same counts of the previous window.
Detection label: BGL's alert tag appears in the unit's window. Early-warning label: it appears in the NEXT window, evaluated only
on units with no alert yet.

Split: windows are ordered in time; the first 60% train, the last 40% test (no shuffling, so the test period is the future).

    python eval/bgl_models.py path/to/BGL.log --cache bgl_full.parquet --out eval/results
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

LINE = re.compile(r"^(\S+) (\d+) \S+ (\S+) \S+ \S+ (\S+) (\S+) (\S+) (.*)$")
LEVELS = ["INFO", "WARNING", "ERROR", "SEVERE", "FATAL", "FAILURE"]
ERROR_LEVELS = ["ERROR", "SEVERE", "FATAL", "FAILURE"]
SUBSYSTEMS = ["KERNEL", "APP", "MMCS", "DISCOVERY", "LINKCARD", "MONITOR", "HARDWARE", "CMCS"]


def load(path, cache):
    cache = Path(cache)
    if cache.exists():
        return pd.read_parquet(cache)
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LINE.match(line)
            if m and m.group(6) in LEVELS:
                rows.append((m.group(1) != "-", int(m.group(2)), m.group(3), m.group(5), m.group(6), " ".join(m.group(7).split()[:3])))
    df = pd.DataFrame(rows, columns=["alert", "ts", "node", "sub", "level", "opening"])
    df.to_parquet(cache)
    return df


def unit_table(df, window, depth):
    d = df.assign(unit=df.node.map(lambda n: "-".join(n.split("-")[:depth])), w=(df.ts - df.ts.min()) // window)
    lev = d.groupby(["w", "unit"])["level"].value_counts().unstack(fill_value=0).reindex(columns=LEVELS, fill_value=0)
    sub = d.assign(sub=d["sub"].where(d["sub"].isin(SUBSYSTEMS), "OTHER")).groupby(["w", "unit"])["sub"].value_counts().unstack(fill_value=0)
    sub = sub.reindex(columns=SUBSYSTEMS + ["OTHER"], fill_value=0)
    sub.columns = ["sub_" + c for c in sub.columns]
    g = d.groupby(["w", "unit"])
    X = pd.concat([lev, sub, g.size().rename("n_lines"), g["opening"].nunique().rename("n_openings"), g["alert"].any().astype(int).rename("alert")], axis=1)
    X = X.reset_index().sort_values(["unit", "w"])
    feat = LEVELS + list(sub.columns) + ["n_lines", "n_openings"]
    prev = X.groupby("unit")[feat].shift(1)
    contiguous = (X.groupby("unit")["w"].diff() == 1).to_numpy()
    for c in feat:
        X["prev_" + c] = np.where(contiguous, prev[c].fillna(0), 0.0)
    nxt = X.groupby("unit")["alert"].shift(-1)
    X["next_alert"] = np.where((X.groupby("unit")["w"].diff(-1) == -1).to_numpy(), nxt, np.nan)
    return X.sort_values(["w", "unit"]).reset_index(drop=True), feat


def rank01(x):
    return (rankdata(x) - 1) / max(len(x) - 1, 1)


def evaluate(scores, y, w):
    mixed = [k for k in np.unique(w) if 0 < y[w == k].sum() < (w == k).sum()]
    per = [roc_auc_score(y[w == k], scores[w == k]) for k in mixed]
    return {"AUROC": round(float(roc_auc_score(y, scores)), 3), "AP": round(float(average_precision_score(y, scores)), 3),
            "AUROC_per_window": round(float(np.mean(per)), 3) if per else None}


def run_setting(df, window, depth, label):
    X, feat = unit_table(df, window, depth)
    cols = feat + ["prev_" + c for c in feat]
    if label == "next":
        X = X[(X.alert == 0) & X.next_alert.notna()].copy()
        X["y"] = X.next_alert.astype(int)
    else:
        X["y"] = X.alert
    cut = X.w.quantile(0.6)
    tr, te = X[X.w <= cut], X[X.w > cut]
    err = lambda t: t[ERROR_LEVELS].sum(axis=1).to_numpy() + (t[["prev_" + c for c in ERROR_LEVELS]].sum(axis=1).to_numpy() * 0.5 if label == "next" else 0)
    ytr, yte, wte = tr.y.to_numpy(), te.y.to_numpy(), te.w.to_numpy()
    out = {"train_units": int(len(tr)), "test_units": int(len(te)), "test_positive_rate": round(float(yte.mean()), 3), "methods": {}}
    gbm = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, random_state=0).fit(tr[cols], ytr)
    lr_sc = StandardScaler().fit(np.log1p(tr[cols]))
    lr = LogisticRegression(C=0.5, max_iter=2000).fit(lr_sc.transform(np.log1p(tr[cols])), ytr)
    p_gbm = gbm.predict_proba(te[cols])[:, 1]
    p_lr = lr.predict_proba(lr_sc.transform(np.log1p(te[cols])))[:, 1]
    iforest = IsolationForest(n_estimators=100, random_state=0).fit(np.log1p(tr[cols]))
    s_if = -iforest.decision_function(np.log1p(te[cols]))
    # hierarchical: stage 1 separates units that logged error-class lines at all; stage 2 is trained only on those
    gate_tr = (tr[ERROR_LEVELS].sum(axis=1) + (tr[["prev_" + c for c in ERROR_LEVELS]].sum(axis=1) if label == "next" else 0)).to_numpy() > 0
    gate_te = (te[ERROR_LEVELS].sum(axis=1) + (te[["prev_" + c for c in ERROR_LEVELS]].sum(axis=1) if label == "next" else 0)).to_numpy() > 0
    stage2 = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, random_state=0).fit(tr[cols][gate_tr], ytr[gate_tr]) if gate_tr.sum() > 50 and len(set(ytr[gate_tr])) > 1 else None
    s_h = np.where(gate_te, 0.5 + 0.5 * (stage2.predict_proba(te[cols])[:, 1] if stage2 else p_gbm), 0.5 * p_gbm)
    ens = (rank01(err(te)) + rank01(p_gbm) + rank01(p_lr) + 0.5 * rank01(s_if)) / 3.5
    methods = {
        "random": np.random.default_rng(0).random(len(te)),
        "Isolation Forest (unsupervised)": s_if,
        "error-class count (rule)": err(te),
        "logistic regression (supervised)": p_lr,
        "gradient boosting (supervised)": p_gbm,
        "hierarchical: rule gate + boosting": s_h,
        "ensemble: rank average of rule, boosting, logistic, forest": ens,
    }
    for name, s in methods.items():
        out["methods"][name] = evaluate(np.asarray(s, dtype=float), yte, wte)
    imp = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--cache", default="bgl_full.parquet")
    ap.add_argument("--out", default="eval/results")
    a = ap.parse_args()
    df = load(a.log, a.cache)
    res = {}
    for unit, depth, window in [("node card", 3, 3600), ("midplane", 2, 600)]:
        for label in ("detect", "next"):
            key = f"{unit}, {window // 60}-min window, {'alert in this window' if label == 'detect' else 'alert in the NEXT window (early warning)'}"
            res[key] = run_setting(df, window, depth, label)
            print(key, json.dumps(res[key]["methods"]), flush=True)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    Path(a.out, "bgl_models.json").write_text(json.dumps(res, indent=2))
    lines = ["| setting | method | AUROC | AP | AUROC per window |", "|---|---|---|---|---|"]
    for key, r in res.items():
        lines.append(f"| **{key}** (test units {r['test_units']}, positives {r['test_positive_rate']:.2f}) | | | | |")
        for name, m in r["methods"].items():
            lines.append(f"| | {name} | {m['AUROC']:.3f} | {m['AP']:.3f} | {m['AUROC_per_window'] if m['AUROC_per_window'] is not None else ''} |")
    Path(a.out, "bgl_models.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
