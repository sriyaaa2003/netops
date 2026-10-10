"""Per-component features for the trained detector. The column order is part of the model's contract."""
from collections import defaultdict

import numpy as np

LEVELS = ["INFO", "WARNING", "ERROR", "SEVERE", "FATAL", "FAILURE"]
SUBSYSTEMS = ["KERNEL", "APP", "MMCS", "DISCOVERY", "LINKCARD", "MONITOR", "HARDWARE", "CMCS"]
COLUMNS = LEVELS + ["sub_" + s for s in SUBSYSTEMS] + ["sub_OTHER", "n_lines", "n_openings"]


def opening(message):
    """The first three words of a message: a cheap stand-in for its template."""
    return " ".join(str(message or "").split()[:3])


def build(logs):
    """One row per component with the COLUMNS above. Returns (components, matrix)."""
    acc = defaultdict(lambda: {"vec": np.zeros(len(COLUMNS) - 2), "n": 0, "open": set()})
    for e in logs:
        sev = e.get("severity")
        if sev not in LEVELS:
            continue
        a = acc[e.get("component", "unknown")]
        a["vec"][LEVELS.index(sev)] += 1
        sub = e.get("subsystem")
        a["vec"][len(LEVELS) + (SUBSYSTEMS.index(sub) if sub in SUBSYSTEMS else len(SUBSYSTEMS))] += 1
        a["n"] += 1
        a["open"].add(opening(e.get("message")))
    components = sorted(acc)
    matrix = np.array([np.concatenate([acc[c]["vec"], [acc[c]["n"], len(acc[c]["open"])]]) for c in components], dtype=float)
    return components, matrix.reshape(len(components), len(COLUMNS))
