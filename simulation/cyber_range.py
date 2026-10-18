"""
Quantum RiskFabric Cyber Range - evidence-driven attack vs defense engine.

This module runs authorized, bounded attack scenarios against a *simulated*
defense chain (edge/CDN/WAF -> application auth/authz/validation -> RiskFabric
risk policy) and records a single correlated event stream. Every metric is
derived from recorded events and an explicit per-attempt ground-truth label -
nothing is a random "success percentage".

Key properties
--------------
* Each run has a unique ``run_id`` and a fixed ``seed`` so runs are repeatable
  and three defense modes can be compared on identical inputs.
* Each generated attempt carries a correlation id and flows through the layers;
  it has exactly one FINAL outcome, so a request blocked at the edge is never
  also counted as an application block (no double counting).
* The RiskFabric risk step uses an injected ``risk_scorer``. The dashboard
  injects one that calls the *real* RiskFabric engine when it is reachable, and
  falls back to a clearly-labelled local classical model otherwise. A quantum
  result is only ever labelled quantum when it genuinely came from the engine.
* Ground truth (`is_malicious`, `objective`) is attached to every attempt so
  detection can be scored (TP/FP/FN/TN, precision, recall).

The three modes:
  * ``baseline``  - edge + app controls only, no RiskFabric risk scoring.
  * ``classical`` - edge + app + RiskFabric classical risk scoring.
  * ``quantum``   - edge + app + RiskFabric with the quantum scorer when the
                    engine reports it ran; otherwise it degrades to classical
                    and says so (never faked).
"""

from __future__ import annotations

import math
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Seeded synthetic identities (fictional - never real people or secrets)
# ---------------------------------------------------------------------------
@dataclass
class Identity:
    customer_id: str
    account_id: str            # matches the RiskFabric registry "acct" convention
    device_id: str             # the customer's usual device
    login_hours: tuple         # (start_hour, end_hour) typical local login window
    amount_band: tuple         # (min, max) typical transaction amount
    source_network: str        # usual source label
    permitted_actions: tuple   # authorized operations
    # Fictional seeded test secret. Used only to decide AUTH_OK vs AUTH_FAIL in
    # the simulation; never a real credential and never logged in the clear.
    secret_token: str


# A small seeded roster. account_id uses the <Bank>-<Account> style so it can be
# pointed at a real registry on the VM; override via the dataset/config if needed.
IDENTITIES = [
    Identity("CUST-1001", "CUST-1001", "dev-aa11", (8, 18), (20, 2000),
             "198.51.100.0/24", ("view_balance", "transfer", "pay_bill"), "seed-tok-1001"),
    Identity("CUST-1002", "CUST-1002", "dev-bb22", (9, 17), (50, 5000),
             "203.0.113.0/24", ("view_balance", "transfer"), "seed-tok-1002"),
    Identity("CUST-1003", "CUST-1003", "dev-cc33", (6, 22), (10, 800),
             "192.0.2.0/24", ("view_balance", "pay_bill"), "seed-tok-1003"),
]
IDENTITY_BY_ID = {i.customer_id: i for i in IDENTITIES}


def public_identities():
    """Identity roster for the UI, with the secret redacted."""
    out = []
    for i in IDENTITIES:
        out.append({"customer_id": i.customer_id, "account_id": i.account_id,
                    "device_id": i.device_id, "login_hours": list(i.login_hours),
                    "amount_band": list(i.amount_band), "source_network": i.source_network,
                    "permitted_actions": list(i.permitted_actions),
                    "secret": "***redacted***"})
    return out


# ---------------------------------------------------------------------------
# RiskFabric policy + local classical scorer (used when the real engine is away)
# ---------------------------------------------------------------------------
POLICY = {"verify_at": 0.40, "review_at": 0.60, "hold_at": 0.80, "version": "policy-local-v1"}


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def local_classical_score(features: dict) -> dict:
    """
    Deterministic local classical risk model (logistic over engineered features).
    Clearly labelled so it is never confused with the RiskFabric engine or a
    quantum backend. Same inputs always give the same score.
    """
    w = {
        "new_device": 1.6, "unusual_hour": 0.9, "source_change": 1.3,
        "failed_auth_recent": 0.5, "amount_dev": 1.1, "velocity": 0.7,
        "authz_violation": 2.2,
    }
    bias = -2.2
    z = bias + sum(w[k] * float(features.get(k, 0.0)) for k in w)
    score = round(_sigmoid(z), 4)
    reasons = [k for k in w if float(features.get(k, 0.0)) > 0]
    return {"score": score, "reasons": reasons, "model": "local-classical-logit",
            "model_version": "lcl-v1", "backend": "local-classical",
            "quantum": None, "latency_ms": 0.3}


