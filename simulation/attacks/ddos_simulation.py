"""
DDoS Attack Simulation.

Generates controlled, high-rate request traffic against the project's own
defensive pipeline (the rate limiter) and, optionally, an explicitly
allow-listed banking target. Every outcome reported by this simulator is the
*real* decision made by the defense / target - nothing about success, blocking
or detection is fabricated.

Design notes
------------
* The simulator owns no long-lived mutable counters that leak between runs.
  Each call to :meth:`start_attack` runs against a fresh :class:`RunStats`
  object, so concurrent or back-to-back runs never corrupt each other.
* Cancellation is cooperative via a :class:`threading.Event`; threads check it
  every iteration and exit promptly.
* All counters are updated under a lock, so thread counts > 1 cannot lose
  increments.
* Structured events are emitted through an ``on_event`` callback instead of the
  old ``print``-monkeypatching scheme, which was not thread safe.
"""

import time
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunStats:
    """Thread-safe counters for a single DDoS run."""

    attack_type: str = "http"
    requests_generated: int = 0          # total requests the attacker emitted
    allowed: int = 0                     # passed the rate limiter
    blocked: int = 0                     # rate-limited by the defense
    bank_checked: int = 0                # forwarded to the bank target
    bank_responses: dict = field(default_factory=dict)  # status -> count
    errors: int = 0
    started_at: str = ""
    finished_at: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, allowed, bank_status=None, error=False):
        with self._lock:
            self.requests_generated += 1
            if allowed:
                self.allowed += 1
            else:
                self.blocked += 1
            if bank_status is not None:
                self.bank_checked += 1
                self.bank_responses[bank_status] = self.bank_responses.get(bank_status, 0) + 1
            if error:
                self.errors += 1

    def snapshot(self):
        with self._lock:
            return {
                "attack_type": self.attack_type,
                "requests_generated": self.requests_generated,
                "allowed": self.allowed,
                "blocked": self.blocked,
                "bank_checked": self.bank_checked,
                "bank_responses": dict(self.bank_responses),
                "errors": self.errors,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }


# Per-profile pacing. These only change how fast requests are emitted and how
# they are labelled; they never change how outcomes are decided.
ATTACK_PROFILES = {
    "http": {"label": "HTTP flood", "delay": 0.01},
    "udp": {"label": "UDP flood", "delay": 0.002},
    "syn": {"label": "SYN flood", "delay": 0.004},
}


