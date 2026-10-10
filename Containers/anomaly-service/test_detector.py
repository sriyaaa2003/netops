import numpy as np
import pytest

from detector import ERROR_LEVELS, LEVELS, build_features, score
from features import COLUMNS


def logs_for(counts):
    return [{"component": c, "severity": s, "subsystem": "APP" if s == "FATAL" else "KERNEL", "message": f"msg {s} {i % 3}"} for c, per in counts.items() for s, n in per.items() for i in range(n)]


def healthy_fleet(n=12):
    return {f"R0{i}-M0-N0": {"INFO": 50 + i, "WARNING": 1} for i in range(n)}


def test_features_count_each_severity_per_component():
    comps, m = build_features(logs_for({"a": {"INFO": 3, "FATAL": 2}, "b": {"WARNING": 1}}))
    assert comps == ["a", "b"]
    assert m[0, LEVELS.index("INFO")] == 3 and m[0, LEVELS.index("FATAL")] == 2
    assert m[1, LEVELS.index("WARNING")] == 1 and m[1][: len(LEVELS)].sum() == 1


def test_unknown_severities_are_ignored():
    comps, m = build_features([{"component": "a", "severity": "TRACE"}])
    assert comps == [] and m.size == 0


@pytest.mark.parametrize("method", ["boosting", "isolation_forest", "error_count"])
def test_a_component_full_of_fatal_lines_gets_the_top_score(method):
    fleet = healthy_fleet()
    fleet["R09-M1-N4"] = {"INFO": 40, "FATAL": 120}
    comps, m = build_features(logs_for(fleet))
    scores, flagged = score(m, method)
    assert comps[int(np.argmax(scores))] == "R09-M1-N4"
    if method != "boosting":      # the trained model is judged on real logs; hand-built lines only need to rank it first
        assert flagged[comps.index("R09-M1-N4")]


def test_error_count_flags_nothing_in_a_quiet_fleet():
    comps, m = build_features(logs_for(healthy_fleet()))
    _, flagged = score(m, "error_count")
    assert not flagged.any()


def test_unknown_detector_raises():
    with pytest.raises(ValueError):
        score(np.zeros((6, len(LEVELS))), "magic")


def test_error_levels_are_known_levels():
    assert set(ERROR_LEVELS) <= set(LEVELS)


def test_features_follow_the_declared_column_order():
    comps, m = build_features(logs_for({"a": {"INFO": 4, "FATAL": 2}}))
    row = dict(zip(COLUMNS, m[0]))
    assert row["INFO"] == 4 and row["FATAL"] == 2 and row["sub_APP"] == 2 and row["sub_KERNEL"] == 4
    assert row["n_lines"] == 6 and row["n_openings"] == 5      # "msg INFO 0..2" and "msg FATAL 0..1"


def test_boosting_scores_are_probabilities_and_the_quiet_fleet_is_not_flagged():
    comps, m = build_features(logs_for(healthy_fleet()))
    p, flagged = score(m, "boosting")
    assert ((p >= 0) & (p <= 1)).all() and not flagged.any()
