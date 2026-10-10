"""Offline evaluation of the NetOps detectors on the real BlueGene/L log (Loghub BGL, 4.7M lines, 215 days).

Unit of analysis: one node card (e.g. R02-M1-N0) or one midplane (R02-M1) in one time window, described only by
its severity counts, exactly what the anomaly service sees. A unit is *positive* when BGL's own alert tag (first
column of the log) appears on any of its lines in the window; the label is used for scoring only, never by a detector.
Each window is scored on its own batch (the Isolation Forest is refit per window, as in the service). Windows are
kept only if they hold both positive and negative units, and a random sample of them (seeded) is scored.

    python eval/bgl_eval.py path/to/BGL.log --out eval/results
"""
import argparse
import itertools
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score

LINE = re.compile(r"^(\S+) (\d+) \S+ (\S+) \S+ \S+ (\S+) (\S+) (\S+)")
LEVELS = ["INFO", "WARNING", "ERROR", "SEVERE", "FATAL", "FAILURE"]
ERROR_IDX = [2, 3, 4, 5]


def load(path, cache=None):
    cache = Path(cache) if cache else None
    if cache and cache.exists():
        return pd.read_parquet(cache)
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LINE.match(line)
            if m and m.group(6) in LEVELS:
                rows.append((m.group(1) != "-", int(m.group(2)), m.group(3), m.group(6)))
    df = pd.DataFrame(rows, columns=["alert", "ts", "node", "level"])
    if cache:
        df.to_parquet(cache)
    return df


def units(df, window, depth):
    df = df.assign(unit=df.node.map(lambda n: "-".join(n.split("-")[:depth])), w=(df.ts - df.ts.min()) // window)
    g = df.groupby(["w", "unit"])
    X = g["level"].value_counts().unstack(fill_value=0).reindex(columns=LEVELS, fill_value=0)
    y = g["alert"].any().astype(int).loc[X.index]
    return X, y


def iforest(Xw, log=True):
    Z = np.log1p(Xw) if log else Xw
    return -IsolationForest(n_estimators=100, random_state=0).fit(Z).decision_function(Z)


def zscore(Xw):
    z = (Xw - Xw.mean(0)) / (Xw.std(0) + 1e-9)
    return z.max(1)


def error_count(Xw):
    return Xw[:, ERROR_IDX].sum(1)


def run(df, window, depth, n_windows, seed=0):
    X, y = units(df, window, depth)
    widx = X.index.get_level_values(0).values
    yv = y.values
    eligible = [w for w in np.unique(widx) if 0 < yv[widx == w].sum() < (widx == w).sum() and (widx == w).sum() >= 5]
    rng = np.random.default_rng(seed)
    chosen = sorted(rng.choice(eligible, size=min(n_windows, len(eligible)), replace=False))
    methods = {
        "random": lambda Xw: rng.random(len(Xw)),
        "max z-score": zscore,
        "Isolation Forest (raw counts)": lambda Xw: iforest(Xw, log=False),
        "Isolation Forest (log counts)": iforest,
        "error-class count": error_count,
    }
    scores = {m: [] for m in methods}
    labels, wid = [], []
    for w in chosen:
        m = widx == w
        for name, fn in methods.items():
            scores[name].append(fn(X.values[m].astype(float)))
        labels.append(yv[m])
        wid.append(np.full(m.sum(), w))
    labels, wid = np.concatenate(labels), np.concatenate(wid)
    out = {"windows_eligible": len(eligible), "windows_scored": len(chosen), "units_scored": int(len(labels)),
           "positive_rate": round(float(labels.mean()), 4), "methods": {}}
    for name, parts in scores.items():
        s = np.concatenate(parts)
        per_window_auc = [roc_auc_score(labels[wid == w], s[wid == w]) for w in chosen]
        out["methods"][name] = {
            "AUROC_pooled": round(roc_auc_score(labels, s), 3),
            "AUROC_per_window_mean": round(float(np.mean(per_window_auc)), 3),
            "AP": round(average_precision_score(labels, s), 3),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--out", default="eval/results")
    ap.add_argument("--cache", default=None, help="parquet cache of the parsed log")
    ap.add_argument("--windows", type=int, default=300)
    a = ap.parse_args()
    df = load(a.log, a.cache)
    results = {}
    for (unit, depth), window in itertools.product([("node card", 3), ("midplane", 2)], [600, 3600]):
        key = f"{unit}, {window // 60}-minute window"
        results[key] = run(df, window, depth, a.windows)
        print(key, json.dumps(results[key]["methods"]), flush=True)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    Path(a.out, "bgl_eval.json").write_text(json.dumps(results, indent=2))
    lines = ["| unit, window | positive rate | method | AUROC (pooled) | AUROC (mean per window) | AP |", "|---|---|---|---|---|---|"]
    for key, r in results.items():
        for name, m in r["methods"].items():
            lines.append(f"| {key} | {r['positive_rate']:.2f} | {name} | {m['AUROC_pooled']:.3f} | {m['AUROC_per_window_mean']:.3f} | {m['AP']:.3f} |")
    Path(a.out, "bgl_eval.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
