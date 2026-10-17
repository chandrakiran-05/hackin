# Data Foundation Analysis Report

## Dataset Overview
- **File**: HI-Small_Trans.csv
- **Row Count**: 10
- **Column Count**: 8
- **Columns**: Date, From Bank, Account, To Bank, To Account, Amount, Currency, Transaction Type, Composite_Account_ID

## Data Quality
- **Duplicate Rows**: 0
- **Date Range**: 2023-01-01 08:30:00 to 2023-01-08 12:00:00
- **Date Range (Days)**: 7

## Account ID Strategy
- **Account Uniqueness Check**: Not Unique
- **Selected Strategy**: <From Bank>-<Account>
- **Reasoning**: Account column is not unique across banks, using composite key

## Sample Data (First 5 Rows)
               Date       From Bank   Account         To Bank  To Account  Amount Currency Transaction Type      Composite_Account_ID
2023-01-01 08:30:00 Bank of America 123456789           Chase   987654321  100.50      USD          Payment Bank of America-123456789
2023-01-01 09:15:00           Chase 987654321 Bank of America   123456789   50.25      USD         Transfer           Chase-987654321
2023-01-02 10:00:00 Bank of America 123456789     Wells Fargo   456789123  200.00      USD          Payment Bank of America-123456789
2023-01-03 11:30:00     Wells Fargo 456789123 Bank of America   123456789  150.75      USD         Transfer     Wells Fargo-456789123
2023-01-03 14:20:00 Bank of America 123456789           Chase   987654321  300.00      USD          Payment Bank of America-123456789

## Graph Feature Implementation (GFP)
As per PRD A-05, we implemented the GFP history graph in the `load()` function of `scoring/core.py`.

**Implementation Details:**
1. **Graph Construction**: The graph is built from the combined training and validation datasets (time-ordered).
   - Nodes: Banks (identified by 'From Bank' and 'To Bank' fields)
   - Edges: Directed transactions from 'From Bank' to 'To Bank'
   - The graph is represented as adjacency lists for both outgoing and incoming edges.

2. **Precomputed Features** (for each bank):
   - **Fan-in**: Number of incoming edges (unique banks that have sent transactions to this bank)
   - **Fan-out**: Number of outgoing edges (unique banks that this bank has sent transactions to)
   - **Degree**: Sum of fan-in and fan-out
   - **Scatter**: Standard deviation of outgoing transaction amounts (volatility of sent amounts)
   - **Gather**: Standard deviation of incoming transaction amounts (volatility of received amounts)
   - **Temporal Cycles**: During scoring, we check if adding the current transaction would create a cycle (i.e., if there's a path from the 'To Bank' back to the 'From Bank' in the current graph)

3. **Consistency**: The same graph construction and feature computation logic is used for both offline and online modes, as the `load()` function is called at startup and the precomputed features are stored in memory.

4. **Startup Time**: The `load()` function measures and returns the time taken to build the graph and compute features.
   - **Measured Startup Time**: 0.0208 seconds (well under the 90-second target)

## Feature Export Implementation (A-06 through A-13)
As per PRD A-06 through A-13, we implemented feature export and intermediate features:

### A-06: score() returns features matching QML export format
The `score()` function in `scoring/core.py` now returns a dictionary with up to 16 named floats matching the QML export format:
- `classical_score`: Placeholder score (0.5) to be replaced by trained model
- `f_source_fan_in`: Source bank fan-in feature
- `f_source_fan_out`: Source bank fan-out feature  
- `f_source_degree`: Source bank degree feature
- `f_source_scatter`: Source bank scatter feature (std of outgoing amounts)
- `f_source_gather`: Source bank gather feature (std of incoming amounts)
- `f_target_fan_in`: Target bank fan-in feature
- `f_target_fan_out`: Target bank fan-out feature
- `f_target_degree`: Target bank degree feature
- `f_target_scatter`: Target bank scatter feature
- `f_target_gather`: Target bank gather feature
- `f_would_create_cycle`: Cycle detection flag (1 if transaction would create cycle, 0 otherwise)

### A-11: QML feature export
Created QML feature export file at `data/features/qml_feature_export.csv` containing:
- Candidates from validation and test splits (using validation data as test proxy)
- Classical score, label, and split columns
- All f_ features matching the score() function output
- **Format**: CSV with columns: classical_score, label, split, f_source_fan_in, f_source_fan_out, f_source_degree, f_source_scatter, f_source_gather, f_target_fan_in, f_target_fan_out, f_target_degree, f_target_scatter, f_target_gather, f_would_create_cycle
- **Rows**: 4 rows (2 validation + 2 test)

### Intermediate Features Implementation

#### Accounts Registry (BK-02)
Created `data/bank/accounts.csv` with:
- Columns: acct,bank_id,segment,opening_balance,first_seen_ts
- One row per unique bank from the dataset
- Opening balances initialized to 10,000.00
- Segment set to 'retail' for all accounts
- First seen timestamp set to dataset start

#### Incumbent Engine Rules (BK-03)
Created `bank/rules.json` with frozen rules R0-R5:
- **R0 unknown account**: HOLD if from_acct not in registry
- **R1 large amount**: VERIFY if amount above segment limit
- **R2 velocity**: HOLD if ≥10 payments from from_acct within 60s
- **R3 card testing**: HOLD if ≥5 payments of ≤5.00 from from_acct within 300s
- **R4 model**: HOLD if raw-gbm-v1 score ≥ hold_at/verify_at
- **R5 enrichment**: HOLD/VERIFY based on RiskFabric headers
- Rules frozen at H8 as required

#### Capacity Model (BK-04)
Implemented in `bank/main.py`:
- Reads configuration from `bank:cfg:*` at startup (slots, service_ms)
- Defaults: 8 slots, 50ms service time
- Implements queueing system when no slots available
- Engine holds slot for service_ms duration per request
- Provides timeout behavior when queue waits too long

## Analysis Timestamp
2026-10-17 22:55:00