def decision_from_score(score: float) -> str:
    if score >= POLICY["hold_at"]:
        return "TEMPORARY_HOLD"
    if score >= POLICY["review_at"]:
        return "REVIEW"
    if score >= POLICY["verify_at"]:
        return "STEP_UP_VERIFICATION"
    return "ALLOW"


# ---------------------------------------------------------------------------
# Event + attempt model
# ---------------------------------------------------------------------------
@dataclass
class Event:
    event_id: str
    run_id: str
    scenario_id: str
    correlation_id: str      # the attempt this event belongs to
    seq: int
    ts: str
    component: str           # controller | edge | app | riskfabric
    action: str
    reason: str
    severity: str            # info | low | medium | high
    latency_ms: float
    details: dict = field(default_factory=dict)

    def as_dict(self):
        return {k: getattr(self, k) for k in
                ("event_id", "run_id", "scenario_id", "correlation_id", "seq",
                 "ts", "component", "action", "reason", "severity", "latency_ms", "details")}


# Final outcome buckets - each attempt ends in exactly one of these.
OUTCOMES = [
    "edge_blocked", "edge_challenged", "edge_rate_limited",
    "app_auth_failed", "app_authz_denied", "app_validation_failed", "app_rate_limited",
    "risk_hold", "risk_review", "risk_step_up", "allowed", "unauthorized_success",
]
STOPPED_OUTCOMES = set(OUTCOMES) - {"allowed", "unauthorized_success"}


@dataclass
class Attempt:
    correlation_id: str
    kind: str                 # login | transaction | request
    identity_id: Optional[str]
    is_malicious: bool
    objective: bool           # True if completing this attempt == the scenario objective
    presented_secret: str     # what the attacker presents (may be wrong / stolen)
    action: str               # requested application action
    amount: float
    new_device: bool
    unusual_hour: bool
    source_change: bool
    payload: str              # inspected by the edge WAF / app validation
    malformed: bool
    source_ip: str


# ---------------------------------------------------------------------------
# Simulated defense layers (real rule logic; clearly a modelled component)
# ---------------------------------------------------------------------------
from simulation.defenses.rate_limiter import RateLimiter
from simulation.defenses.sql_injection_defense import SQLInjectionDefense

_MAL_PAYLOAD = SQLInjectionDefense()   # reused as the WAF signature engine


class EdgeDefense:
    """Simulated CDN/WAF/edge: per-source rate limit, WAF signatures, bot
    challenge on bursty reputation. Not a claim about any real CDN."""

    def __init__(self, rate_max=12, window=60):
        self.rl = RateLimiter(max_requests=rate_max, time_window=window)
        self.seen = {}            # source_ip -> count (reputation)

    def evaluate(self, a: Attempt):
        t0 = time.perf_counter()
        self.seen[a.source_ip] = self.seen.get(a.source_ip, 0) + 1
        # 1) WAF signature match (malicious payloads)
        if a.payload and _MAL_PAYLOAD.detect_sql_injection(a.payload):
            return self._r("edge_blocked", "waf_signature_match", "high", t0,
                           {"rule": "WAF-SQLi", "payload": a.payload[:48]})
        # 2) rate limit per source
        if not self.rl.is_allowed(a.source_ip):
            return self._r("edge_rate_limited", "per_source_rate_limit", "medium", t0,
                           {"source": a.source_ip})
        # 3) reputation / bot challenge on sustained burst from one source
        if self.seen[a.source_ip] > 8 and a.is_malicious:
            return self._r("edge_challenged", "bot_challenge_reputation", "medium", t0,
                           {"source": a.source_ip, "seen": self.seen[a.source_ip]})
        return self._r("forward", "classified_clean", "info", t0, {})

    def _r(self, outcome, reason, sev, t0, details):
        return {"outcome": outcome, "reason": reason, "severity": sev,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 3),
                "details": details, "passed": outcome == "forward"}


