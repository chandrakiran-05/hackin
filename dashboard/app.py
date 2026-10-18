"""
Security Simulation Dashboard.

A Flask control plane for the banking attack-simulation system. It drives the
attack simulators against the local defensive pipeline (rate limiter +
SQL-injection defense) and, when configured, verifies the *real* response from
the Quantum RiskFabric target (https://github.com/SachinDurairaj06/quantum-riskfabric)
running on loopback.

Every number shown on the dashboard comes from a real defense decision or a
real HTTP response - the dashboard never fabricates outcomes.

Reliability features:
* A single :class:`RunManager` owns all shared state behind one lock.
* Each attack runs with an isolated set of counters and a cancellation
  ``Event`` so runs can be stopped cleanly and never corrupt each other.
* Concurrency is capped (one run per attack kind) so repeated clicks cannot
  spawn unbounded background threads.
* Inputs are validated and the target is checked against an allowlist.
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
    import requests  # used for real target response verification
except Exception:  # pragma: no cover - requests should be installed
    requests = None

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration (with safe defaults; adjustable at runtime within limits)
# ---------------------------------------------------------------------------
# The target is the Quantum RiskFabric stack. Its default payment entry is the
# bank channel on :9000; the perimeter entry is :8000. All on loopback.
DEFAULT_TARGET_URL = os.getenv("RF_TARGET_URL", os.getenv("RF_BANK_URL", "http://127.0.0.1:9000"))
PAY_PATH = os.getenv("RF_PAY_PATH", "/bank/pay")        # channel decision (ALLOW/VERIFY/HOLD)
ENGINE_PATH = os.getenv("RF_ENGINE_PATH", "/engine/pay")  # raw engine decision + score
HEALTH_PATH = os.getenv("RF_HEALTH_PATH", "/bank/health")

MAX_THREADS = int(os.getenv("SIM_MAX_THREADS", "20"))
MAX_DURATION = int(os.getenv("SIM_MAX_DURATION", "120"))
MAX_LOGS = 300

VALID_DDOS_TYPES = {"http", "udp", "syn"}
VALID_SQL_TYPES = {"basic", "ddl", "union"}

# Hosts the simulator may send traffic to. Loopback lab targets only; adding a
# target requires editing this set (enforced for config changes).
TARGET_ALLOWLIST = {"127.0.0.1", "localhost", "::1"}

# Simulated source identities, each pinned to a geographic origin so the attack
# map can draw stable arcs from each origin toward the server. These are lab
# source IPs (RFC 1918) used only against the authorized loopback target.
SOURCE_PROFILES = [
    {"ip": "10.0.0.11", "label": "New York",   "lat": 40.71,  "lng": -74.01},
    {"ip": "10.0.0.12", "label": "London",     "lat": 51.51,  "lng": -0.13},
    {"ip": "10.0.0.13", "label": "Moscow",     "lat": 55.76,  "lng": 37.62},
    {"ip": "10.0.0.14", "label": "Singapore",  "lat": 1.35,   "lng": 103.82},
    {"ip": "10.0.0.15", "label": "Sao Paulo",  "lat": -23.55, "lng": -46.63},
    {"ip": "10.0.0.16", "label": "Lagos",      "lat": 6.52,   "lng": 3.38},
    {"ip": "10.0.0.17", "label": "Sydney",     "lat": -33.87, "lng": 151.21},
    {"ip": "10.0.0.18", "label": "Mumbai",     "lat": 19.08,  "lng": 72.88},
]
SOURCE_IPS = [p["ip"] for p in SOURCE_PROFILES]
# Where the bank/server is drawn on the map (purely for visualization).
SERVER_LOCATION = {"label": "Bank Datacenter", "lat": 50.11, "lng": 8.68}


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def _host_allowed(url):
    try:
        host = urlparse(url).hostname
    except Exception:
        return False
    return host in TARGET_ALLOWLIST


# ---------------------------------------------------------------------------
# Target client - records the real response from the RiskFabric target
# ---------------------------------------------------------------------------
class TargetClient:
    """Speaks the RiskFabric payment contract. Records real responses only."""

    def __init__(self, base_url=DEFAULT_TARGET_URL, timeout=3.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._counter = 0
        self._lock = threading.Lock()

    def _next_txn(self):
        with self._lock:
            self._counter += 1
            return f"sim-{int(time.time())}-{self._counter}"

    def build_payment(self, from_acct, to_acct, amount, currency="USD",
                      fmt="ACH", txn_id=None):
        """Build a payment in the RiskFabric contract shape (bank/app.py)."""
        return {
            "txn_id": txn_id or self._next_txn(),
            "ts": time.time(),
            "from_acct": str(from_acct),
            "to_acct": str(to_acct),
            "amount": float(amount),
            "currency": str(currency),
            "format": str(fmt),
        }

    def health(self):
        """Return (reachable: bool, detail: str)."""
        if requests is None:
            return False, "requests library unavailable"
        if not _host_allowed(self.base_url):
            return False, "target not in allowlist"
        try:
            r = requests.get(f"{self.base_url}{HEALTH_PATH}", timeout=self.timeout)
            if r.status_code == 200:
                body = r.json()
                return bool(body.get("ok", True)), (
                    f"fail_mode={body.get('fail_mode')}, accounts={body.get('accounts')}"
                    if isinstance(body, dict) else "ok")
            return False, f"HTTP {r.status_code}"
        except Exception as exc:
            return False, str(exc)

    def probe(self, source_ip):
        """
        Send one benign payment through the channel and return (status, detail)
        where ``status`` is the real decision (ALLOW/VERIFY/HOLD) or an error
        marker (UNREACHABLE/ERROR). Never raises on network failure.
        """
        if requests is None:
            return "ERROR", "requests unavailable"
        if not _host_allowed(self.base_url):
            return "ERROR", "target not in allowlist"
        payload = self.build_payment("SIM-ACC", "DEST-ACC", 100.0)
        try:
            r = requests.post(f"{self.base_url}{PAY_PATH}", json=payload,
                              timeout=self.timeout,
                              headers={"X-Forwarded-For": source_ip,
                                       "X-Request-Id": payload["txn_id"]})
            if r.status_code == 200:
                body = r.json()
                status = body.get("action") or body.get("decision") or "UNKNOWN"
                score = body.get("score")
                return status, (f"score={score}" if score is not None else None)
            return "ERROR", f"HTTP {r.status_code}"
        except Exception as exc:
            return "UNREACHABLE", str(exc)

    def score(self, txn):
        """
        Submit one transaction to the raw engine and return the real decision:
        {ok, decision, score, reasons, latency_ms, error}. Used by the fraud
        scenario to observe exactly how the ML/engine responds.
        """
        result = {"ok": False, "decision": None, "score": None, "reasons": [],
                  "latency_ms": None, "error": None, "txn": txn}
        if requests is None:
            result["error"] = "requests unavailable"
            return result
        if not _host_allowed(self.base_url):
            result["error"] = "target not in allowlist"
            return result
        try:
            r = requests.post(f"{self.base_url}{ENGINE_PATH}", json=txn,
                              timeout=self.timeout,
                              headers={"X-Request-Id": txn.get("txn_id", "")})
            if r.status_code == 200:
                body = r.json()
                result.update(
                    ok=True,
                    decision=body.get("decision") or body.get("action"),
                    score=body.get("score"),
                    reasons=body.get("reasons", []),
                    latency_ms=body.get("engine_latency_ms") or body.get("latency_ms"),
                )
            else:
                result["error"] = f"HTTP {r.status_code}: {r.text[:120]}"
        except Exception as exc:
            result["error"] = str(exc)
        return result


# ---------------------------------------------------------------------------
# Run manager - owns shared state and background runs
# ---------------------------------------------------------------------------
class RunManager:
    def __init__(self):
        self._lock = threading.RLock()
        self.rate_limiter = RateLimiter(max_requests=10, time_window=60)
        self.sql_defense = SQLInjectionDefense()
        self.target = TargetClient()
        self.verify_target = True

        self._logs = deque(maxlen=MAX_LOGS)
        self._runs = {"ddos": None, "sql": None}
        self._last_scenario = None
        self.add_event({"timestamp": _utcnow_iso(),
                        "message": "Dashboard initialised", "level": "INFO"})

    # -- logging ----------------------------------------------------------
    def add_event(self, event):
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

    def _start(self, kind, params, target_fn, stats_ref=None):
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
                stats = target_fn(cancel, self._on_sim_event)
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
        self.add_event(event)

    def start_ddos(self, attack_type, duration, threads):
        sim = DDoSSimulator(defense=self.rate_limiter,
                            bank_client=self.target if self.verify_target else None,
                            source_ips=SOURCE_IPS)
        stats = DDoSStats(attack_type=attack_type, started_at=_utcnow_iso())

        def target_fn(cancel, on_event):
            return sim.start_attack(attack_type, duration, threads,
                                    cancel_event=cancel, on_event=on_event,
                                    stats=stats)

        return self._start("ddos", {"type": attack_type, "duration": duration,
                                    "threads": threads}, target_fn, stats_ref=stats)

    def start_sql(self, attack_type, duration, threads):
        sim = SQLInjectionSimulator(defense=self.sql_defense, source_ips=SOURCE_IPS)
        stats = SQLStats(attack_type=attack_type, started_at=_utcnow_iso())

        def target_fn(cancel, on_event):
            return sim.start_attack(attack_type, duration, threads,
                                    cancel_event=cancel, on_event=on_event,
                                    stats=stats)

        return self._start("sql", {"type": attack_type, "duration": duration,
                                   "threads": threads}, target_fn, stats_ref=stats)

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
            self._last_scenario = None
            self._logs.clear()
        self.add_event({"message": "System reset: defenses, runs, scenario and logs cleared",
                        "level": "INFO"})

    # -- fraud scenario ---------------------------------------------------
    def run_scenario(self, account, to_acct, baseline_amount, fraud_amount,
                     currency, fmt, source_label):
        """
        Account-takeover / stolen-session test. Submits a baseline legitimate
        transfer and then an anomalous high-value transfer from the SAME account
        to a new destination, and reports exactly how the engine/ML responded to
        each. This validates fraud detection; it performs no credential theft.
        """
        baseline_txn = self.target.build_payment(account, account + "-PAYEE",
                                                  baseline_amount, currency, fmt)
        fraud_txn = self.target.build_payment(account, to_acct, fraud_amount,
                                              currency, fmt)
        self.add_event({
            "message": (f"Fraud scenario: account {account} - baseline "
                        f"{baseline_amount} {currency} vs stolen-session "
                        f"{fraud_amount} {currency} to {to_acct} "
                        f"(source {source_label})"),
            "level": "ATTACK", "kind": "scenario"})

        baseline_res = self.target.score(baseline_txn)
        fraud_res = self.target.score(fraud_txn)

        for label, res in (("baseline", baseline_res), ("fraud", fraud_res)):
            if res["ok"]:
                self.add_event({
                    "message": (f"Engine response ({label}): {res['decision']} "
                                f"score={res['score']} reasons={res['reasons']}"),
                    "level": ("DEFENSE" if res["decision"] in ("HOLD", "VERIFY")
                              and label == "fraud" else "INFO"),
                    "kind": "scenario", "outcome": res["decision"]})
            else:
                self.add_event({
                    "message": f"Engine unreachable ({label}): {res['error']}",
                    "level": "WARNING", "kind": "scenario"})

        caught = bool(fraud_res["ok"] and fraud_res["decision"] in ("HOLD", "VERIFY"))
        result = {
            "ts": _utcnow_iso(),
            "account": account, "to_acct": to_acct, "currency": currency,
            "source_label": source_label,
            "baseline": {"amount": baseline_amount, **baseline_res},
            "fraud": {"amount": fraud_amount, **fraud_res},
            "caught": caught,
            "target_url": self.target.base_url,
        }
        with self._lock:
            self._last_scenario = result
        return result

    # -- status -----------------------------------------------------------
    def _run_view(self, kind):
        with self._lock:
            handle = self._runs.get(kind)
            if not handle:
                return {"running": False, "stats": None, "params": None,
                        "started_at": None}
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
        blocked_ips = self.rate_limiter.blocked_ip_set()

        ddos_s = ddos["stats"] or {}
        sql_s = sql["stats"] or {}
        active = ddos["running"] or sql["running"]
        with self._lock:
            scenario = self._last_scenario
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
            "target": {"configured_url": self.target.base_url,
                       "verify_enabled": self.verify_target,
                       "responses": ddos_s.get("bank_responses", {})},
            "map": {
                "server": SERVER_LOCATION,
                "active": active,
                "sources": [dict(p, blocked=(p["ip"] in blocked_ips))
                            for p in SOURCE_PROFILES],
            },
            "scenario": scenario,
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


@app.route('/run_scenario', methods=['POST'])
def run_scenario():
    """Run the stolen-session / account-takeover fraud-detection test."""
    data = request.get_json(silent=True) or {}
    account = str(data.get("account", "SIM-ACC-001")).strip() or "SIM-ACC-001"
    to_acct = str(data.get("to_acct", "MULE-ACC-999")).strip() or "MULE-ACC-999"
    currency = str(data.get("currency", "USD")).strip() or "USD"
    fmt = str(data.get("format", "ACH")).strip() or "ACH"
    source_label = str(data.get("source", "Unknown origin")).strip() or "Unknown origin"
    try:
        baseline_amount = float(data.get("baseline_amount", 120.0))
        fraud_amount = float(data.get("fraud_amount", 48500.0))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "amounts must be numbers"}), 400
    if baseline_amount <= 0 or fraud_amount <= 0:
        return jsonify({"status": "error", "message": "amounts must be positive"}), 400

    result = manager.run_scenario(account, to_acct, baseline_amount, fraud_amount,
                                  currency, fmt, source_label)
    return jsonify({"status": "completed", "result": result})


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


@app.route('/target_status')
def target_status():
    reachable, detail = manager.target.health()
    return jsonify({"url": manager.target.base_url, "reachable": reachable,
                    "detail": detail, "verify_enabled": manager.verify_target})


@app.route('/config', methods=['GET', 'POST'])
def config():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        if 'verify_target' in data:
            manager.verify_target = bool(data['verify_target'])
        url = data.get('target_url') or data.get('bank_url')
        if url:
            url = str(url)
            if not _host_allowed(url):
                return jsonify({"status": "error",
                                "message": "target_url host not in allowlist"}), 400
            manager.target = TargetClient(base_url=url)
        manager.add_event({"message": "Configuration updated", "level": "INFO"})
    return jsonify({"target_url": manager.target.base_url,
                    "verify_target": manager.verify_target,
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
    reachable, detail = manager.target.health()
    manager.add_event({
        "message": (f"RiskFabric target {manager.target.base_url} reachable ({detail})"
                    if reachable else
                    f"RiskFabric target {manager.target.base_url} not reachable ({detail}); "
                    "attacks still run against the local rate limiter / SQLi defense"),
        "level": "INFO" if reachable else "WARNING"})
    app.run(debug=False, host='0.0.0.0', port=5001, threaded=True)
