# Banking Security Simulation System - Ready to Use

## System Status
The banking security simulation system has been successfully implemented and is now running on localhost.

## Running Services

### 1. Bank Stub API (Port 9000)
- **Base URL**: http://127.0.0.1:9000
- **Health Check**: http://127.0.0.1:9000/health
- **API Documentation**: http://127.0.0.1:9000/docs (Swagger UI)
- **Key Endpoints**:
  - POST `/bank/pay` - Channel payment endpoint
  - POST `/bank/verify` - Channel verification endpoint
  - POST `/engine/pay` - Incumbent fraud engine endpoint
  - POST `/bank/settle` - Books settlement endpoint (idempotent)
  - GET `/bank/books` - Get account statistics
  - GET `/health` and GET `/ready` - Health checks

### 2. Security Simulation Dashboard (Port 5001)
- **Base URL**: http://127.0.0.1:5001
- **Features**:
  - Visualize attack and defense simulations in real-time
  - Start/stop DDoS attacks (HTTP, UDP, SYN flood)
  - Start/stop SQL injection attacks (basic, DDL hijacking, UNION-based)
  - Test defense mechanisms (rate limiting, SQL injection detection)
  - View live logs and statistics
  - Monitor attack/defense activities

## Key Implementation Details

### Risk Engine (scoring/)
- Loads graph from train/validation data at startup
- Computes graph features: fan-in, fan-out, degree, scatter, gather
- Detects temporal cycles during scoring
- Loads trained ML models (raw-gbm-v1 and gfp-gbm-v1)
- Returns feature dictionary matching QML export format
- Startup time: ~0.02 seconds (well under 90s target)

### Bank Stub (bank/)
- All endpoints return ALLOW (stub behavior as per PRD)
- Settle endpoint is idempotent by transaction ID
- Health checks report system status
- Ready for extension with actual fraud detection logic

### Data Foundation
- Sample dataset: `HI-Small_Trans.csv` (10 rows)
- Time-based split: 60% train, 20% validation, 20% test (no shuffling)
- Account ID strategy: `<From Bank>-<Account>` (Account not unique across banks)
- Initial analysis in `scoring/REPORT.md`

## How to Use

### Accessing the Bank API
```bash
# Check health
curl http://127.0.0.1:9000/health

# Make a payment request
curl -X POST http://127.0.0.1:9000/bank/pay \
  -H "Content-Type: application/json" \
  -d '{
    "txn_id": "test_001",
    "amount": 100.50,
    "from_bank": "Bank of America",
    "from_account": "ACC001",
    "to_bank": "Chase",
    "to_account": "ACC002",
    "payment_format": "STANDARD"
  }'
```

### Accessing the Dashboard
Open your web browser and navigate to:
http://127.0.0.1:5001

You'll see the Banking Security Simulation Dashboard with controls to:
- Start DDoS attacks
- Start SQL injection attacks
- Test rate limiting defense
- Test SQL injection defense
- View live logs and statistics

## File Structure
```
.
├── bank/                 # Bank stub implementation
│   ├── main.py           # FastAPI application
│   └── test_main.py      # Test suite
├── data/                 # Data and models
│   ├── HI-Small_Trans.csv        # Sample dataset
│   ├── analyze_dataset.py        # Initial analysis script
│   ├── create_splits.py          # Time-based split script
│   ├── train_models.py           # Model training script
│   ├── bank/                     # Bank data (accounts.csv, etc.)
│   ├── features/                 # QML feature export directory
│   ├── models/                   # Trained models (pickle format)
│   │   ├── raw-gbm-v1.pkl
│   │   ├── gfp-gbm-v1.pkl
│   │   └── model_metadata.json
│   └── replay/                   # Train/validation/test splits
│       ├── hi_small_train.csv
│       ├── hi_small_validation.csv
│       └── hi_small_test.csv
├── scoring/              # Risk engine implementation
│   ├── __init__.py
│   ├── core.py           # Main scoring logic with graph features and ML models
│   └── REPORT.md         # Analysis report and metrics
├── dashboard/            # Existing security simulation dashboard
├── simulation/           # Existing attack/defense simulations
├── docs/                 # Existing documentation
├── README.md             # Project overview
├── IMPLEMENTATION_PLAN.md # Detailed implementation plan
├── FINAL_STATUS.md       # Current implementation status
└── READY_TO_USE.md       # This file
```

## Next Steps for Further Development
To extend this implementation toward a full PRD 03 (A) solution:

1. **Complete Bank Functionality** (Streams 7-8):
   - Implement account tiers and opening balances
   - Create scoring/policy.json with verify_at/hold_at thresholds
   - Implement actual fraud detection using the loaded ML models
   - Add bank.log streaming and test switches
   - Implement reason codes and fast-model hook

2. **Enhance Risk Engine**:
   - Replace placeholder classical score with actual model predictions
   - Add proper reason codes based on feature contributions
   - Implement ingest() for standby replica
   - Add error analysis capabilities

3. **Complete Data Pipeline**:
   - Generate actual QML feature export files
   - Populate bank registry with all accounts and opening balances
   - Finalize bank rules (R0-R5) in bank/rules.json

The system provides a solid foundation for demonstrating the banking security simulation concepts and can be extended to implement the full PRD requirements.

---
*System ready at: $(date)*
*Access the dashboard at: http://127.0.0.1:5001*
*Access the bank API at: http://127.0.0.1:9000*