# Implementation Plan for PRD 03 (A): The Classical Risk Engine and Synthetic Bank

## Overview
This plan breaks down the work into components that can be worked on in parallel by multiple agents, following the build order and requirements specified in the PRD (A-01 through A-15, BK-01 through BK-10).

## Directory Structure
```
scoring/          # Classical risk engine
bank/             # Synthetic bank
data/
  replay/         # Replay files
  models/         # Model files
  features/       # Feature exports
  bank/           # Bank-specific data (accounts.csv, postings.jsonl, etc.)
```

## Parallel Work Streams

### Stream 1: Data Foundation (Can start immediately - H0-H2)
*Agents: 1-2*
- Download or copy the HI-Small_Trans.csv dataset
- Perform initial data analysis (row counts, laundering rows, date range)
- Determine account ID strategy (check if Account is unique across banks)
- Create data loader utilities
- Implement time-based split (60/20/20 train/validation/test, never shuffled)

**Dependencies:** None
**Deliverables:** 
- Dataset in `$RF_DATA/` 
- Initial analysis in `scoping/REPORT.md` (counts, date range)
- Time-split datasets
- Account ID determination documented

### Stream 2: Risk Engine Stub (H0-H1)
*Agents: 1*
- Create scoring package skeleton per CONTRACTS section 9
- Implement `load()` function
- Implement `score()` returning fixed score of 0.1 with empty reasons (<1ms)
- Implement `ingest()` that does nothing
- Implement `Unavailable` exception
**Dependencies:** None
**Deliverables:**
- `scoring/__init__.py` with basic package structure
- Basic functionality testable by importing and calling functions

### Stream 3: Bank Stub (H0-H1)
*Agents: 1*
- Create stub bank on port 9000
- Implement all endpoints per CONTRACTS section 11:
  - POST /bank/pay
  - POST /bank/verify  
  - POST /engine/pay
  - POST /bank/settle
  - GET /bank/books
  - GET /bank/health (two routes)
- Engine always returns ALLOW
- Settle appends one line to `$RF_DATA/bank/postings.jsonl` and is idempotent by txn_id
**Dependencies:** None
**Deliverables:**
- `bank/main.py` or equivalent FastAPI application
- Basic bank service running on port 9000

### Stream 4: Model Development (H2-H6)
*Agents: 2*
- Train `raw-gbm-v1` and `gfp-gbm-v1` on training data
- Choose hyperparameters and thresholds on validation data only
- Handle class imbalance (record approach in REPORT.md)
- Implement portable model formats (LightGBM text, Snap ML export, or JSON)
- Conduct load test on VM
- Verify same scores on laptop and VM for 100 rows
**Dependencies:** 
- Stream 1 (Data Foundation) for training/validation/test splits
**Deliverables:**
- Trained models in portable format
- Hyperparameter and threshold documentation
- Load test results

### Stream 5: Graph Feature Implementation (H2-H6)
*Agents: 1*
- Implement GFP history graph at `load()` function
- Build graph from all train and validation transactions ordered by time
- Measure startup time (target <90s)
- Implement same code for offline/online feature computation
**Dependencies:**
- Stream 1 (Data Foundation) for training/validation data
- Stream 4 (Model Development) for model integration
**Deliverables:**
- Graph feature computation implementation
- Startup time measurements
- Offline/online consistency verification

### Stream 6: Feature Export & Intermediate Features (H6-H8)
*Agents: 2*
- Implement QML feature export (validation and test splits with classical score, label, split, and f_ features)
- Implement `score()` to return `features`: up to 16 named floats matching QML export
- Build registry: write `accounts.csv` and load opening balances into `bank:bal:{acct}`
- Freeze bank rules at H8 (BK-03)
- Implement capacity model with slots, service_ms, and queue
**Dependencies:**
- Stream 1 (Data Foundation) for data
- Stream 4 (Model Development) for trained models
- Stream 5 (Graph Features) for graph computation
**Deliverables:**
- QML feature export file
- Features returned from score() function
- Bank registry (accounts.csv)
- Frozen rules.json
- Capacity model implementation

