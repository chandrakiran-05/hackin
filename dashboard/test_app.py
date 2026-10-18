"""
Tests for the dashboard control plane.

Covers input validation, the concurrency cap, cancellation/reset, the bank
allowlist and the real-outcome reporting of the defense probes. Uses Flask's
test client so no real server/port is needed.

Run with:  python -m pytest dashboard/test_app.py -q
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dashboard import app as dash


@pytest.fixture
def client():
    dash.app.config["TESTING"] = True
    with dash.app.test_client() as c:
        yield c
    # Ensure no run leaks between tests.
    dash.manager.reset()


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"BANKING SECURITY SIMULATION" in r.data


def test_start_ddos_rejects_bad_type(client):
    r = client.post("/start_ddos", json={"type": "nope", "duration": 5, "threads": 2})
    assert r.status_code == 400
    assert r.get_json()["status"] == "error"


def test_start_ddos_rejects_out_of_range(client):
    r = client.post("/start_ddos", json={"type": "http", "duration": 99999, "threads": 2})
    assert r.status_code == 400
    r2 = client.post("/start_ddos", json={"type": "http", "duration": 5, "threads": 9999})
    assert r2.status_code == 400


def test_start_sql_rejects_ddos_type(client):
    # A SQL run must use a SQL technique, not an http/udp/syn profile.
    r = client.post("/start_sql", json={"type": "http", "duration": 5, "threads": 2})
    assert r.status_code == 400


def test_concurrency_cap(client):
    r1 = client.post("/start_ddos", json={"type": "http", "duration": 5, "threads": 2})
    assert r1.status_code == 200
    r2 = client.post("/start_ddos", json={"type": "http", "duration": 5, "threads": 2})
    assert r2.status_code == 409  # busy
    client.post("/stop_ddos")


def test_stop_and_reset(client):
    client.post("/start_sql", json={"type": "union", "duration": 10, "threads": 2})
    time.sleep(0.6)
    status = client.get("/get_status").get_json()
    assert status["sql_active"] is True

    stop = client.post("/stop_sql").get_json()
    assert stop["status"] == "stopping"
    time.sleep(1.0)
    assert client.get("/get_status").get_json()["sql_active"] is False

    client.post("/reset")
    s = client.get("/get_status").get_json()
    assert s["stats"]["sql_attempts"] == 0
    assert s["stats"]["rate_limited_ips"] == 0


def test_defense_probe_reports_real_result(client):
    r = client.post("/test_defense",
                    json={"type": "sql_injection", "query": "' UNION SELECT a,b FROM users --"})
    data = r.get_json()
    assert data["action"] == "BLOCKED"
    assert data["safe"] is False

    r2 = client.post("/test_defense",
                     json={"type": "sql_injection", "query": "Jane Doe"})
    data2 = r2.get_json()
    assert data2["action"] == "ALLOWED"
    assert data2["safe"] is True


def test_rate_limit_probe_blocks(client):
    r = client.post("/test_defense", json={"type": "rate_limit", "ip": "192.0.2.123"})
    data = r.get_json()
    # Default limiter allows 10, probe sends 15, so it must block part way.
    assert data["blocked_at"] is not None
    assert 1 <= data["blocked_at"] <= 15


def test_target_config_rejects_non_allowlisted_host(client):
    r = client.post("/config", json={"target_url": "http://evil.example.com:9000"})
    assert r.status_code == 400
    assert "allowlist" in r.get_json()["message"]


def test_scenario_validation(client):
    r = client.post("/run_scenario", json={"fraud_amount": -5})
    assert r.status_code == 400


def test_scenario_reports_unreachable_without_fabricating(client):
    # Point at a guaranteed-closed loopback port so the test is deterministic
    # regardless of whether anything else is bound locally.
    cfg = client.post("/config", json={"target_url": "http://127.0.0.1:65533"})
    assert cfg.status_code == 200
    # With no reachable target, the scenario must report the real unreachable
    # outcome - never a fabricated "caught" result.
    r = client.post("/run_scenario", json={
        "account": "ACC-123", "to_acct": "MULE-9", "currency": "USD",
        "baseline_amount": 100, "fraud_amount": 50000, "source": "Moscow"})
    assert r.status_code == 200
    result = r.get_json()["result"]
    assert result["account"] == "ACC-123"
    assert result["fraud"]["ok"] is False          # target not running in tests
    assert result["fraud"]["error"]                 # a real error string
    assert result["caught"] is False                # not fabricated


def test_dataset_lists_real_accounts(client):
    d = client.get("/dataset").get_json()
    assert d["count"] >= 1
    row = d["rows"][0]
    assert "from_acct" in row and "to_acct" in row and "amount" in row
    # account id uses the <Bank>-<Account> convention
    assert "-" in row["from_acct"]


def test_dataset_reads_registry_accounts_format(client, tmp_path):
    # RiskFabric registry format: acct,segment -> real known payers.
    csv = tmp_path / "accounts.csv"
    csv.write_text("acct,segment\nCUST-001,retail\nCUST-002,business\n")
    assert client.post("/config", json={"dataset_path": str(csv)}).status_code == 200
    d = client.get("/dataset").get_json()
    assert "registry" in (d.get("format") or "")
    assert d["count"] == 2
    assert d["rows"][0]["from_acct"] == "CUST-001"
    assert d["rows"][0]["segment"] == "retail"


def test_console_feed_reports_unreachable_without_console(client):
    # Pin to a guaranteed-closed port so the test is deterministic.
    assert client.post("/config", json={"console_url": "http://127.0.0.1:65532"}).status_code == 200
    f = client.get("/console_feed").get_json()
    assert f["reachable"] is False
    assert f["holds"] == []


def test_config_rejects_non_allowlisted_console(client):
    r = client.post("/config", json={"console_url": "http://evil.example.com:8500"})
    assert r.status_code == 400


def test_range_scenarios_and_start_status(client):
    # point the target at a closed port so the range uses the local scorer
    client.post("/config", json={"target_url": "http://127.0.0.1:65531"})
    sc = client.get("/range/scenarios").get_json()
    assert any(s["id"] == "credential_impersonation" for s in sc["scenarios"])
    assert sc["identities"][0]["secret"] == "***redacted***"

    r = client.post("/range/start", json={"scenario": "credential_impersonation",
                                          "mode": "baseline", "seed": 7, "intensity": 1})
    assert r.status_code == 200
    run_id = r.get_json()["run_id"]
    # live run; poll until it completes
    for _ in range(40):
        st = client.get("/range/status?run_id=" + run_id).get_json()
        if st["status"] != "RUNNING":
            break
        time.sleep(0.2)
    assert st["status"] in ("COMPLETED", "STOPPED")
    assert st["metrics"]["total_attempts"] > 0


def test_range_start_validation(client):
    assert client.post("/range/start", json={"scenario": "nope"}).status_code == 400
    assert client.post("/range/start", json={"scenario": "sql_injection",
                                             "intensity": 99}).status_code == 400


def test_range_compare_and_export(client):
    client.post("/config", json={"target_url": "http://127.0.0.1:65531"})
    cmp = client.post("/range/compare", json={"scenario": "credential_impersonation",
                                              "seed": 7, "intensity": 1}).get_json()
    assert len(cmp["matrix"]) == 3
    base = next(r for r in cmp["matrix"] if r["mode"] == "baseline")
    assert base["compromise_state"] == "COMPROMISED"
    rid = cmp["results"]["classical"]["run_id"]
    csv = client.get("/range/export?run_id=" + rid + "&fmt=csv")
    assert csv.status_code == 200
    assert "correlation_id" in csv.get_data(as_text=True).splitlines()[0]


def test_status_exposes_attack_map(client):
    s = client.get("/get_status").get_json()
    assert "map" in s
    assert s["map"]["server"]["label"]
    assert len(s["map"]["sources"]) >= 1
    assert "lat" in s["map"]["sources"][0] and "ip" in s["map"]["sources"][0]
