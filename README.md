# Banking Security Simulation System

A controlled, judge-ready security-testing tool that demonstrates how a
synthetic banking defense system responds to scripted attack scenarios. The
simulator drives traffic through a **real defensive pipeline** (a rate limiter
and a SQL-injection detector) and, when an allow-listed banking target is
reachable, records the **actual** response the bank returns.

> **No fabricated outcomes.** Every number on the dashboard — blocked requests,
> detection rate, bank responses — comes from a real defense decision or a real
> HTTP response. When the bank target is unreachable, that is reported as
> `UNREACHABLE` rather than being counted as a "block".

## What it does

* **Attack simulation**
  * DDoS / flood profiles (HTTP, UDP, SYN) — pacing differs per profile.
  * SQL injection techniques (basic auth-bypass, DDL hijacking, UNION exfil),
    with benign control traffic interleaved to show false-positive behaviour.
* **Source simulation** — traffic is spread across a pool of simulated source
  IP profiles so you can see per-source rate limiting.
* **Detection visibility** — every generated request is evaluated by the real
  defense modules in `simulation/defenses/`.
* **Response verification** — a sampled subset of *allowed* flood requests is
  forwarded to the configured bank target and the real `ALLOW`/`VERIFY`/`HOLD`
  response is displayed.
* **Reliable execution** — thread-safe counters, cooperative cancellation, a
  one-run-per-kind concurrency cap, bounded thread joins, and a full reset.
* **Polished dashboard** — live metrics, real throughput and defense-
  effectiveness charts, a defensive-response panel, a bank-connectivity
  indicator, and a structured event log.

## Project structure

```
simulation/
  attacks/
    ddos_simulation.py            # DDoS generator -> real rate limiter / bank
    sql_injection_simulation.py   # SQLi payloads  -> real SQLi detector
  defenses/
    rate_limiter.py               # sliding-window rate limiter (+ reset)
    sql_injection_defense.py      # pattern-based SQLi detector (+ reset)
  test_simulation.py              # proves outcomes are real + cancel/reset
dashboard/
  app.py                          # Flask control plane (RunManager + routes)
  templates/index.html            # dashboard UI (blue theme)
  static/vendor/chart.umd.js      # vendored Chart.js (offline-friendly)
  test_app.py                     # route validation / concurrency / reset tests
bank/                             # LOCAL STUB standing in for the real backend
docs/                             # attack-type notes and case studies
```

## Installation

```bash
pip install -r requirements.txt
```

To also run the bundled bank stub and its tests (optional — the real backend
lives on a separate device), install the extras listed at the bottom of
`requirements.txt`.

## Running

1. *(Optional)* start the bank stub so response verification has a target:
   ```bash
   python -m uvicorn bank.main:app --host 127.0.0.1 --port 9000
   ```
2. Start the dashboard:
   ```bash
   python dashboard/app.py
   ```
3. Open <http://localhost:5001>.

If the bank stub is not running, DDoS runs still execute and are verified
against the rate limiter; bank responses are reported as `UNREACHABLE`.

### Configuration

| Setting | Env var | Default |
| --- | --- | --- |
| Bank target URL | `RF_BANK_URL` | `http://127.0.0.1:9000` |
| Max threads per run | `SIM_MAX_THREADS` | `20` |
| Max run duration (s) | `SIM_MAX_DURATION` | `120` |

The bank target is restricted to an **allowlist** of loopback lab hosts
(`127.0.0.1`, `localhost`, `::1`). Runtime config changes are rejected for any
host outside the allowlist.

### Key endpoints

| Route | Purpose |
| --- | --- |
| `POST /start_ddos`, `POST /start_sql` | start a run (validated) |
| `POST /stop_ddos`, `POST /stop_sql`, `POST /stop_all` | cancel runs |
| `POST /reset` | cancel runs, clear defenses, logs and counters |
| `POST /test_defense` | single-input probe of a defense |
| `GET /get_status` | live state, stats, bank responses, logs |
| `GET /bank_status` | bank-target connectivity |
| `GET/POST /config` | view / adjust bank target + verification |

## Testing

```bash
python -m pytest simulation/test_simulation.py dashboard/test_app.py -q
# plus the bank stub tests (needs the optional extras):
python -m pytest bank/test_main.py -q
```

## Safety

All testing is confined to the authorized synthetic environment on loopback.
The tool adds no stealth, evasion, or third-party targeting; the target
allowlist and execution limits are enforced in `dashboard/app.py`.