class AppDefense:
    """Simulated application security: authentication, authorization, schema/
    input validation and an application rate limit."""

    def __init__(self, rate_max=20, window=60):
        self.rl = RateLimiter(max_requests=rate_max, time_window=window)
        self.failed_auth = {}     # identity_id -> recent failed count

    def evaluate(self, a: Attempt):
        t0 = time.perf_counter()
        ident = IDENTITY_BY_ID.get(a.identity_id)
        # application rate limit (keyed by identity, else source)
        key = a.identity_id or a.source_ip
        if not self.rl.is_allowed(key):
            return self._r("app_rate_limited", "app_rate_limit", "low", t0, {"key": key})
        # schema / input validation
        if a.malformed:
            return self._r("app_validation_failed", "schema_validation_failed", "low", t0, {})
        # authentication (login / any action needing a session)
        if a.kind in ("login", "transaction"):
            if ident is None or a.presented_secret != ident.secret_token:
                self.failed_auth[a.identity_id] = self.failed_auth.get(a.identity_id, 0) + 1
                return self._r("app_auth_failed", "authentication_rejected", "medium", t0,
                               {"identity": a.identity_id, "failed_recent": self.failed_auth.get(a.identity_id)})
        # authorization
        if ident is not None and a.action not in ident.permitted_actions:
            return self._r("app_authz_denied", "authorization_denied", "high", t0,
                           {"identity": a.identity_id, "action": a.action})
        # passed all application controls -> reaches a protected function
        return self._r("protected_reached", "authenticated_authorized", "info", t0,
                       {"identity": a.identity_id, "action": a.action,
                        "failed_recent": self.failed_auth.get(a.identity_id, 0)})

    def _r(self, outcome, reason, sev, t0, details):
        return {"outcome": outcome, "reason": reason, "severity": sev,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 3),
                "details": details, "passed": outcome == "protected_reached"}


def build_features(a: Attempt, failed_recent: int) -> dict:
    ident = IDENTITY_BY_ID.get(a.identity_id)
    amount_dev = 0.0
    if ident is not None:
        lo, hi = ident.amount_band
        if a.amount > hi:
            amount_dev = min(1.0, (a.amount - hi) / max(hi, 1.0))
    return {
        "new_device": 1.0 if a.new_device else 0.0,
        "unusual_hour": 1.0 if a.unusual_hour else 0.0,
        "source_change": 1.0 if a.source_change else 0.0,
        "failed_auth_recent": min(1.0, failed_recent / 5.0),
        "amount_dev": amount_dev,
        "velocity": 0.0,   # set by the engine from recent attempt rate
        "authz_violation": 0.0,
        # Raw transaction context so an injected real-engine scorer can build a
        # payment. The local scorer ignores these and uses the weights above.
        "_from_acct": a.identity_id or "SIM-ACC", "_to_acct": "MULE-ACC-RANGE",
        "_amount": float(a.amount or 100.0), "_currency": "USD",
    }


def default_local_scorer(features: dict, mode: str) -> dict:
    """Offline risk scorer. For quantum mode with no real engine it stays
    classical and says the quantum backend is unavailable - never faked."""
    res = local_classical_score(features)
    res["decision"] = decision_from_score(res["score"])
    res["timeout"] = False
    res["fallback"] = (mode == "quantum")   # quantum asked but unavailable locally
    if mode == "quantum":
        res["backend"] = "local-classical (quantum backend unavailable)"
    return res



# ---------------------------------------------------------------------------
# Scenario catalogue - each has an objective, ground truth and a generator
# ---------------------------------------------------------------------------
ATTACKER_IP = "45.83.100.7"      # a fixed "attacker" source for the demo


def _mk(cid, kind, identity_id, is_malicious, objective=False, secret="", action="view_balance",
        amount=0.0, new_device=False, unusual_hour=False, source_change=False,
        payload="", malformed=False, source_ip=None):
    return Attempt(cid, kind, identity_id, is_malicious, objective, secret, action, amount,
                   new_device, unusual_hour, source_change, payload, malformed,
                   source_ip or ATTACKER_IP)


