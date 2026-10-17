"""
Test script for the Bank Stub implementation
Tests that all endpoints return the contract shapes and that settle is idempotent
"""

import json
import os
import sys
from fastapi.testclient import TestClient

# Add the bank directory to the path so we can import main
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import app, POSTINGS_FILE

client = TestClient(app)

def test_health_endpoints():
    """Test health check endpoints"""
    # Test /health
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert data["version"] == "1.0.0"

    # Test /ready
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "timestamp" in data
    assert data["version"] == "1.0.0"

    print("✓ Health endpoints test passed")

def test_bank_pay_endpoint():
    """Test POST /bank/pay endpoint"""
    payment_data = {
        "txn_id": "test_txn_001",
        "amount": 100.50,
        "from_bank": "BANK001",
        "from_account": "ACC001",
        "to_bank": "BANK002",
        "to_account": "ACC002",
        "payment_format": "STANDARD",
        "timestamp": "2026-10-17T10:30:00Z"
    }

    response = client.post("/bank/pay", json=payment_data)
    assert response.status_code == 200
    data = response.json()

    # Check contract shape
    assert data["txn_id"] == "test_txn_001"
    assert data["status"] == "ALLOW"  # Stub always returns ALLOW
    assert data["path"] == "bank"
    assert data["mode"] == "bank_only"
    assert data["timeout"] == False

    print("✓ Bank pay endpoint test passed")

def test_bank_verify_endpoint():
    """Test POST /bank/verify endpoint"""
    payment_data = {
        "txn_id": "test_txn_002",
        "amount": 250.75,
        "from_bank": "BANK003",
        "from_account": "ACC003",
        "to_bank": "BANK004",
        "to_account": "ACC004",
        "payment_format": "INSTANT"
    }

    response = client.post("/bank/verify", json=payment_data)
    assert response.status_code == 200
    data = response.json()

    # Check contract shape
    assert data["txn_id"] == "test_txn_002"
    assert data["status"] == "ALLOW"  # Stub always returns ALLOW
    assert data["path"] == "bank"
    assert data["mode"] == "bank_only"
    assert data["timeout"] == False

    print("✓ Bank verify endpoint test passed")

def test_engine_pay_endpoint():
    """Test POST /engine/pay endpoint"""
    payment_data = {
        "txn_id": "test_txn_003",
        "amount": 500.00,
        "from_bank": "BANK005",
        "from_account": "ACC005",
        "to_bank": "BANK006",
        "to_account": "ACC006",
        "payment_format": "WIRE"
    }

    response = client.post("/engine/pay", json=payment_data)
    assert response.status_code == 200
    data = response.json()

    # Check contract shape
    assert data["txn_id"] == "test_txn_003"
    assert data["status"] == "ALLOW"  # Stub always returns ALLOW
    assert data["path"] == "engine"
    assert data["mode"] == "engine"
    assert data["timeout"] == False

    print("✓ Engine pay endpoint test passed")

def test_bank_settle_endpoint_idempotency():
    """Test POST /bank/settle endpoint idempotency"""
    # Clean up any existing postings file for clean test
    if os.path.exists(POSTINGS_FILE):
        os.remove(POSTINGS_FILE)

    payment_data = {
        "txn_id": "test_txn_004",
        "amount": 75.25,
        "from_bank": "BANK007",
        "from_account": "ACC007",
        "to_bank": "BANK008",
        "to_account": "ACC008",
        "payment_format": "ACH",
        "timestamp": "2026-10-17T11:00:00Z"
    }

    # First call - should create a posting
    response1 = client.post("/bank/settle", json=payment_data)
    assert response1.status_code == 200
    data1 = response1.json()
    assert data1["txn_id"] == "test_txn_004"
    assert data1["status"] == "ALLOW"
    assert data1["path"] == "bank"
    assert data1["mode"] == "settle"
    assert data1["timeout"] == False

    # Second call with same txn_id - should be idempotent (no duplicate posting)
    response2 = client.post("/bank/settle", json=payment_data)
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["txn_id"] == "test_txn_004"
    assert data2["status"] == "ALLOW"
    assert data2["path"] == "bank"
    assert data2["mode"] == "settle"
    assert data2["timeout"] == False

    # Verify only one posting was created
    assert os.path.exists(POSTINGS_FILE)
    with open(POSTINGS_FILE, 'r') as f:
        lines = f.readlines()
        assert len(lines) == 1, f"Expected 1 posting, got {len(lines)}"
        posting = json.loads(lines[0].strip())
        assert posting["txn_id"] == "test_txn_004"
        assert posting["amount"] == 75.25

    print("✓ Bank settle endpoint idempotency test passed")

def test_get_bank_books_endpoint():
    """Test GET /bank/books endpoint"""
    # Clean up any existing postings file for clean test
    if os.path.exists(POSTINGS_FILE):
        os.remove(POSTINGS_FILE)

    # Add some test data
    test_payments = [
        {
            "txn_id": "test_txn_005",
            "amount": 100.00,
            "from_bank": "BANK001",
            "from_account": "ACC001",
            "to_bank": "BANK002",
            "to_account": "ACC002",
            "payment_format": "STANDARD"
        },
        {
            "txn_id": "test_txn_006",
            "amount": 200.00,
            "from_bank": "BANK003",
            "from_account": "ACC003",
            "to_bank": "BANK004",
            "to_account": "ACC004",
            "payment_format": "STANDARD"
        }
    ]

    # Make settle calls to create postings
    for payment in test_payments:
        response = client.post("/bank/settle", json=payment)
        assert response.status_code == 200

    # Now test the books endpoint
    response = client.get("/bank/books")
    assert response.status_code == 200
    data = response.json()

    # Should have 2 unique accounts (ACC001, ACC002, ACC003, ACC004 = 4 unique)
    # Actually: ACC001, ACC002 from first payment and ACC003, ACC004 from second = 4 unique
    assert data["account_count"] == 4
    assert data["total_postings"] == 2
    assert data["total_amount"] == 300.00  # 100.00 + 200.00

    print("✓ Get bank books endpoint test passed")

def run_all_tests():
    """Run all tests"""
    print("Running bank stub tests...")
    print("=" * 50)

    try:
        test_health_endpoints()
        test_bank_pay_endpoint()
        test_bank_verify_endpoint()
        test_engine_pay_endpoint()
        test_bank_settle_endpoint_idempotency()
        test_get_bank_books_endpoint()

        print("=" * 50)
        print("✓ All tests passed!")
        return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)