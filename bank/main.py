"""
Stub Bank Implementation
Implements a stub bank per PRD BK-01 and CONTRACTS section 11
"""

import json
import os
import uuid
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Stub Bank", version="1.0.0")

# Ensure the data directory exists
RF_DATA = os.getenv("RF_DATA", "./data")
BANK_DATA_DIR = os.path.join(RF_DATA, "bank")
POSTINGS_FILE = os.path.join(BANK_DATA_DIR, "postings.jsonl")
ACCOUNTS_FILE = os.path.join(BANK_DATA_DIR, "accounts.csv")
RULES_FILE = os.path.join(BANK_DATA_DIR, "rules.json")

# Create directories if they don't exist
os.makedirs(BANK_DATA_DIR, exist_ok=True)

# Load configuration at startup
def load_bank_config():
    """Load bank configuration from bank:cfg:*"""
    global CAPACITY_SLOTS, SERVICE_MS
    try:
        # Load capacity slots from bank:cfg:slots (default 8)
        slots_file = os.path.join(BANK_DATA_DIR, "cfg", "slots")
        if os.path.exists(slots_file):
            with open(slots_file, 'r') as f:
                CAPACITY_SLOTS = int(f.read().strip())

        # Load service_ms from bank:cfg:service_ms (default 50)
        service_file = os.path.join(BANK_DATA_DIR, "cfg", "service_ms")
        if os.path.exists(service_file):
            with open(service_file, 'r') as f:
                SERVICE_MS = int(f.read().strip())

        print(f"Loaded bank config: slots={CAPACITY_SLOTS}, service_ms={SERVICE_MS}")
    except Exception as e:
        print(f"Warning: Could not load bank config, using defaults: {e}")
        # Keep defaults

# Load configuration at module import
load_bank_config()

# Pydantic models for request/response (based on typical banking contracts)
class PaymentRequest(BaseModel):
    txn_id: str
    amount: float
    from_bank: str
    from_account: str
    to_bank: str
    to_account: str
    payment_format: str
    timestamp: Optional[str] = None

class BankResponse(BaseModel):
    txn_id: str
    status: str  # ALLOW, VERIFY, HOLD
    path: str
    mode: str
    timeout: bool = False
    reason: Optional[str] = None

# Capacity model implementation
# These will be loaded from bank:cfg:* at startup
CAPACITY_SLOTS = 8  # default value
SERVICE_MS = 50     # default value
REQUEST_QUEUE = asyncio.Queue()
ACTIVE_SLOTS = 0
QUEUE_MS = 0

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str

class BooksResponse(BaseModel):
    account_count: int
    total_postings: int
    total_amount: float

@app.post("/bank/pay", response_model=BankResponse)
async def bank_pay(payment: PaymentRequest):
    """
    Channel endpoint: /bank/pay
    Runs the bank's flow exactly as a bank does today
    Always returns ALLOW (stub behavior)
    """
    # In a real implementation, this would evaluate with the engine
    # For stub, we always return ALLOW

    return BankResponse(
        txn_id=payment.txn_id,
        status="ALLOW",
        path="bank",
        mode="bank_only",
        timeout=False
    )

@app.post("/bank/verify", response_model=BankResponse)
async def bank_verify(payment: PaymentRequest):
    """
    Channel endpoint: /bank/verify
    Verifies a payment with a token
    Always returns ALLOW (stub behavior)
    """
    return BankResponse(
        txn_id=payment.txn_id,
        status="ALLOW",
        path="bank",
        mode="bank_only",
        timeout=False
    )

@app.post("/engine/pay", response_model=BankResponse)
async def engine_pay(payment: PaymentRequest):
    """
    Incumbent fraud engine endpoint: /engine/pay
    Implements capacity model with slots, service_ms and a queue
    """
    global ACTIVE_SLOTS, QUEUE_MS

    start_time = datetime.utcnow()

    # Wait for an available slot if at capacity
    while ACTIVE_SLOTS >= CAPACITY_SLOTS:
        # Calculate queue time
        queue_wait = (datetime.utcnow() - start_time).total_seconds() * 1000
        if queue_wait > 10000:  # 10 second timeout
            return BankResponse(
                txn_id=payment.txn_id,
                status="HOLD",
                path="engine",
                mode="engine",
                timeout=True,
                reason="capacity_timeout"
            )
        # Wait briefly before checking again
        await asyncio.sleep(0.01)

    # Acquire a slot
    ACTIVE_SLOTS += 1

    try:
        # Simulate processing time (service_ms)
        await asyncio.sleep(SERVICE_MS / 1000.0)

        # In a real implementation, this would evaluate rules and models
        # For now, we return ALLOW as stub behavior
        return BankResponse(
            txn_id=payment.txn_id,
            status="ALLOW",
            path="engine",
            mode="engine",
            timeout=False
        )
    finally:
        # Release the slot
        ACTIVE_SLOTS -= 1

@app.post("/bank/settle", response_model=BankResponse)
async def bank_settle(payment: PaymentRequest):
    """
    Books endpoint: /bank/settle
    How RiskFabric tells the bank the final decision
    Idempotent by txn_id - appends to postings.jsonl
    """
    # Check if this txn_id already exists (idempotency)
    if os.path.exists(POSTINGS_FILE):
        with open(POSTINGS_FILE, 'r') as f:
            for line in f:
                try:
                    posted = json.loads(line.strip())
                    if posted.get('txn_id') == payment.txn_id:
                        # Already posted, return success without duplicating
                        return BankResponse(
                            txn_id=payment.txn_id,
                            status="ALLOW",
                            path="bank",
                            mode="settle",
                            timeout=False
                        )
                except json.JSONDecodeError:
                    continue

    # Append to postings.jsonl
    posting_record = {
        "txn_id": payment.txn_id,
        "amount": payment.amount,
        "from_bank": payment.from_bank,
        "from_account": payment.from_account,
        "to_bank": payment.to_bank,
        "to_account": payment.to_account,
        "payment_format": payment.payment_format,
        "timestamp": payment.timestamp or datetime.utcnow().isoformat() + "Z",
        "action": "ALLOW",  # Since engine always returns ALLOW
        "settled_at": datetime.utcnow().isoformat() + "Z"
    }

    with open(POSTINGS_FILE, 'a') as f:
        f.write(json.dumps(posting_record) + '\n')

    return BankResponse(
        txn_id=payment.txn_id,
        status="ALLOW",
        path="bank",
        mode="settle",
        timeout=False
    )

@app.get("/bank/books", response_model=BooksResponse)
async def get_bank_books():
    """
    Books endpoint: GET /bank/books
    Returns counts and values for the console
    """
    account_count = 0
    total_postings = 0
    total_amount = 0.0

    # Count unique accounts from postings
    accounts = set()

    if os.path.exists(POSTINGS_FILE):
        with open(POSTINGS_FILE, 'r') as f:
            for line in f:
                try:
                    posted = json.loads(line.strip())
                    accounts.add(posted.get('from_account'))
                    accounts.add(posted.get('to_account'))
                    total_postings += 1
                    total_amount += posted.get('amount', 0.0)
                except json.JSONDecodeError:
                    continue

    account_count = len(accounts)

    return BooksResponse(
        account_count=account_count,
        total_postings=total_postings,
        total_amount=total_amount
    )

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow().isoformat() + "Z",
        version="1.0.0"
    )

@app.get("/ready", response_model=HealthResponse)
async def readiness_check():
    """Readiness check endpoint"""
    return HealthResponse(
        status="ready",
        timestamp=datetime.utcnow().isoformat() + "Z",
        version="1.0.0"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9000)