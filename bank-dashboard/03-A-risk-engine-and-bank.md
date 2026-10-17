# PRD 03 (A): The classical risk engine and the synthetic bank

| | |
|---|---|
| Version | 1.0, 2026-10-17 |
| Owner | A (Risk ML, pro AI) |
| Folders | `scoring/`, `bank/`. Data and models in `$RF_DATA` (`replay/`, `models/`, `features/`, `bank/`), never in git |
| Pair | E (calls `scoring` and the bank). C consumes the feature export and `REPORT.md` |
| Contracts | sections 5 (`bank.log`, `payments`), 6 (tier and bank keys), 9 (scoring module), 10 (replay), 11 (bank and Shield), 13 (feature export) |

## 1. Why this PRD exists
A builds two things that everything else stands on.
1. **The reliable risk engine.**
   - It is the classical model that scores every payment at full strength, at every load.
   - It is the system of record for RiskFabric's scores.
   - The quantum challenger (PRD 05) is compared against it and never replaces it.
2. **The synthetic bank.** It plays the "existing bank" we integrate alongside, in three parts:
   - the customer channel,
   - the incumbent fraud engine,
   - the core books that post money.
   
   It has to behave like a real incumbent, including its weak spot: it approves on timeout. Otherwise the comparison in PRD 02 means nothing.

## 2. The data
- **Dataset:** IBM Transactions for Anti Money Laundering, `HI-Small_Trans.csv`.
  - It is synthetic, made by IBM's AMLworld generator, with about 5 million transactions and about 0.1% labelled laundering.
  - Columns: `Timestamp, From Bank, Account, To Bank, Account.1, Amount Received, Receiving Currency, Amount Paid, Payment Currency, Payment Format, Is Laundering`.
  - At H1, count the rows, laundering rows, accounts and the date range. Write the counts in `scoring/REPORT.md`; never quote counts from memory.
- **Account id.** Use the `Account` string. At H1 check whether it is unique across banks.
  - If it is not, use `<From Bank>-<Account>`.
  - Tell C, who records it in CONTRACTS section 0.
- **Time.**
  - `ts` is the dataset timestamp as UTC epoch seconds.
  - Rows that share a minute keep their file order.
  - The lab replays rows in order at its own rate; the payment's `ts` stays the dataset time.
- **Split.** By time, 60/20/20 into train, validation and test. Never shuffled. Every feature at time t uses only transactions before t.
- **Labels** never reach the system under test. The replay file keeps `label` for C's scoring only.

## 3. Part 1: the classical risk engine
### 3.1 Models
| Model id | What | Used by | Priority |
|---|---|---|---|
| `gfp-gbm-v1` | Graph features from IBM's Graph Feature Preprocessor (GFP, in Snap ML) plus raw features, gradient-boosted trees (LightGBM or Snap ML's booster) | RiskFabric: `standalone` decisions, `shield` shadow scores | MUST |
| `raw-gbm-v1` | Gradient-boosted trees on raw columns only (amount, currencies, format, hour, bank ids, same-bank flag) | Three jobs: the plain baseline for M-23; **the bank's incumbent model**; the fast model for the downgrade baseline | MUST |

Reusing `raw-gbm-v1` as the bank's incumbent model is deliberate (ADR-022). The bank alone is then a realistic incumbent (rules plus a plain ML model), not a straw man. The thing we compare is the architecture, not two models we tuned differently.

### 3.2 How graph features work in real time
GFP keeps a graph of recent payments and computes, for each new payment, patterns around its accounts:
- fan-in and fan-out,
- degree,
- scatter-gather,
- temporal cycles.