class DDoSSimulator:
    def __init__(self, target_ip="127.0.0.1", target_port=80,
                 defense=None, bank_client=None, source_ips=None):
        """
        :param defense: object exposing ``is_allowed(ip) -> bool`` (the rate
            limiter). Required for real outcomes; if omitted, requests are
            counted but every request is treated as ``allowed`` and a warning
            is emitted (used only for standalone demos).
        :param bank_client: optional object exposing
            ``probe(source_ip) -> (status, detail)`` used to record the real
            defensive response from the banking target for a sampled subset of
            allowed requests.
        :param source_ips: iterable of simulated source IPs to spread traffic
            across (source simulation). Defaults to a small lab pool.
        """
        self.target_ip = target_ip
        self.target_port = target_port
        self.defense = defense
        self.bank_client = bank_client
        self.source_ips = list(source_ips) if source_ips else [
            "10.0.0.11", "10.0.0.12", "10.0.0.13", "10.0.0.14", "10.0.0.15",
        ]

    def _emit(self, on_event, message, level="INFO", **fields):
        if on_event is None:
            return
        event = {"timestamp": _utcnow_iso(), "message": message, "level": level}
        event.update(fields)
        try:
            on_event(event)
        except Exception:
            # A faulty consumer must never crash the attack thread.
            pass

    def _flood_worker(self, worker_id, profile, end_time, cancel_event,
                      stats, on_event, bank_sample_every):
        delay = profile["delay"]
        n = 0
        while time.time() < end_time and not cancel_event.is_set():
            n += 1
            # Spread traffic across the simulated source pool.
            source_ip = self.source_ips[(worker_id + n) % len(self.source_ips)]

            if self.defense is not None:
                allowed = self.defense.is_allowed(source_ip)
            else:
                allowed = True

            bank_status = None
            # Only forward a small sample of *allowed* requests to the bank so
            # we verify the real response without overwhelming the target.
            if allowed and self.bank_client is not None and bank_sample_every \
                    and (stats.requests_generated % bank_sample_every == 0):
                try:
                    bank_status, detail = self.bank_client.probe(source_ip)
                    self._emit(on_event,
                               f"Bank response for {source_ip}: {bank_status}"
                               + (f" ({detail})" if detail else ""),
                               level="INFO", source_ip=source_ip,
                               bank_status=bank_status, kind="ddos")
                except Exception as exc:  # pragma: no cover - defensive
                    stats.record(allowed, bank_status=None, error=True)
                    self._emit(on_event, f"Bank probe error: {exc}",
                               level="WARNING", kind="ddos")
                    continue

            stats.record(allowed, bank_status=bank_status)

            if not allowed and stats.blocked % 25 == 1:
                self._emit(on_event,
                           f"Rate limiter blocked flood traffic from {source_ip}",
                           level="DEFENSE", source_ip=source_ip, kind="ddos")

            if delay:
                time.sleep(delay)

    def start_attack(self, attack_type="http", duration=10, threads=5,
                     cancel_event=None, on_event=None, bank_sample_every=50,
                     stats=None):
        """
        Run a DDoS simulation and return a :class:`RunStats` snapshot dict.

        This call blocks until the run finishes or ``cancel_event`` is set. The
        dashboard runs it inside a background thread. A caller may pass its own
        ``stats`` object (exposing the same API) so it can read live progress
        while the run is in flight.
        """
        attack_type = (attack_type or "http").lower()
        profile = ATTACK_PROFILES.get(attack_type, ATTACK_PROFILES["http"])
        if cancel_event is None:
            cancel_event = threading.Event()

        if stats is None:
            stats = RunStats(attack_type=attack_type, started_at=_utcnow_iso())
        if self.defense is None:
            self._emit(on_event,
                       "No defense wired in; outcomes are not verified",
                       level="WARNING", kind="ddos")

        self._emit(on_event,
                   f"Starting {profile['label']} with {threads} thread(s) for "
                   f"{duration}s across {len(self.source_ips)} source IPs",
                   level="ATTACK", kind="ddos")

        end_time = time.time() + duration
        workers = []
        for i in range(threads):
            t = threading.Thread(
                target=self._flood_worker,
                args=(i, profile, end_time, cancel_event, stats, on_event,
                      bank_sample_every),
                daemon=True,
            )
            t.start()
            workers.append(t)

        # Join with a bounded timeout so a wedged worker cannot hang the server.
        deadline = end_time + 5
        for t in workers:
            remaining = max(0.1, deadline - time.time())
            t.join(timeout=remaining)

        stats.finished_at = _utcnow_iso()
        snap = stats.snapshot()
        cancelled = cancel_event.is_set()
        self._emit(on_event,
                   ("Cancelled" if cancelled else "Completed")
                   + f" {profile['label']}: {snap['requests_generated']} requests, "
                   f"{snap['allowed']} allowed, {snap['blocked']} blocked by defense",
                   level="INFO", kind="ddos")
        return snap


if __name__ == "__main__":
    # Standalone demo wires the real rate limiter so outcomes are genuine.
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from simulation.defenses.rate_limiter import RateLimiter

    limiter = RateLimiter(max_requests=10, time_window=60)
    sim = DDoSSimulator(defense=limiter)
    result = sim.start_attack("http", duration=3, threads=4,
                              on_event=lambda e: print(e["level"], e["message"]))
    print("RESULT:", result)