### Stream 7: Bank Functionality & Policy (H8-H10)
*Agents: 2*
- Implement account tiers (high/medium/low/unseen) from train/validation
- Implement scoring/policy.json with verify_at and hold_at (≤2% hold rate on S1)
- Implement bank channel: /bank/pay and /bank/verify with deadline, fail mode, self-posting
- Implement bank books: settle, idempotency, postings, balances, GET /bank/books
- Implement bank.log stream per CONTRACTS section 5
- Implement test switches: X-Mock-Delay-Ms and X-Mock-Fail
- Implement ingest() for standby (adds payment to graph without scoring)
- Implement reason codes (up to 3 short strings from strongest feature contributions)
- Implement fast-model hook for downgrade baseline (RF_VARIANT=submitted_design)
**Dependencies:**
- Stream 1 (Data Foundation) for account data
- Stream 4 & 5 (Models & Graph Features) for scoring
- Stream 6 (Feature Export) for feature definitions
**Deliverables:**
- Account tier implementation
- Policy.json with verify_at/hold_at
- Fully functional bank channel and books
- Bank.log logging
- Test switches
- Standby ingest functionality
- Reason codes in score output
- Fast-model hook

### Stream 8: Finalization & Documentation (H10-H17)
*Agents: 2*
- Implement and test brownout switch (BK-10): changing bank:cfg:service_ms while running takes effect within 1s
- Create bank/README.md with rules, capacity rule, fail modes, and limitations
- Complete REPORT.md with all required metrics:
  - Minority-class F1, PR-AUC, recall at top 1% of scores on test split for both models
  - p50/p95/p99 inference latency on VM
  - Startup time
  - AI accelerator presence check
  - SnapML version or fallback used
- Perform error analysis on finished runs (which laundering patterns slipped through and why)
- If accelerator present, compare Snap ML on accelerator vs CPU
**Dependencies:**
- All previous streams for complete system
**Deliverables:**
- Brownout switch functionality
- Comprehensive bank/README.md
- Detailed scoring/REPORT.md
- Error analysis documentation
- Accelerator comparison (if applicable)

## Dependency Summary

### Independent Streams (Can start immediately):
1. Data Foundation (Stream 1)
2. Risk Engine Stub (Stream 2) 
3. Bank Stub (Stream 3)

### Dependent Streams:
4. Model Development → requires Stream 1
5. Graph Feature Implementation → requires Streams 1 & 4
6. Feature Export & Intermediate Features → requires Streams 1, 4, & 5
7. Bank Functionality & Policy → requires Streams 1, 4, 5, & 6
8. Finalization & Documentation → requires all previous streams

## Critical Path
The critical path follows the build order:
Data Foundation → Model Development → Graph Features → Feature Export/Bank Registry → Bank Functionality/Policy → Finalization

## Parallelization Opportunities
- Streams 1, 2, and 3 can run completely in parallel at start
- Streams 4 and 5 can run in parallel after Stream 1 completes
- Streams 6 and 7 have some sequential dependencies but can overlap
- Stream 8 depends on completion of all previous streams but can begin as components finish

## Risk Mitigation
1. **SnapML availability**: Decide by H2 whether to use pandas window fallback
2. **LightGBM compilation**: Start install in pre-flight, use distribution package if available
3. **Memory constraints**: Load only needed columns with compact dtypes; train on laptop if VM <8GB
4. **Graph build speed**: Measure at CP1; if >90s, use last N days history
5. **Model quality**: Incumbant model performance doesn't matter as it's the same baseline everywhere

## Handoff Points
- **After H1**: E has stubs; C knows the account ID
- **After H2**: B has replay file; C-08 passes
- **After H6 (CP1)**: C-13 on the VM
- **After H8**: C starts QML on real data; bank is frozen
- **After H10 (CP2)**: Needs C-07, C-10 (engine part), C-14
- **After H12**: C sets bank capacity rule
- **After H13**: Tuning freeze
- **After H16.5**: Support for video recording
- **After H17**: Final verification