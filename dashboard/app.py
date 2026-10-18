"""
Security Simulation Dashboard.

A Flask control plane for the banking attack-simulation system. It drives the
existing attack simulators against the existing defensive pipeline (rate
limiter + SQL-injection defense) and, when configured, verifies the *real*
response from an allow-listed banking target. Every number shown on the
dashboard comes from a real defense decision or a real HTTP response - the
dashboard never fabricates outcomes.

Reliability features:
* A single :class:`RunManager` owns all shared state behind one lock.
* Each attack runs with an isolated set of counters and a cancellation
  ``Event`` so runs can be stopped cleanly and never corrupt each other.
* Concurrency is capped (one run per attack kind) so repeated clicks cannot
  spawn unbounded background threads.
* Inputs are validated and the bank target is checked against an allowlist.
"""

import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Flask, render_template, jsonify, request

# Ensure the project root is on sys.path so this script works when run directly
# as `python dashboard/app.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulation.attacks.ddos_simulation import DDoSSimulator, RunStats as DDoSStats
from simulation.attacks.sql_injection_simulation import (
    SQLInjectionSimulator, RunStats as SQLStats)
from simulation.defenses.rate_limiter import RateLimiter
from simulation.defenses.sql_injection_defense import SQLInjectionDefense

try:
    import requests  # used for real bank response verification
except Exception:  # pragma: no cover - requests should be installed
    requests = None

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration (with safe defaults; adjustable at runtime within limits)
# ---------------------------------------------------------------------------
DEFAULT_BANK_URL = os.getenv("RF_BANK_URL", "http://127.0.0.1:9000")
MAX_THREADS = int(os.getenv("SIM_MAX_THREADS", "20"))
MAX_DURATION = int(os.getenv("SIM_MAX_DURATION", "120"))
MAX_LOGS = 300

VALID_DDOS_TYPES = {"http", "udp", "syn"}
VALID_SQL_TYPES = {"basic", "ddl", "union"}

# Hosts the simulator is permitted to send verification traffic to. Only loopback
# lab targets are allowed by default; adding a target requires editing this set.
TARGET_ALLOWLIST = {"127.0.0.1", "localhost", "::1"}


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def _host_allowed(url):
    try:
        host = urlparse(url).hostname
    except Exception:
        return False
    return host in TARGET_ALLOWLIST


