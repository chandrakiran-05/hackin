"""
Tests for the attack-simulation pipeline.

These tests assert that outcomes come from the *real* defense modules - that
the simulators never invent blocked/allowed results - and that cancellation,
counter invariants and the defense reset paths behave correctly.

Run with:  python -m pytest simulation/test_simulation.py -q
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulation.attacks.ddos_simulation import DDoSSimulator
from simulation.attacks.sql_injection_simulation import SQLInjectionSimulator
from simulation.defenses.rate_limiter import RateLimiter
from simulation.defenses.sql_injection_defense import SQLInjectionDefense


# --------------------------------------------------------------------------
# SQL injection: outcomes must be the real detector's decision
# --------------------------------------------------------------------------
def test_sqli_union_payloads_are_really_detected():
    defense = SQLInjectionDefense()
    sim = SQLInjectionSimulator(defense=defense)
    # benign_ratio=0 -> every query is a malicious payload.
    snap = sim.start_attack("union", duration=2, threads=2, benign_ratio=0.0)

    assert snap["malicious_sent"] >= 1
    # UNION payloads are caught by the real defense -> 100% detection.
    assert snap["blocked"] == snap["malicious_sent"]
    assert snap["detection_rate"] == 100.0
    # Counter invariant.
    assert snap["blocked"] + snap["allowed"] == snap["queries_attempted"]


def test_sqli_benign_traffic_is_not_a_false_positive():
    defense = SQLInjectionDefense()
    sim = SQLInjectionSimulator(defense=defense)
    # benign_ratio=1 -> every query is legitimate control traffic.
    snap = sim.start_attack("basic", duration=2, threads=2, benign_ratio=1.0)

    assert snap["benign_sent"] >= 1
    # The real detector must not flag ordinary input.
    assert snap["benign_blocked"] == 0


def test_sqli_without_defense_does_not_fabricate_blocks():
    # With no defense wired, the simulator must not invent a "blocked" outcome.
    sim = SQLInjectionSimulator(defense=None)
    snap = sim.start_attack("ddl", duration=1, threads=1, benign_ratio=0.0)
    assert snap["blocked"] == 0


# --------------------------------------------------------------------------
# DDoS: outcomes must be the real rate limiter's decision
# --------------------------------------------------------------------------
def test_ddos_requests_are_really_rate_limited():
    limiter = RateLimiter(max_requests=5, time_window=60)
    sim = DDoSSimulator(defense=limiter, bank_client=None,
                        source_ips=["10.1.1.1", "10.1.1.2"])
    snap = sim.start_attack("http", duration=2, threads=2)

    assert snap["requests_generated"] > 0
    # Counter invariant: every request is either allowed or blocked.
    assert snap["allowed"] + snap["blocked"] == snap["requests_generated"]
    # The limiter allows at most max_requests per source IP, so a flood is
    # mostly blocked and the allowed count is bounded by the pool.
    assert snap["allowed"] <= 5 * 2
    assert snap["blocked"] > 0


def test_ddos_cancellation_stops_promptly():
    limiter = RateLimiter(max_requests=10, time_window=60)
    sim = DDoSSimulator(defense=limiter, bank_client=None)
    cancel = threading.Event()

    result = {}

    def run():
        result["snap"] = sim.start_attack("http", duration=30, threads=3,
                                          cancel_event=cancel)

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.5)
    cancel.set()
    t.join(timeout=8)
    assert not t.is_alive(), "cancellation did not stop the run"
    assert result["snap"]["requests_generated"] > 0


# --------------------------------------------------------------------------
# Defense reset paths
# --------------------------------------------------------------------------
def test_rate_limiter_reset_clears_blocks():
    limiter = RateLimiter(max_requests=2, time_window=60)
    ip = "198.51.100.7"
    for _ in range(5):
        limiter.is_allowed(ip)
    assert ip in limiter.blocked_ips
    limiter.reset()
    assert limiter.blocked_ips == set()
    # After reset the IP is allowed again.
    assert limiter.is_allowed(ip) is True


def test_sql_defense_reset_zeroes_counters():
    defense = SQLInjectionDefense()
    defense.check_query("' OR 1=1 --", "203.0.113.9")
    assert defense.get_stats()["total_attempts"] > 0
    defense.reset()
    stats = defense.get_stats()
    assert stats["total_attempts"] == 0
    assert stats["blocked_attempts"] == 0
    assert stats["allowed_queries"] == 0
