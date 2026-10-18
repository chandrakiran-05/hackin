"""Origins for the attack map: where each simulated source IP is drawn, and real per-source counts.

Every source IP in this project is a lab address (RFC 1918 or documentation ranges) used only against the loopback
target, so none of them has a real geolocation. Each one is *assigned* an origin here so the map can show where
traffic is modelled to come from. The counts drawn on the map are not modelled: they come from the defense decisions
the simulators actually received (rate limiter, SQL-injection detector, cyber-range pipeline).
"""
import threading
import time
import zlib

SERVER = {"label": "Bank Datacenter", "city": "Frankfurt", "lat": 50.11, "lng": 8.68}

# ip -> assigned origin. `role` says what the source is in the simulation, never a claim about a real host.
ORIGINS = {
    # attack console source pool (DDoS and SQL-injection runs)
    "10.0.0.11": {"city": "New York", "country": "US", "lat": 40.71, "lng": -74.01, "role": "attack pool"},
    "10.0.0.12": {"city": "London", "country": "GB", "lat": 51.51, "lng": -0.13, "role": "attack pool"},
    "10.0.0.13": {"city": "Moscow", "country": "RU", "lat": 55.76, "lng": 37.62, "role": "attack pool"},
    "10.0.0.14": {"city": "Singapore", "country": "SG", "lat": 1.35, "lng": 103.82, "role": "attack pool"},
    "10.0.0.15": {"city": "Sao Paulo", "country": "BR", "lat": -23.55, "lng": -46.63, "role": "attack pool"},
    "10.0.0.16": {"city": "Lagos", "country": "NG", "lat": 6.52, "lng": 3.38, "role": "attack pool"},
    "10.0.0.17": {"city": "Sydney", "country": "AU", "lat": -33.87, "lng": 151.21, "role": "attack pool"},
    "10.0.0.18": {"city": "Mumbai", "country": "IN", "lat": 19.08, "lng": 72.88, "role": "attack pool"},
    # cyber range sources (simulation/cyber_range.py)
    "45.83.100.7": {"city": "Amsterdam", "country": "NL", "lat": 52.37, "lng": 4.90, "role": "attacker"},
    "45.83.100.8": {"city": "Warsaw", "country": "PL", "lat": 52.23, "lng": 21.01, "role": "attacker (flood)"},
    "45.83.100.9": {"city": "Istanbul", "country": "TR", "lat": 41.01, "lng": 28.98, "role": "attacker (flood)"},
    "198.51.100.20": {"city": "Paris", "country": "FR", "lat": 48.86, "lng": 2.35, "role": "customer"},
    "198.51.100.30": {"city": "Madrid", "country": "ES", "lat": 40.42, "lng": -3.70, "role": "customer"},
    "198.51.100.40": {"city": "Milan", "country": "IT", "lat": 45.46, "lng": 9.19, "role": "customer"},
    "192.0.2.50": {"city": "Zurich", "country": "CH", "lat": 47.37, "lng": 8.54, "role": "authenticated user"},
}

# Any IP not listed above is placed on one of these, chosen by a stable hash of the IP, and flagged as such.
_FALLBACK = [
    {"city": "Toronto", "country": "CA", "lat": 43.65, "lng": -79.38},
    {"city": "Johannesburg", "country": "ZA", "lat": -26.20, "lng": 28.05},
    {"city": "Tokyo", "country": "JP", "lat": 35.68, "lng": 139.69},
    {"city": "Mexico City", "country": "MX", "lat": 19.43, "lng": -99.13},
    {"city": "Cairo", "country": "EG", "lat": 30.04, "lng": 31.24},
    {"city": "Seoul", "country": "KR", "lat": 37.57, "lng": 126.98},
]


def locate(ip):
    """The assigned origin of a source IP: {ip, city, country, lat, lng, role, placed}."""
    ip = str(ip)
    known = ORIGINS.get(ip)
    if known:
        return dict(known, ip=ip, placed="assigned")
    spot = _FALLBACK[zlib.crc32(ip.encode()) % len(_FALLBACK)]
    return dict(spot, ip=ip, role="unlisted source", placed="hashed")


def _status(o):
    if o["breached"]:
        return "breached"
    if not o["requests"]:
        return "idle"
    share = o["stopped"] / o["requests"]
    if share >= 0.5:
        return "blocked"
    if share > 0:
        return "partial"
    return "passing"


def _finish(by_ip):
    out = []
    for ip, o in by_ip.items():
        row = dict(locate(ip), **o)
        row["stop_rate"] = round(o["stopped"] / o["requests"], 4) if o["requests"] else None
        row["status"] = _status(row)
        out.append(row)
    out.sort(key=lambda r: (-r["requests"], r["ip"]))
    return out


def _blank():
    return {"requests": 0, "stopped": 0, "passed": 0, "malicious": 0, "breached": 0, "kinds": {}, "last_seen": None}


class OriginTally:
    """Thread-safe per-source counts for the attack console, fed by the defense decisions the simulators get."""

    def __init__(self, pool=()):
        self._lock = threading.Lock()
        self._pool = list(pool)
        self._by = {}

    def record(self, ip, kind, stopped):
        with self._lock:
            o = self._by.setdefault(str(ip), _blank())
            o["requests"] += 1
            o["stopped" if stopped else "passed"] += 1
            o["kinds"][kind] = o["kinds"].get(kind, 0) + 1
            o["last_seen"] = time.time()

    def reset(self):
        with self._lock:
            self._by = {}

    def snapshot(self):
        with self._lock:
            by = {ip: dict(o, kinds=dict(o["kinds"])) for ip, o in self._by.items()}
        for ip in self._pool:            # show the whole source pool, even before it sends anything
            by.setdefault(ip, _blank())
        return _finish(by)


def origins_from_attempts(attempts):
    """Per-source counts for a cyber-range run, from its recorded attempts (one final outcome each)."""
    by = {}
    for m in attempts:
        o = by.setdefault(str(m.get("source_ip")), _blank())
        o["requests"] += 1
        o["stopped" if m.get("stopped") else "passed"] += 1
        if m.get("is_malicious"):
            o["malicious"] += 1
        if m.get("outcome") == "unauthorized_success":
            o["breached"] += 1
        kind = m.get("kind") or "request"
        o["kinds"][kind] = o["kinds"].get(kind, 0) + 1
    return _finish(by)


class TappedRateLimiter:
    """Hands the simulator the real rate limiter and records each decision per source."""

    def __init__(self, limiter, tally, kind="ddos"):
        self._limiter, self._tally, self._kind = limiter, tally, kind

    def is_allowed(self, ip):
        allowed = self._limiter.is_allowed(ip)
        self._tally.record(ip, self._kind, not allowed)
        return allowed


class TappedSQLDefense:
    """Hands the simulator the real SQL-injection detector and records each verdict per source."""

    def __init__(self, defense, tally, kind="sql"):
        self._defense, self._tally, self._kind = defense, tally, kind

    def check_query(self, query, ip_address="unknown"):
        is_safe, action = self._defense.check_query(query, ip_address)
        self._tally.record(ip_address, self._kind, not is_safe)
        return is_safe, action