def _gen_credential_impersonation(rng, n):
    victim = IDENTITIES[0]
    out = []
    # legitimate customer activity (benign, correct secret, known context)
    for _ in range(max(2, n // 4)):
        out.append(_mk(uuid.uuid4().hex[:12], "transaction", victim.customer_id, False,
                       secret=victim.secret_token, action="transfer",
                       amount=rng.uniform(*victim.amount_band),
                       source_ip="198.51.100.20"))
    # wrong-credential impostors (auth should catch)
    for _ in range(max(2, n // 3)):
        out.append(_mk(uuid.uuid4().hex[:12], "login", victim.customer_id, True, objective=True,
                       secret="guess-" + rng.choice(["123", "pw", "letmein"]),
                       action="transfer", amount=rng.uniform(5000, 60000),
                       new_device=True, unusual_hour=True, source_change=True))
    # stolen-credential impostors (valid secret, anomalous context - risk must catch)
    for _ in range(max(2, n // 3)):
        out.append(_mk(uuid.uuid4().hex[:12], "transaction", victim.customer_id, True, objective=True,
                       secret=victim.secret_token, action="transfer",
                       amount=rng.uniform(25000, 90000), new_device=True,
                       unusual_hour=True, source_change=True))
    rng.shuffle(out)
    return out


def _gen_password_spraying(rng, n):
    out = []
    for _ in range(n):
        ident = rng.choice(IDENTITIES)
        out.append(_mk(uuid.uuid4().hex[:12], "login", ident.customer_id, True, objective=True,
                       secret="Spring2026!", action="view_balance", new_device=True,
                       source_change=True, source_ip=ATTACKER_IP))
    for _ in range(max(2, n // 6)):   # a little legit traffic
        ident = rng.choice(IDENTITIES)
        out.append(_mk(uuid.uuid4().hex[:12], "login", ident.customer_id, False,
                       secret=ident.secret_token, action="view_balance", source_ip="198.51.100.30"))
    rng.shuffle(out)
    return out


def _gen_repeated_failed_auth(rng, n):
    victim = IDENTITIES[1]
    out = [_mk(uuid.uuid4().hex[:12], "login", victim.customer_id, True, objective=True,
               secret="try-" + str(i), action="view_balance", new_device=True, source_change=True)
           for i in range(n)]
    return out


def _gen_sql_injection(rng, n):
    payloads = ["admin' OR '1'='1", "' UNION SELECT card_number, cvv FROM cards --",
                "1; DROP TABLE accounts; --"]
    out = [_mk(uuid.uuid4().hex[:12], "request", None, True, objective=True,
               action="view_balance", payload=rng.choice(payloads)) for _ in range(n)]
    for _ in range(max(2, n // 5)):
        out.append(_mk(uuid.uuid4().hex[:12], "request", None, False, action="view_balance",
                       payload="account summary", source_ip="198.51.100.40"))
    rng.shuffle(out)
    return out


def _gen_ddos_burst(rng, n):
    out = [_mk(uuid.uuid4().hex[:12], "request", None, True, action="view_balance",
               source_ip=rng.choice([ATTACKER_IP, "45.83.100.8", "45.83.100.9"]))
           for _ in range(n)]
    return out


def _gen_broken_authorization(rng, n):
    # CUST-1003 is only permitted view_balance/pay_bill -> "transfer" is unauthorized
    ident = IDENTITY_BY_ID["CUST-1003"]
    out = [_mk(uuid.uuid4().hex[:12], "transaction", ident.customer_id, True, objective=True,
               secret=ident.secret_token, action="transfer", amount=rng.uniform(100, 3000),
               source_ip="192.0.2.50") for _ in range(n)]
    for _ in range(max(2, n // 4)):
        out.append(_mk(uuid.uuid4().hex[:12], "transaction", ident.customer_id, False,
                       secret=ident.secret_token, action="pay_bill", amount=rng.uniform(10, 500),
                       source_ip="192.0.2.50"))
    rng.shuffle(out)
    return out


def _gen_malformed_input(rng, n):
    out = [_mk(uuid.uuid4().hex[:12], "request", None, True, action="view_balance",
               payload="{bad json" * 3, malformed=True) for _ in range(n)]
    return out


def _gen_suspicious_transaction(rng, n):
    victim = IDENTITIES[0]
    out = []
    for _ in range(max(2, n // 2)):   # legit in-band transfers (benign)
        out.append(_mk(uuid.uuid4().hex[:12], "transaction", victim.customer_id, False,
                       secret=victim.secret_token, action="transfer",
                       amount=rng.uniform(*victim.amount_band), source_ip="198.51.100.20"))
    for _ in range(max(2, n // 2)):   # anomalous high-value / velocity (fraud ground truth)
        out.append(_mk(uuid.uuid4().hex[:12], "transaction", victim.customer_id, True, objective=True,
                       secret=victim.secret_token, action="transfer",
                       amount=rng.uniform(30000, 120000), new_device=True, unusual_hour=True,
                       source_ip="198.51.100.20"))
    rng.shuffle(out)
    return out


SCENARIOS = {
    "credential_impersonation": {
        "name": "Credential impersonation (stolen session)", "category": "identity",
        "objective": "Complete an unauthorized high-value transfer as a victim customer.",
        "ground_truth": "Wrong-secret and stolen-secret impostor attempts are malicious; the victim's own in-band transfers are benign.",
        "generator": _gen_credential_impersonation, "base": 12, "objective_threshold": 1},
    "password_spraying": {
        "name": "Password spraying", "category": "identity",
        "objective": "Obtain any valid session with a common password across accounts.",
        "ground_truth": "Spray logins are malicious; seeded correct-secret logins are benign.",
        "generator": _gen_password_spraying, "base": 24, "objective_threshold": 1},
    "repeated_failed_auth": {
        "name": "Repeated failed authentication", "category": "identity",
        "objective": "Brute-force a victim login.",
        "ground_truth": "All guess attempts are malicious.",
        "generator": _gen_repeated_failed_auth, "base": 20, "objective_threshold": 1},
    "sql_injection": {
        "name": "SQL injection", "category": "application",
        "objective": "Reach the application/data layer with an injection payload.",
        "ground_truth": "Injection payloads are malicious; plain queries are benign.",
        "generator": _gen_sql_injection, "base": 16, "objective_threshold": 1},
    "ddos_burst": {
        "name": "Application request flood", "category": "availability",
        "objective": "Saturate the application past the edge.",
        "ground_truth": "Flood requests are malicious.",
        "generator": _gen_ddos_burst, "base": 60, "objective_threshold": 10},
    "broken_authorization": {
        "name": "Broken authorization", "category": "application",
        "objective": "Perform an operation the account is not permitted to do.",
        "ground_truth": "Unpermitted actions are malicious; permitted actions are benign.",
        "generator": _gen_broken_authorization, "base": 14, "objective_threshold": 1},
    "malformed_input": {
        "name": "Malformed input / schema validation", "category": "application",
        "objective": "Bypass schema validation with malformed payloads.",
        "ground_truth": "All malformed payloads are malicious.",
        "generator": _gen_malformed_input, "base": 14, "objective_threshold": 1},
    "suspicious_transaction": {
        "name": "Suspicious transaction (fraud)", "category": "risk",
        "objective": "Push through an anomalous high-value transfer.",
        "ground_truth": "Anomalous high-value transfers are malicious; in-band transfers are benign.",
        "generator": _gen_suspicious_transaction, "base": 16, "objective_threshold": 1},
}


def scenario_catalogue():
    return [{"id": sid, "name": s["name"], "category": s["category"],
             "objective": s["objective"], "ground_truth": s["ground_truth"]}
            for sid, s in SCENARIOS.items()]


# ---------------------------------------------------------------------------
# Run engine
# ---------------------------------------------------------------------------
def _pct(values, p):
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(math.ceil(p * len(s))) - 1)], 3)


class RangeRun:
    def __init__(self, run_id, scenario_id, mode, seed, intensity):
        self.run_id = run_id
        self.scenario_id = scenario_id
        self.scenario = SCENARIOS[scenario_id]
        self.mode = mode
        self.seed = seed
        self.intensity = intensity
        self.status = "READY"
        self.started_at = None
        self.finished_at = None
        self.events = []
        self.attempts = []        # per-attempt meta dicts
        self.total_planned = 0
        self._seq = 0
        self.cancel = threading.Event()
        self.lock = threading.Lock()

    def emit(self, correlation_id, component, action, reason, severity, latency_ms, details):
        with self.lock:
            self._seq += 1
            ev = Event(uuid.uuid4().hex[:12], self.run_id, self.scenario_id, correlation_id,
                       self._seq, _utcnow_iso(), component, action, reason, severity,
                       latency_ms, details)
            self.events.append(ev)


def _process_attempt(run, a, edge, app, scorer, state):
    t_start = time.perf_counter()
    run.emit(a.correlation_id, "controller", "generated",
             f"{run.scenario_id} attempt ({'malicious' if a.is_malicious else 'benign'})",
             "info", 0.0, {"kind": a.kind, "identity": a.identity_id, "action": a.action,
                           "amount": round(a.amount, 2), "is_malicious": a.is_malicious})

    # --- edge ---
    e = edge.evaluate(a)
    run.emit(a.correlation_id, "edge", e["outcome"], e["reason"], e["severity"],
             e["latency_ms"], e["details"])
    if not e["passed"]:
        return _meta(a, e["outcome"], (time.perf_counter() - t_start) * 1000, None)

    # --- application ---
    ap = app.evaluate(a)
    run.emit(a.correlation_id, "app", ap["outcome"], ap["reason"], ap["severity"],
             ap["latency_ms"], ap["details"])
    if not ap["passed"]:
        return _meta(a, ap["outcome"], (time.perf_counter() - t_start) * 1000, None)

    # --- baseline: no risk scoring, app decision is final ---
    if run.mode == "baseline":
        outcome = "unauthorized_success" if a.is_malicious else "allowed"
        run.emit(a.correlation_id, "riskfabric", "skipped", "baseline_no_riskfabric", "info", 0.0,
                 {"mode": "baseline"})
        return _meta(a, outcome, (time.perf_counter() - t_start) * 1000, None)

    # --- RiskFabric risk scoring ---
    failed_recent = ap["details"].get("failed_recent", 0)
    feats = build_features(a, failed_recent)
    state["ident_count"][a.identity_id] = state["ident_count"].get(a.identity_id, 0) + 1
    feats["velocity"] = min(1.0, state["ident_count"][a.identity_id] / 10.0)
    if a.action not in (IDENTITY_BY_ID.get(a.identity_id).permitted_actions
                        if IDENTITY_BY_ID.get(a.identity_id) else ()):
        feats["authz_violation"] = 1.0
    try:
        r = scorer(feats, run.mode) or {}
    except Exception as exc:   # scorer/engine failure -> conservative review
        r = {"score": None, "decision": "REVIEW", "model": "n/a",
             "backend": "unavailable", "reasons": [f"scorer_error:{exc}"],
             "latency_ms": 0.0, "timeout": True, "fallback": True, "quantum": None}
    score = r.get("score")
    decision = r.get("decision") or (decision_from_score(score) if score is not None else "REVIEW")
    run.emit(a.correlation_id, "riskfabric", decision,
             "; ".join(r.get("reasons", [])) or "risk_policy",
             "high" if decision in ("TEMPORARY_HOLD", "REVIEW") else
             ("medium" if decision == "STEP_UP_VERIFICATION" else "info"),
             round(r.get("latency_ms", 0.0), 3),
             {"score": score, "model": r.get("model"), "model_version": r.get("model_version"),
              "backend": r.get("backend"), "quantum": r.get("quantum"),
              "timeout": r.get("timeout", False), "fallback": r.get("fallback", False),
              "policy": POLICY["version"]})

    if decision == "ALLOW":
        outcome = "unauthorized_success" if a.is_malicious else "allowed"
    elif decision == "STEP_UP_VERIFICATION":
        outcome = "risk_step_up"      # impostor cannot satisfy step-up -> contained
    elif decision == "REVIEW":
        outcome = "risk_review"
    else:
        outcome = "risk_hold"
    return _meta(a, outcome, (time.perf_counter() - t_start) * 1000, r)


def _meta(a, outcome, total_latency_ms, risk):
    return {"correlation_id": a.correlation_id, "identity_id": a.identity_id,
            "kind": a.kind, "action": a.action, "amount": round(a.amount, 2),
            "is_malicious": a.is_malicious, "objective": a.objective, "outcome": outcome,
            "stopped": outcome in STOPPED_OUTCOMES, "source_ip": a.source_ip,
            "total_latency_ms": round(total_latency_ms, 3),
            "risk": ({"decision": risk.get("decision"), "score": risk.get("score"),
                      "backend": risk.get("backend"), "model": risk.get("model"),
                      "quantum": risk.get("quantum"), "latency_ms": risk.get("latency_ms"),
                      "timeout": risk.get("timeout", False),
                      "fallback": risk.get("fallback", False)} if risk else None)}


def compute_metrics(run):
    atts = list(run.attempts)
    oc = {k: 0 for k in OUTCOMES}
    tp = fp = fn = tn = 0
    risk_lat, total_lat = [], []
    backends = {}
    quantum_used = fallbacks = timeouts = risk_evaluated = 0
    for m in atts:
        oc[m["outcome"]] = oc.get(m["outcome"], 0) + 1
        total_lat.append(m["total_latency_ms"])
        mal, stopped = m["is_malicious"], m["stopped"]
        if mal and stopped:
            tp += 1
        elif mal and not stopped:
            fn += 1
        elif not mal and stopped:
            fp += 1
        else:
            tn += 1
        r = m.get("risk")
        if r:
            risk_evaluated += 1
            if r.get("latency_ms") is not None:
                risk_lat.append(r["latency_ms"])
            b = r.get("backend") or "n/a"
            backends[b] = backends.get(b, 0) + 1
            if r.get("quantum"):
                quantum_used += 1
            if r.get("fallback"):
                fallbacks += 1
            if r.get("timeout"):
                timeouts += 1
    edge_block = oc["edge_blocked"] + oc["edge_challenged"] + oc["edge_rate_limited"]
    app_block = (oc["app_auth_failed"] + oc["app_authz_denied"] +
                 oc["app_validation_failed"] + oc["app_rate_limited"])
    risk_block = oc["risk_hold"] + oc["risk_review"] + oc["risk_step_up"]
    total = len(atts)
    forwarded_app = total - edge_block
    protected = forwarded_app - app_block
    precision = round(tp / (tp + fp), 4) if (tp + fp) else None
    recall = round(tp / (tp + fn), 4) if (tp + fn) else None
    return {
        "mode": run.mode, "total_events": len(run.events), "total_attempts": total,
        "unique_sources": len({m["source_ip"] for m in atts}),
        "edge_observed": total, "edge_blocked": oc["edge_blocked"],
        "edge_challenged": oc["edge_challenged"], "edge_rate_limited": oc["edge_rate_limited"],
        "forwarded_to_app": forwarded_app,
        "app_auth_failed": oc["app_auth_failed"], "app_authz_denied": oc["app_authz_denied"],
        "app_validation_failed": oc["app_validation_failed"], "app_rate_limited": oc["app_rate_limited"],
        "protected_reached": protected,
        "risk_evaluated": risk_evaluated, "risk_hold": oc["risk_hold"],
        "risk_review": oc["risk_review"], "risk_step_up": oc["risk_step_up"],
        "allowed": oc["allowed"], "unauthorized_completed": oc["unauthorized_success"],
        "edge_blocks_total": edge_block, "app_blocks_total": app_block, "risk_blocks_total": risk_block,
        "outcome_counts": oc,
        "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
        "precision": precision, "recall": recall,
        "latency_total_ms": {"p50": _pct(total_lat, 0.5), "p95": _pct(total_lat, 0.95), "p99": _pct(total_lat, 0.99)},
        "latency_risk_ms": {"p50": _pct(risk_lat, 0.5), "p95": _pct(risk_lat, 0.95), "p99": _pct(risk_lat, 0.99)},
        "backends": backends, "quantum_used": quantum_used,
        "fallback_events": fallbacks, "model_timeouts": timeouts,
    }


def compute_compromise(run):
    atts = list(run.attempts)
    if not atts:
        return {"state": "INCONCLUSIVE", "evidence": "no attempts recorded",
                "objective_successes": 0, "unauthorized_total": 0}
    obj_success = sum(1 for m in atts if m["outcome"] == "unauthorized_success" and m["objective"])
    unauth = sum(1 for m in atts if m["outcome"] == "unauthorized_success")
    # Only malicious attempts reaching an internal layer count as "suspicious
    # activity inside"; benign traffic legitimately reaching the app does not.
    reached_internal = sum(1 for m in atts
                           if m["is_malicious"] and not m["outcome"].startswith("edge_"))
    threshold = run.scenario["objective_threshold"]
    if obj_success >= threshold:
        state = "COMPROMISED"
        ev = f"{obj_success} unauthorized objective action(s) completed (threshold {threshold})."
    elif unauth > 0:
        state = "PARTIALLY_COMPROMISED"
        ev = f"{unauth} unauthorized action(s) completed, below the objective threshold {threshold}."
    elif reached_internal > 0:
        state = "CONTAINED"
        ev = f"{reached_internal} attempt(s) reached an internal layer but 0 unauthorized actions completed."
    else:
        state = "BLOCKED"
        ev = f"All {len(atts)} attempt(s) stopped at the edge; 0 reached the application."
    return {"state": state, "evidence": ev, "objective_successes": obj_success,
            "unauthorized_total": unauth, "threshold": threshold}


class CyberRange:
    """Owns runs. ``risk_scorer(features, mode) -> dict`` is injected by the
    dashboard so the RiskFabric step can use the real engine when reachable."""

    def __init__(self, risk_scorer: Optional[Callable] = None, live_delay=0.05):
        self.risk_scorer = risk_scorer or default_local_scorer
        self.live_delay = live_delay
        self._runs = {}
        self._lock = threading.RLock()

    def catalogue(self):
        return scenario_catalogue()

    def _new_run(self, scenario_id, mode, seed, intensity):
        run_id = "run-" + uuid.uuid4().hex[:10]
        run = RangeRun(run_id, scenario_id, mode, seed, intensity)
        with self._lock:
            self._runs[run_id] = run
        return run

    def _execute(self, run, delay):
        run.status = "RUNNING"
        run.started_at = _utcnow_iso()
        rng = random.Random(f"{run.scenario_id}:{run.seed}")
        n = min(int(run.scenario["base"] * max(1, run.intensity)), 200)
        attempts = run.scenario["generator"](rng, n)
        run.total_planned = len(attempts)
        edge, app = EdgeDefense(), AppDefense()
        state = {"ident_count": {}}
        for a in attempts:
            if run.cancel.is_set():
                run.status = "STOPPED"
                break
            meta = _process_attempt(run, a, edge, app, self.risk_scorer, state)
            with run.lock:
                run.attempts.append(meta)
            if delay:
                time.sleep(delay)
        if run.status != "STOPPED":
            run.status = "COMPLETED"
        run.finished_at = _utcnow_iso()

    def start(self, scenario_id, mode="quantum", seed=42, intensity=1, live=True):
        if scenario_id not in SCENARIOS:
            raise ValueError(f"unknown scenario '{scenario_id}'")
        if mode not in ("baseline", "classical", "quantum"):
            raise ValueError(f"unknown mode '{mode}'")
        run = self._new_run(scenario_id, mode, int(seed), int(intensity))
        if live:
            t = threading.Thread(target=self._execute, args=(run, self.live_delay), daemon=True)
            t.start()
        else:
            self._execute(run, 0.0)
        return run.run_id

    def stop(self, run_id):
        run = self._runs.get(run_id)
        if run and run.status == "RUNNING":
            run.cancel.set()
            return True
        return False

    def get(self, run_id):
        return self._runs.get(run_id)

    def status(self, run_id, events_limit=60):
        run = self._runs.get(run_id)
        if not run:
            return None
        with run.lock:
            recent = [e.as_dict() for e in run.events[-events_limit:]]
            progressed = len(run.attempts)
        return {
            "run_id": run.run_id, "scenario_id": run.scenario_id,
            "scenario_name": run.scenario["name"], "objective": run.scenario["objective"],
            "ground_truth": run.scenario["ground_truth"], "mode": run.mode,
            "seed": run.seed, "intensity": run.intensity, "status": run.status,
            "started_at": run.started_at, "finished_at": run.finished_at,
            "planned": run.total_planned, "progressed": progressed,
            "metrics": compute_metrics(run), "compromise": compute_compromise(run),
            "events": recent, "policy": POLICY,
        }

    def compare(self, scenario_id, seed=42, intensity=1):
        """Run all three modes on identical seeded inputs and return a matrix."""
        if scenario_id not in SCENARIOS:
            raise ValueError(f"unknown scenario '{scenario_id}'")
        results = {}
        for mode in ("baseline", "classical", "quantum"):
            run = self._new_run(scenario_id, mode, int(seed), int(intensity))
            self._execute(run, 0.0)
            results[mode] = {"run_id": run.run_id, "metrics": compute_metrics(run),
                             "compromise": compute_compromise(run)}
        rows = []
        for mode in ("baseline", "classical", "quantum"):
            m, c = results[mode]["metrics"], results[mode]["compromise"]
            rows.append({
                "scenario": scenario_id, "mode": mode, "run_id": results[mode]["run_id"],
                "generated_events": m["total_attempts"], "edge_blocks": m["edge_blocks_total"],
                "app_blocks": m["app_blocks_total"], "risk_detections": m["risk_blocks_total"],
                "unauthorized_completed": m["unauthorized_completed"],
                "compromise_state": c["state"], "false_positives": m["false_positive"],
                "false_negatives": m["false_negative"], "precision": m["precision"],
                "recall": m["recall"], "detection_latency_p95_ms": m["latency_total_ms"]["p95"],
                "decision_latency_p95_ms": m["latency_risk_ms"]["p95"],
                "fallback_events": m["fallback_events"], "quantum_used": m["quantum_used"],
                "backends": m["backends"],
            })
        return {"scenario": scenario_id, "seed": int(seed), "intensity": int(intensity),
                "results": results, "matrix": rows}

    def export(self, run_id, fmt="json"):
        run = self._runs.get(run_id)
        if not run:
            return None, None
        if fmt == "csv":
            import csv as _csv
            import io
            buf = io.StringIO()
            cols = ["correlation_id", "identity_id", "kind", "action", "amount",
                    "is_malicious", "objective", "outcome", "stopped", "total_latency_ms"]
            w = _csv.writer(buf)
            w.writerow(cols + ["risk_decision", "risk_score", "risk_backend"])
            for m in run.attempts:
                r = m.get("risk") or {}
                w.writerow([m[c] for c in cols] + [r.get("decision"), r.get("score"), r.get("backend")])
            return buf.getvalue(), "text/csv"
        payload = {"run": self.status(run_id, events_limit=100000)}
        return payload, "application/json"