Graph state must be consistent and must not depend on load.
- **One writer of graph state.** Replica 8001 is the primary: it scores and adds each payment to its graph inside `score()`. Replica 8002 is a hot standby (HAProxy `backup`), so it only takes traffic if 8001 fails.
- **The standby follows.** The decision service writes every scored payment to the `payments` stream (CONTRACTS section 5). The standby calls `scoring.ingest(payment)` for each entry, so its graph stays current (SHOULD). Until this works, the standby starts from the history graph and says so in `/health` (`"graph": "history-only"`).
- **History at start.** `load(model_dir)` builds the graph from all train and validation transactions, ordered by time, so every run starts from the same state. Measure the startup time. If it is over 90 s, tell C and D at CP1.
- **Same code offline and online.** The offline evaluation and the QML export use the same feature code, run in time order. This is the only way the offline numbers describe the online system.
- If `snapml` doesn't install on s390x, build the same patterns (fan-in, fan-out, scatter-gather, short cycles) with pandas time windows over the same history, and say so in `REPORT.md`. Do not swap in another library.

### 3.3 Requirements
| ID | Requirement | Priority | Accept |
|---|---|---|---|
| A-01 | Within 30 minutes of H0, deliver the stub `scoring` package: `load`, `score` returning `{"score": 0.1, "reasons": [], ...}` in under 1 ms, `ingest` doing nothing, and `Unavailable` | MUST | E imports it; C-02 passes with the stub |
| A-02 | Data loader and time split. Write the replay file `$RF_DATA/replay/hi_small_test.csv` (test split, section 10 format, `txn_id` below `t-900000000`) | MUST, by H2 | C-08 |
| A-03 | Portable model formats (LightGBM text, Snap ML export or JSON) and a load test on the VM by H2. s390x is big-endian | MUST | a load-and-predict script prints the same scores on the laptop and the VM for 100 rows |
| A-04 | Train `raw-gbm-v1` and `gfp-gbm-v1` on train, choose hyperparameters and thresholds on validation only. Handle class imbalance with class weights or sampling, recorded in `REPORT.md` | MUST, by H6 | `REPORT.md` lists both with their settings |
| A-05 | `score(payment, signals, timeout_ms)` per section 9. Same answer at any load, no network calls, thread-safe. Primary mode adds the payment to the graph | MUST, by H6 | C-13: 1,000 replay rows, p99 at most 20 ms warm on the VM; identical output at idle and under CPU stress |
| A-06 | `score()` also returns `features`: up to 16 named floats, the same names as the `f_` columns of the QML export (A-11). E stores them for held payments only | SHOULD, by H8 | C-15 shows `features` in `hold:{txn_id}` |
| A-07 | `ingest(payment)` for the standby: adds a payment to the graph without scoring it | SHOULD, by H10 | after 1,000 payments, primary and standby give the same score for the next 100 payments |
| A-08 | Account tiers: account risk from train and validation (share of risky activity and the model's mean score), cut into high (top 2%), medium (next 8%) and low. Unseen accounts are unknown. A loader writes `tier:{acct}` before every run | MUST, by H9 | C-07 uses them; `REPORT.md` gives the tier counts |
| A-09 | `scoring/policy.json`: `verify_at` and `hold_at` chosen on validation so the hold rate is at most 2% of S1 traffic | MUST, by H9 | S1 hold rate at most 2% in C's run |
| A-10 | Reason codes: up to 3 short strings from the strongest feature contributions (for example LightGBM's per-feature contributions), mapped to plain words such as "fan-out burst", "new counterparty", "amount far above usual", plus "cluster c-17" from signals | SHOULD, by H10 | console shows reasons on held payments |
| A-11 | QML feature export (CONTRACTS section 13): candidates from the validation and test splits with their classical score, label, split and the `f_` features | MUST, by H8 | C loads it; row counts and positives are in `REPORT.md` |
| A-12 | `scoring/REPORT.md`, all measured with the commands shown:<br>- minority-class F1, PR-AUC, and recall at the top 1% of scores on the test split for both models<br>- p50/p95/p99 inference latency on the VM<br>- startup time<br>- whether the AI accelerator is present (`grep -o nnpa /proc/cpuinfo`)<br>- the snapml version, or the fallback used | MUST, by H14 | M-23 on the scoreboard comes from it |
| A-13 | Fast-model hook for the downgrade baseline: E can load `raw-gbm-v1` through `scoring` when `RF_VARIANT=submitted_design` | SHOULD, by H10 | C's `submitted_design` run completes |
| A-14 | Error analysis: which laundering patterns slipped through in S4 and S4b, and why | SHOULD, H12 to H17 | a section in `REPORT.md` |
| A-15 | Snap ML on the accelerator compared with CPU, if the accelerator is present | STRETCH | a timing table in `REPORT.md` |

## 4. Part 2: the synthetic bank (the existing bank, split into its parts)
### 4.1 The four parts
| Part | Folder or file | What it models | Endpoints |
|---|---|---|---|
| Customer and account registry | `bank/` loader, `$RF_DATA/bank/accounts.csv` | The bank's customer base: every account in the dataset, with a segment and an opening balance. All synthetic | none |
| Channel | `bank/` | The bank's existing front door. Customers reach it directly today (`bank_only`) or through RiskFabric's bypass | `POST /bank/pay`, `POST /bank/verify` |
| Incumbent fraud engine | `bank/`, `bank/rules.json`, `$RF_DATA/models/bank/raw-gbm-v1.*` | The bank's existing fraud check: rules plus `raw-gbm-v1`, with **fixed capacity** | `POST /engine/pay`, `GET /engine/health` |
| Core books | `bank/`, `$RF_DATA/bank/postings.jsonl`, `bank:bal:{acct}` | The ledger of money the bank actually moved. The ground truth for "fraud value through" | `POST /bank/settle`, `GET /bank/books`, `GET /bank/health` |

All four run in one FastAPI process on port 9000. Exact bodies are in CONTRACTS section 11.

### 4.2 The registry
`accounts.csv` columns: `acct,bank_id,segment,opening_balance,first_seen_ts`.
- Every account in the dataset is a customer. An account's existence is not a label, so this is not leakage.
- **Segment:** `business` if the account's monthly payment volume in train is in the top 10%, otherwise `retail`.
- **Opening balance:** the larger of 1,000 and 3 times the account's highest daily outflow in train. Accounts with no train history get 1,000.
- Lab-generated identities use accounts outside the registry (CONTRACTS section 0). The engine treats them as unknown.
- Seeded and deterministic: the same file every time.

### 4.3 The incumbent engine
**Rules (`bank/rules.json`).**
- Fixed at H8, before any scenario runs.
- Documented in `bank/README.md`.
- Never tuned after results.

| Rule | Condition | Outcome |
|---|---|---|
| R0 unknown account | `from_acct` not in the registry | HOLD |
| R1 large amount | amount above the segment limit (retail 10,000; business 100,000) | VERIFY |
| R2 velocity | at least 10 payments from `from_acct` within 60 s of payment time | HOLD |
| R3 card testing | at least 5 payments of 5.00 or less from `from_acct` within 300 s of payment time | HOLD |
| R4 model | `raw-gbm-v1` score at or above the bank's `hold_at` (or `verify_at`), tuned on validation for at most a 2% hold rate | HOLD (or VERIFY) |
| R5 enrichment | `X-Cluster-Risk` at least 0.8 gives HOLD; `X-Edge-Action: stepup` gives at least VERIFY. These headers only exist when RiskFabric is in front | HOLD or VERIFY |

The strictest outcome wins (HOLD over VERIFY over ALLOW). `reasons` lists the rule ids that fired.

**Capacity model.** It is the reason "bank alone" breaks under attack.
- The engine has `bank:cfg:slots` concurrent slots (default 8). Each request holds a slot for its model time plus `bank:cfg:service_ms` (an awaited sleep, so it doesn't burn the VM's CPU).
- Capacity is therefore about `slots x 1000 / service_ms` requests per second.
- At H10, C sets `service_ms` by a documented rule, **capacity = 4R** (R is the base legitimate rate from PRD 02), before any scenario runs. The effect:
  - S1 (R) and S2 (3R) fit.
  - S3 and S4 (about 5R) exceed it, as an attack would exceed a real bank's sizing.
- Requests that find no free slot wait in a queue.

**Test switches** (C-10):
- `X-Mock-Delay-Ms` adds delay.
- `X-Mock-Fail: 1` answers 503.

### 4.4 The channel (the status quo)
`POST /bank/pay` runs the bank's flow exactly as a bank does today:
1. Evaluate with the engine within `bank:cfg:deadline_ms` (default 100).
2. If the engine is late, apply `bank:cfg:fail_mode`:
   - `open` (the default, the status quo) means ALLOW with `timeout: true`;
   - `closed` means HOLD with `timeout: true`, used for the sensitivity run.
3. ALLOW is posted to the books at once. VERIFY waits for `POST /bank/verify`; a correct token posts it. HOLD is never posted during a run.

The response uses the section 3 shape with `path: "bank"` and `mode: "bank_only"` (CONTRACTS section 11).

### 4.5 The books
- `POST /bank/settle` is how RiskFabric tells the bank the final decision in `shield` and `standalone` modes.
  - The body carries the payment and the final action.
  - It is idempotent per `txn_id` (`bank:posted:{txn_id}`), so a retry never double-posts.
  - ALLOW posts: one line in `postings.jsonl`, and debit and credit on `bank:bal:{acct}`. No overdraft logic; balances may go negative, documented as out of scope.
- `GET /bank/books` returns counts and values for the console.
- Every channel, engine, verify and settle event writes one `bank.log` entry. C's metrics M-04, M-06, M-14 and M-15 depend on them.

### 4.6 Who calls what, by system
| System | Lab request goes to | Engine called by | Final decision | Who posts |
|---|---|---|---|---|
| `bank_only` | edge (status-quo config), then `/bank/pay` | the channel, inside the bank | engine, or fail-open | the channel itself |
| `shield` | edge (RiskFabric config), then the decision service | the Shield router (`/engine/pay`) | engine, or stand-in if the engine is late | the router calls `/bank/settle` |
| `standalone` | edge (RiskFabric config), then the decision service | nobody | our model, or stand-in | the decision service calls `/bank/settle` |
| bypass | edge (RiskFabric config with both replicas down), then `/bank/pay` | the channel | engine, or fail-open (the status quo) | the channel itself |

### 4.7 Requirements
| ID | Requirement | Priority | Accept |
|---|---|---|---|
| BK-01 | Within 60 minutes of H0, a stub bank on 9000: every endpoint answers in the contract shape; the engine always says ALLOW; settle appends to `postings.jsonl` | MUST | E's router and C's checks run against it |
| BK-02 | Registry builder writes `accounts.csv` and loads opening balances into `bank:bal:{acct}` | MUST, by H8 | `GET /bank/books` shows the account count |
| BK-03 | Incumbent engine rules R0 to R5 from `rules.json`, and `raw-gbm-v1` loaded from a portable file | MUST, by H8 | a unit test per rule; fixed rules committed by H8 |
| BK-04 | Capacity model with slots, `service_ms` and a queue; values read from `bank:cfg:*` at startup | MUST, by H8 | at 2 times capacity, `bank.log` shows rising `queue_ms` and timeouts |
| BK-05 | Channel `/bank/pay` and `/bank/verify` with deadline, fail mode and self-posting | MUST, by H10 | a `bank_only` S1 run completes; C-14 |
| BK-06 | Books: settle, idempotency, postings, balances, `GET /bank/books` | MUST, by H10 | C-14: postings match final ALLOWs; a repeated settle doesn't double-post |
| BK-07 | `bank.log` stream per CONTRACTS section 5 | MUST, by H10 | C-04 lists `bank.log` |
| BK-08 | Test switches `X-Mock-Delay-Ms` and `X-Mock-Fail` | MUST, by H10 | C-10 |
| BK-09 | `bank/README.md`: rules, capacity rule, fail modes, and what the bank does not model (overdrafts, settlement networks, real KYC) | MUST, by H12 | C reviews it before the freeze |
| BK-10 | Brownout switch for S5: changing `bank:cfg:service_ms` while running takes effect within 1 s | SHOULD, by H12 | C's S5 run shows rising engine latency at 60 s |

## 5. What A must not do
- No neural networks or GNNs. No shuffled splits. No labels or future data as features.
- `score()` has no load-dependent branch, no cheaper path and no network calls. The downgrade baseline exists only behind `RF_VARIANT=submitted_design`, off by default.
- No quantum or LLM imports in `scoring/` or `bank/`.
- Don't tune the bank to look bad, and don't touch the bank after H8 except to fix bugs. C must approve any fix and log it in `team/STATUS.md`.
- Don't edit `decision/`. Tell E what you need.

## 6. Build order (A)
| Hours | Work | Hand-off |
|---|---|---|
| H0 to H1 | A-01 stub (by H0:30), BK-01 stub bank (by H1). Download or copy the dataset; counts and the account-id check | E has stubs; C knows the account id |
| H1 to H2 | A-02 split and replay file; A-03 portable-format load test on the VM | B has the replay file; C-08 passes |
| H2 to H6 | A-04 both models; GFP history graph at `load()`; A-05 real `score()` | **CP1:** C-13 on the VM |
| H6 to H8 | A-11 feature export; A-06 `features`; BK-02 registry; BK-03 rules (frozen at H8); BK-04 capacity | C starts QML on real data at H8; the bank is frozen |
| H8 to H10 | A-08 tiers; A-09 policy; BK-05 channel; BK-06 books; BK-07 `bank.log`; BK-08 switches; A-07 ingest; A-10 reasons; A-13 fast-model hook | **CP2** needs C-07, C-10 (engine part), C-14 |
| H10 to H12 | BK-09 README; BK-10 brownout; fixes from CP2 | C sets the bank capacity rule |
| H12 to H13 | Support tuning; nothing changes in the bank | Tuning freeze at H13 |
| H13 to H16.5 | A-12 `REPORT.md`; A-14 error analysis on finished runs | |
| H16.5 to H17 | The rebuild test (PRD 06, D-18): follow `deploy/README.md` in a fresh clone with offset 100 and Valkey database 6 | Freeze at H17 |
| H17 to H18 | Record your video segment (model, bank, numbers; 30 s) | E assembles |
| H18 to H21 | Sleep. Then check every model and bank number in the README | |

## 7. Risks
| Risk | Response |
|---|---|
| `snapml` missing on s390x | Pandas-window fallback (section 3.2). Decide by H2 |
| LightGBM compiles slowly on s390x | Start the install in pre-flight. Use the distribution package if one exists. Snap ML's booster as the second choice |
| Memory: the CSV is about half a gigabyte; pandas needs several times that | Load only the needed columns with compact dtypes. If the VM has under 8 GB, train on a laptop and move the portable model to the VM; inference and the graph still run on LinuxONE. State this in `REPORT.md` |
| Graph build at startup is slow | Measure at CP1. If over 90 s, keep the graph history to the last N days and say so |
| Incumbent model too good or too weak | Neither matters: it is the same plain baseline everywhere, and its numbers are published |

## 8. First prompts for A (paste after "go")
```
Task (A-01): create the scoring package skeleton per CONTRACTS section 9 in scoring/: load(), score() returning a fixed score of 0.1 with empty reasons in under 1 ms, ingest() that does nothing, and Unavailable.
Done when importing scoring, calling load('x') and score() on the sample body from section 3 prints a valid dict.
```
```
Task (BK-01): create a stub bank in bank/ per CONTRACTS section 11: POST /bank/pay, POST /bank/verify, POST /engine/pay, POST /bank/settle, GET /bank/books and the two health routes on 127.0.0.1:9000. The engine always answers ALLOW; settle appends one line to $RF_DATA/bank/postings.jsonl and is idempotent by txn_id.
Done when curl calls to every route return the contract shapes. Show me a plan in at most 5 bullets first.
```
