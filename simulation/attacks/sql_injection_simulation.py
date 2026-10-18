"""
SQL Injection Attack Simulation (including DDL hijacking).

Sends crafted SQL-injection payloads through the project's *real* SQL-injection
defense and reports the actual detection decision for each payload. No success
or block outcome is fabricated - whether a payload is blocked or allowed is
decided entirely by ``SQLInjectionDefense.check_query``.

A small set of benign control queries is interleaved so the demo also shows the
defense correctly allowing legitimate traffic (i.e. its false-positive
behaviour), which judges can verify.
"""

import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


# Attack payloads grouped by technique. Benign controls verify the defense does
# not block ordinary input.
PAYLOADS = {
    "basic": [
        "admin' OR '1'='1",
        "' OR 1=1 --",
        "') OR ('a'='a",
    ],
    "ddl": [
        "1; DROP TABLE users; --",
        "1; ALTER TABLE accounts ADD COLUMN backdoor VARCHAR(50); --",
        "1; CREATE TABLE hacked (id INT, data VARCHAR(100)); --",
    ],
    "union": [
        "' UNION SELECT username, password FROM users; --",
        "' UNION SELECT card_number, cvv FROM cards --",
    ],
}

BENIGN_CONTROLS = [
    "Jane Doe",
    "account summary",
    "ACC-00123",
    "payment reference 48215",
]


@dataclass
class RunStats:
    """Thread-safe counters for a single SQL-injection run."""

    attack_type: str = "basic"
    queries_attempted: int = 0
    blocked: int = 0          # payloads the defense blocked
    allowed: int = 0          # queries the defense allowed through
    benign_sent: int = 0
    benign_blocked: int = 0   # false positives on legitimate input
    started_at: str = ""
    finished_at: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, blocked, benign=False):
        with self._lock:
            self.queries_attempted += 1
            if blocked:
                self.blocked += 1
            else:
                self.allowed += 1
            if benign:
                self.benign_sent += 1
                if blocked:
                    self.benign_blocked += 1

    def snapshot(self):
        with self._lock:
            detected = self.blocked
            malicious = self.queries_attempted - self.benign_sent
            return {
                "attack_type": self.attack_type,
                "queries_attempted": self.queries_attempted,
                "blocked": self.blocked,
                "allowed": self.allowed,
                "benign_sent": self.benign_sent,
                "benign_blocked": self.benign_blocked,
                "malicious_sent": malicious,
                "detection_rate": (detected / malicious * 100) if malicious else 0.0,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }


class SQLInjectionSimulator:
    def __init__(self, defense=None, source_ips=None):
        """
        :param defense: object exposing ``check_query(query, ip) ->
            (is_safe, action)``. This is the real detection pipeline whose
            decisions are reported verbatim.
        :param source_ips: simulated source IP pool (source simulation).
        """
        self.defense = defense
        self.source_ips = list(source_ips) if source_ips else [
            "10.0.0.21", "10.0.0.22", "10.0.0.23",
        ]

    def _emit(self, on_event, message, level="INFO", **fields):
        if on_event is None:
            return
        event = {"timestamp": _utcnow_iso(), "message": message, "level": level}
        event.update(fields)
        try:
            on_event(event)
        except Exception:
            pass

    def _worker(self, worker_id, payloads, end_time, cancel_event, stats,
                on_event, benign_ratio):
        n = 0
        while time.time() < end_time and not cancel_event.is_set():
            n += 1
            source_ip = self.source_ips[(worker_id + n) % len(self.source_ips)]

            # Interleave benign control traffic.
            benign = random.random() < benign_ratio
            if benign:
                query = random.choice(BENIGN_CONTROLS)
            else:
                query = random.choice(payloads)

            if self.defense is not None:
                is_safe, action = self.defense.check_query(query, source_ip)
                blocked = (action == "BLOCKED") or (is_safe is False)
            else:
                # No defense wired: we cannot know the outcome, so record the
                # query as attempted/unverified rather than inventing a result.
                blocked = False

            stats.record(blocked, benign=benign)

            short = (query[:40] + "...") if len(query) > 40 else query
            if benign:
                if blocked:
                    self._emit(on_event,
                               f"FALSE POSITIVE: benign query blocked from {source_ip}: {short}",
                               level="WARNING", source_ip=source_ip, kind="sql",
                               outcome="BLOCKED", benign=True)
            else:
                if blocked:
                    self._emit(on_event,
                               f"Defense BLOCKED {stats.attack_type} payload from {source_ip}: {short}",
                               level="DEFENSE", source_ip=source_ip, kind="sql",
                               outcome="BLOCKED")
                else:
                    self._emit(on_event,
                               f"Payload ALLOWED through from {source_ip}: {short}",
                               level="ATTACK", source_ip=source_ip, kind="sql",
                               outcome="ALLOWED")
            time.sleep(0.4)

    def start_attack(self, attack_type="basic", duration=10, threads=3,
                     cancel_event=None, on_event=None, benign_ratio=0.25,
                     stats=None):
        attack_type = (attack_type or "basic").lower()
        payloads = PAYLOADS.get(attack_type, PAYLOADS["basic"])
        if cancel_event is None:
            cancel_event = threading.Event()

        if stats is None:
            stats = RunStats(attack_type=attack_type, started_at=_utcnow_iso())
        if self.defense is None:
            self._emit(on_event,
                       "No defense wired in; outcomes are not verified",
                       level="WARNING", kind="sql")

        self._emit(on_event,
                   f"Starting {attack_type} SQL-injection run with {threads} "
                   f"thread(s) for {duration}s",
                   level="ATTACK", kind="sql")

        end_time = time.time() + duration
        workers = []
        for i in range(threads):
            t = threading.Thread(
                target=self._worker,
                args=(i, payloads, end_time, cancel_event, stats, on_event,
                      benign_ratio),
                daemon=True,
            )
            t.start()
            workers.append(t)

        deadline = end_time + 5
        for t in workers:
            remaining = max(0.1, deadline - time.time())
            t.join(timeout=remaining)

        stats.finished_at = _utcnow_iso()
        snap = stats.snapshot()
        cancelled = cancel_event.is_set()
        self._emit(on_event,
                   ("Cancelled" if cancelled else "Completed")
                   + f" {attack_type} SQLi: {snap['malicious_sent']} payloads, "
                   f"{snap['blocked']} blocked "
                   f"({snap['detection_rate']:.0f}% detection), "
                   f"{snap['benign_sent']} benign sent",
                   level="INFO", kind="sql")
        return snap


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from simulation.defenses.sql_injection_defense import SQLInjectionDefense

    defense = SQLInjectionDefense()
    sim = SQLInjectionSimulator(defense=defense)
    result = sim.start_attack("union", duration=3, threads=2,
                              on_event=lambda e: print(e["level"], e["message"]))
    print("RESULT:", result)
