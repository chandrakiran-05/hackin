"""
Tests for the cyber-range engine.

These use the deterministic local classical scorer (no network) so the
attack-vs-defense outcomes are reproducible, and they lock in the acceptance
criteria: unique run ids, no double counting across layers, ground-truth
accounting, and the baseline-vs-RiskFabric outcome difference.

Run: python -m pytest simulation/test_cyber_range.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulation.cyber_range import (
    CyberRange, scenario_catalogue, public_identities, OUTCOMES)


def _run(scenario, mode, seed=7):
    cr = CyberRange(live_delay=0)          # default = local classical scorer
    run_id = cr.start(scenario, mode=mode, seed=seed, intensity=1, live=False)
    return cr, cr.status(run_id)


def test_catalogue_and_identities():
    cat = scenario_catalogue()
    assert any(s["id"] == "credential_impersonation" for s in cat)
    for s in cat:
        assert s["objective"] and s["ground_truth"]
    # identities never expose the seeded secret
    for ident in public_identities():
        assert ident["secret"] == "***redacted***"


def test_unique_run_ids():
    cr = CyberRange(live_delay=0)
    a = cr.start("sql_injection", mode="baseline", seed=1, live=False)
    b = cr.start("sql_injection", mode="baseline", seed=1, live=False)
    assert a != b


def test_no_double_counting_and_ground_truth_accounting():
    _, st = _run("credential_impersonation", "quantum")
    m = st["metrics"]
    # each attempt has exactly one final outcome
    assert sum(m["outcome_counts"].values()) == m["total_attempts"]
    # ground-truth confusion matrix partitions every attempt
    assert (m["true_positive"] + m["false_positive"] + m["false_negative"]
            + m["true_negative"]) == m["total_attempts"]


def test_riskfabric_changes_the_outcome():
    # Baseline misses stolen-credential fraud; RiskFabric contains it.
    _, base = _run("credential_impersonation", "baseline")
    _, cls = _run("credential_impersonation", "classical")
    assert base["metrics"]["unauthorized_completed"] > 0
    assert base["compromise"]["state"] == "COMPROMISED"
    assert cls["metrics"]["unauthorized_completed"] == 0
    assert cls["compromise"]["state"] in ("CONTAINED", "BLOCKED")
    assert cls["metrics"]["recall"] == 1.0


def test_edge_block_not_counted_as_app_block():
    # SQLi payloads are stopped at the edge WAF, never reach the app layer.
    _, st = _run("sql_injection", "quantum")
    m = st["metrics"]
    assert m["edge_blocks_total"] > 0
    assert m["unauthorized_completed"] == 0
    # malicious injection attempts end as edge_blocked, not as an app block
    assert m["outcome_counts"]["edge_blocked"] > 0


def test_broken_authorization_denied_at_app():
    _, st = _run("broken_authorization", "classical")
    m = st["metrics"]
    assert m["app_authz_denied"] > 0
    assert m["unauthorized_completed"] == 0


def test_compare_runs_three_modes():
    cr = CyberRange(live_delay=0)
    out = cr.compare("suspicious_transaction", seed=3, intensity=1)
    modes = {r["mode"] for r in out["matrix"]}
    assert modes == {"baseline", "classical", "quantum"}
    base = next(r for r in out["matrix"] if r["mode"] == "baseline")
    cls = next(r for r in out["matrix"] if r["mode"] == "classical")
    assert base["unauthorized_completed"] >= cls["unauthorized_completed"]


def test_export_json_and_csv():
    cr = CyberRange(live_delay=0)
    rid = cr.start("broken_authorization", mode="classical", seed=5, live=False)
    js, ctype = cr.export(rid, "json")
    assert ctype == "application/json" and js["run"]["run_id"] == rid
    csv, ctype2 = cr.export(rid, "csv")
    assert ctype2 == "text/csv" and "correlation_id" in csv.splitlines()[0]


def test_quantum_offline_is_labelled_not_faked():
    # With the local scorer, quantum mode must NOT claim a quantum backend.
    _, st = _run("suspicious_transaction", "quantum")
    backends = st["metrics"]["backends"]
    assert all("quantum backend unavailable" in b or "local-classical" in b for b in backends)
    assert st["metrics"]["quantum_used"] == 0