# ---------------------------------------------------------------------------
# Bank client - verifies the real defensive response from the banking target
# ---------------------------------------------------------------------------
class BankClient:
    """Thin client that records the bank's actual response. Never fabricates."""

    def __init__(self, base_url=DEFAULT_BANK_URL, timeout=2.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._counter = 0
        self._lock = threading.Lock()

    def _next_txn(self):
        with self._lock:
            self._counter += 1
            return f"sim-{int(time.time())}-{self._counter}"

    def health(self):
        """Return (reachable: bool, detail: str)."""
        if requests is None:
            return False, "requests library unavailable"
        if not _host_allowed(self.base_url):
            return False, "target not in allowlist"
        try:
            r = requests.get(f"{self.base_url}/health", timeout=self.timeout)
            if r.status_code == 200:
                return True, r.json().get("status", "ok")
            return False, f"HTTP {r.status_code}"
        except Exception as exc:
            return False, str(exc)

    def probe(self, source_ip):
        """
        Send one payment-shaped request and return (status, detail) where
        ``status`` is the bank's real decision (ALLOW/VERIFY/HOLD) or an error
        marker (UNREACHABLE/ERROR). Does not raise on network failure so the
        caller can record the real outcome truthfully.
        """
        if requests is None:
            return "ERROR", "requests unavailable"
        if not _host_allowed(self.base_url):
            return "ERROR", "target not in allowlist"
        payload = {
            "txn_id": self._next_txn(),
            "amount": 100.0,
            "from_bank": "SIM_BANK",
            "from_account": "SIM_ACC",
            "to_bank": "TARGET_BANK",
            "to_account": "TARGET_ACC",
            "payment_format": "STANDARD",
            "timestamp": _utcnow_iso(),
        }
        try:
            r = requests.post(f"{self.base_url}/bank/pay", json=payload,
                              timeout=self.timeout,
                              headers={"X-Forwarded-For": source_ip})
            if r.status_code == 200:
                return r.json().get("status", "UNKNOWN"), None
            return "ERROR", f"HTTP {r.status_code}"
        except Exception as exc:
            return "UNREACHABLE", str(exc)


# ---------------------------------------------------------------------------
# Run manager - owns shared state and background runs
# ---------------------------------------------------------------------------
class RunManager:
    def __init__(self):
        self._lock = threading.RLock()
        self.rate_limiter = RateLimiter(max_requests=10, time_window=60)
        self.sql_defense = SQLInjectionDefense()
        self.bank_client = BankClient()
        self.bank_verify = True

        self._logs = deque(maxlen=MAX_LOGS)
        # Per-kind run handles: {kind: {"cancel": Event, "thread": Thread,
        #                               "stats": dict, "running": bool,
        #                               "params": {...}}}
        self._runs = {"ddos": None, "sql": None}
        self.add_event({"timestamp": _utcnow_iso(),
                        "message": "Dashboard initialised", "level": "INFO"})

    # -- logging ----------------------------------------------------------
    def add_event(self, event):
        # Normalise + stamp a wall-clock HH:MM:SS for the UI.
        event.setdefault("timestamp", _utcnow_iso())
        event["time"] = time.strftime("%H:%M:%S")
        event.setdefault("level", "INFO")
        with self._lock:
            self._logs.append(event)

    def logs(self, limit=50):
        with self._lock:
            return list(self._logs)[-limit:]

    def clear_logs(self):
        with self._lock:
            self._logs.clear()

    # -- run control ------------------------------------------------------
    def is_running(self, kind):
        with self._lock:
            handle = self._runs.get(kind)
            return bool(handle and handle["running"])

    def _start(self, kind, params, target, stats_ref=None):
        with self._lock:
            if self.is_running(kind):
                return False, f"{kind} run already in progress"
            cancel = threading.Event()
            handle = {"cancel": cancel, "thread": None, "stats": None,
                      "stats_ref": stats_ref, "running": True, "params": params,
                      "started_at": _utcnow_iso()}
            self._runs[kind] = handle

        def runner():
            try:
                stats = target(cancel, self._on_sim_event)
                with self._lock:
                    handle["stats"] = stats
            except Exception as exc:  # pragma: no cover - defensive
                self.add_event({"message": f"{kind} run error: {exc}",
                                "level": "ERROR", "kind": kind})
            finally:
                with self._lock:
                    handle["running"] = False

        t = threading.Thread(target=runner, daemon=True)
        with self._lock:
            handle["thread"] = t
        t.start()
        return True, f"{kind} run started"

    def _on_sim_event(self, event):
        # Live stats are read from stats_ref in _run_view; here we only need to
        # record the structured event for the log stream.
        self.add_event(event)

    def start_ddos(self, attack_type, duration, threads):
        sim = DDoSSimulator(defense=self.rate_limiter,
                            bank_client=self.bank_client if self.bank_verify else None)
        stats = DDoSStats(attack_type=attack_type, started_at=_utcnow_iso())

        def target(cancel, on_event):
            return sim.start_attack(attack_type, duration, threads,
                                    cancel_event=cancel, on_event=on_event,
                                    stats=stats)

        return self._start("ddos", {"type": attack_type, "duration": duration,
                                    "threads": threads}, target, stats_ref=stats)

    def start_sql(self, attack_type, duration, threads):
        sim = SQLInjectionSimulator(defense=self.sql_defense)
        stats = SQLStats(attack_type=attack_type, started_at=_utcnow_iso())

        def target(cancel, on_event):
            return sim.start_attack(attack_type, duration, threads,
                                    cancel_event=cancel, on_event=on_event,
                                    stats=stats)

        return self._start("sql", {"type": attack_type, "duration": duration,
                                   "threads": threads}, target, stats_ref=stats)

    def stop(self, kind):
        with self._lock:
            handle = self._runs.get(kind)
            if not handle or not handle["running"]:
                return False, f"no active {kind} run"
            handle["cancel"].set()
        self.add_event({"message": f"Cancellation requested for {kind} run",
                        "level": "WARNING", "kind": kind})
        return True, f"{kind} run cancelling"

    def stop_all(self):
        stopped = []
        for kind in ("ddos", "sql"):
            ok, _ = self.stop(kind)
            if ok:
                stopped.append(kind)
        return stopped

    def reset(self):
        """Cancel runs, clear defenses, logs and run handles."""
        self.stop_all()
        # Give cancelled threads a brief moment to observe the flag.
        deadline = time.time() + 3
        for kind in ("ddos", "sql"):
            handle = self._runs.get(kind)
            t = handle["thread"] if handle else None
            if t:
                t.join(timeout=max(0.1, deadline - time.time()))
        self.rate_limiter.reset()
        self.sql_defense.reset()
        with self._lock:
            self._runs = {"ddos": None, "sql": None}
            self._logs.clear()
        self.add_event({"message": "System reset: defenses, runs and logs cleared",
                        "level": "INFO"})

    # -- status -----------------------------------------------------------
    def _run_view(self, kind):
        with self._lock:
            handle = self._runs.get(kind)
            if not handle:
                return {"running": False, "stats": None, "params": None,
                        "started_at": None}
            # While running, read the live snapshot so stats climb in real time;
            # once finished, use the stored final snapshot.
            stats = handle.get("stats")
            ref = handle.get("stats_ref")
            if handle["running"] and ref is not None:
                stats = ref.snapshot()
            return {"running": handle["running"], "stats": stats,
                    "params": handle.get("params"),
                    "started_at": handle.get("started_at")}

    def status(self):
        ddos = self._run_view("ddos")
        sql = self._run_view("sql")
        rl_stats = self.rate_limiter.get_stats()
        sql_stats = self.sql_defense.get_stats()

        ddos_s = ddos["stats"] or {}
        sql_s = sql["stats"] or {}
        return {
            "ddos_active": ddos["running"],
            "sql_active": sql["running"],
            "runs": {"ddos": ddos, "sql": sql},
            "stats": {
                "ddos_requests": ddos_s.get("requests_generated", 0),
                "ddos_allowed": ddos_s.get("allowed", 0),
                "ddos_blocked": ddos_s.get("blocked", 0),
                "sql_attempts": sql_s.get("queries_attempted", 0),
                "sql_malicious": sql_s.get("malicious_sent", 0),
                "sql_blocked": sql_s.get("blocked", 0),
                "sql_allowed": sql_s.get("allowed", 0),
                "detection_rate": round(sql_s.get("detection_rate", 0.0), 1),
                "rate_limited_ips": rl_stats["blocked_ips"],
                "blocked_attempts": sql_stats["blocked_attempts"],
            },
            "defense_stats": {"rate_limiter": rl_stats, "sql_defense": sql_stats},
            "bank": {"configured_url": self.bank_client.base_url,
                     "verify_enabled": self.bank_verify,
                     "responses": ddos_s.get("bank_responses", {})},
            "config": {"max_threads": MAX_THREADS, "max_duration": MAX_DURATION,
                       "allowlist": sorted(TARGET_ALLOWLIST)},
            "logs": self.logs(limit=50),
        }


manager = RunManager()


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------
def _validate_run(data, valid_types, default_type, default_threads):
    attack_type = str(data.get("type", default_type)).lower()
    if attack_type not in valid_types:
        return None, f"invalid type '{attack_type}'; expected one of {sorted(valid_types)}"
    try:
        duration = int(data.get("duration", 10))
        threads = int(data.get("threads", default_threads))
    except (TypeError, ValueError):
        return None, "duration and threads must be integers"
    if not (1 <= duration <= MAX_DURATION):
        return None, f"duration must be between 1 and {MAX_DURATION}s"
    if not (1 <= threads <= MAX_THREADS):
        return None, f"threads must be between 1 and {MAX_THREADS}"
    return {"type": attack_type, "duration": duration, "threads": threads}, None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/start_ddos', methods=['POST'])
def start_ddos():
    data = request.get_json(silent=True) or {}
    params, err = _validate_run(data, VALID_DDOS_TYPES, "http", 5)
    if err:
        return jsonify({"status": "error", "message": err}), 400
    ok, msg = manager.start_ddos(params["type"], params["duration"], params["threads"])
    return jsonify({"status": "started" if ok else "busy", "message": msg}), (200 if ok else 409)


@app.route('/start_sql', methods=['POST'])
def start_sql():
    data = request.get_json(silent=True) or {}
    params, err = _validate_run(data, VALID_SQL_TYPES, "basic", 3)
    if err:
        return jsonify({"status": "error", "message": err}), 400
    ok, msg = manager.start_sql(params["type"], params["duration"], params["threads"])
    return jsonify({"status": "started" if ok else "busy", "message": msg}), (200 if ok else 409)


@app.route('/stop_ddos', methods=['POST'])
def stop_ddos():
    ok, msg = manager.stop("ddos")
    return jsonify({"status": "stopping" if ok else "idle", "message": msg})


@app.route('/stop_sql', methods=['POST'])
def stop_sql():
    ok, msg = manager.stop("sql")
    return jsonify({"status": "stopping" if ok else "idle", "message": msg})


@app.route('/stop_all', methods=['POST'])
def stop_all():
    stopped = manager.stop_all()
    return jsonify({"status": "stopping", "stopped": stopped})


@app.route('/reset', methods=['POST'])
def reset():
    manager.reset()
    return jsonify({"status": "reset"})


@app.route('/test_defense', methods=['POST'])
def test_defense():
    """Directly exercise a defense with a single input and report the real result."""
    data = request.get_json(silent=True) or {}
    test_type = data.get('type', 'rate_limit')

    if test_type == 'rate_limit':
        ip = str(data.get('ip', '192.168.1.200'))
        results = []
        for i in range(15):
            allowed = manager.rate_limiter.is_allowed(ip)
            results.append({'request': i + 1, 'allowed': allowed, 'ip': ip})
        blocked_at = next((r['request'] for r in results if not r['allowed']), None)
        manager.add_event({
            "message": (f"Rate-limit probe on {ip}: blocked after request {blocked_at}"
                        if blocked_at else f"Rate-limit probe on {ip}: all 15 allowed"),
            "level": "DEFENSE", "kind": "ddos"})
        return jsonify({'status': 'completed', 'ip': ip, 'results': results,
                        'blocked_at': blocked_at,
                        'stats': manager.rate_limiter.get_stats()})

    elif test_type == 'sql_injection':
        query = str(data.get('query', "admin' OR '1'='1"))
        ip = str(data.get('ip', '192.168.1.200'))
        is_safe, action = manager.sql_defense.check_query(query, ip)
        manager.add_event({
            "message": f"SQLi probe from {ip}: {action} -> {query[:40]}",
            "level": "DEFENSE", "kind": "sql", "outcome": action})
        return jsonify({'status': 'completed', 'query': query, 'safe': is_safe,
                        'action': action, 'stats': manager.sql_defense.get_stats()})

    return jsonify({'status': 'error', 'message': 'Invalid test type'}), 400


@app.route('/bank_status')
def bank_status():
    reachable, detail = manager.bank_client.health()
    return jsonify({"url": manager.bank_client.base_url, "reachable": reachable,
                    "detail": detail, "verify_enabled": manager.bank_verify})


@app.route('/config', methods=['GET', 'POST'])
def config():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        if 'bank_verify' in data:
            manager.bank_verify = bool(data['bank_verify'])
        if 'bank_url' in data:
            url = str(data['bank_url'])
            if not _host_allowed(url):
                return jsonify({"status": "error",
                                "message": "bank_url host not in allowlist"}), 400
            manager.bank_client = BankClient(base_url=url)
        manager.add_event({"message": "Configuration updated", "level": "INFO"})
    return jsonify({"bank_url": manager.bank_client.base_url,
                    "bank_verify": manager.bank_verify,
                    "allowlist": sorted(TARGET_ALLOWLIST),
                    "max_threads": MAX_THREADS, "max_duration": MAX_DURATION})


@app.route('/get_status')
def get_status():
    return jsonify(manager.status())


@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    manager.clear_logs()
    return jsonify({'status': 'cleared'})


if __name__ == '__main__':
    reachable, detail = manager.bank_client.health()
    manager.add_event({
        "message": (f"Bank target {manager.bank_client.base_url} reachable ({detail})"
                    if reachable else
                    f"Bank target {manager.bank_client.base_url} not reachable ({detail}); "
                    "DDoS runs will still verify against the rate limiter"),
        "level": "INFO" if reachable else "WARNING"})
    # debug=False avoids the reloader spawning duplicate background threads.
    app.run(debug=False, host='0.0.0.0', port=5001, threaded=True)
