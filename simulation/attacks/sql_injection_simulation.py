"""
SQL Injection Attack Simulation (including DDL hijacking)
Simulates SQL injection attacks for educational purposes.
"""

import time
import threading
from datetime import datetime

class SQLInjectionSimulator:
    def __init__(self):
        self.attack_active = False
        self.attack_threads = []
        self.queries_attempted = 0
        self.successful_injections = 0

    def basic_sqli(self, duration=10):
        """Simulate basic SQL injection (e.g., bypassing login)"""
        print(f"[ATTACK] Starting basic SQL injection attack")
        end_time = time.time() + duration

        while time.time() < end_time and self.attack_active:
            # Simulate sending SQL injection payload
            self.queries_attempted += 1
            payload = "' OR '1'='1"
            # In a real scenario, this would be sent to a login form
            if random.random() < 0.3:  # Simulate 30% success rate
                self.successful_injections += 1
                print(f"[ATTACK] SQLi SUCCESS: Bypassed login with payload: {payload}")
            else:
                print(f"[ATTACK] SQLi FAILED: Payload blocked: {payload}")
            time.sleep(0.5)  # Simulate delay between attempts

        print(f"[ATTACK] Basic SQLi completed. Attempts: {self.queries_attempted}, Success: {self.successful_injections}")

    def ddl_hijacking(self, duration=10):
        """Simulate DDL hijacking attack (altering database schema)"""
        print(f"[ATTACK] Starting DDL hijacking attack")
        end_time = time.time() + duration

        while time.time() < end_time and self.attack_active:
            # Simulate sending DDL injection payload
            self.queries_attempted += 1
            # Examples of DDL hijacking payloads
            ddl_payloads = [
                "1; DROP TABLE users; --",
                "1; ALTER TABLE accounts ADD COLUMN backdoor VARCHAR(50); --",
                "1; CREATE TABLE hacked (id INT, data VARCHAR(100)); --"
            ]
            payload = random.choice(ddl_payloads)

            # Simulate success rate (lower for DDL as it's more restricted)
            if random.random() < 0.1:  # 10% success rate for DDL
                self.successful_injections += 1
                print(f"[ATTACK] DDL HIJACKING SUCCESS: Executed: {payload}")
            else:
                print(f"[ATTACK] DDL HIJACKING FAILED: Blocked: {payload}")
            time.sleep(0.7)  # Simulate delay between attempts

        print(f"[ATTACK] DDL hijacking completed. Attempts: {self.queries_attempted}, Success: {self.successful_injections}")

    def union_based_sqli(self, duration=10):
        """Simulate UNION-based SQL injection to extract data"""
        print(f"[ATTACK] Starting UNION-based SQL injection attack")
        end_time = time.time() + duration

        while time.time() < end_time and self.attack_active:
            self.queries_attempted += 1
            payload = "' UNION SELECT username, password FROM users; --"
            if random.random() < 0.2:  # 20% success rate
                self.successful_injections += 1
                print(f"[ATTACK] UNION SQLi SUCCESS: Extracted data with payload: {payload}")
            else:
                print(f"[ATTACK] UNION SQLi FAILED: Payload blocked: {payload}")
            time.sleep(0.6)

        print(f"[ATTACK] UNION SQLi completed. Attempts: {self.queries_attempted}, Success: {self.successful_injections}")

    def start_attack(self, attack_type="basic", duration=10, threads=3):
        """Start SQL injection attack with specified type"""
        self.attack_active = True
        self.queries_attempted = 0
        self.successful_injections = 0

        print(f"[INFO] Starting {attack_type} SQL injection attack with {threads} threads for {duration} seconds")

        attack_methods = {
            "basic": self.basic_sqli,
            "ddl": self.ddl_hijacking,
            "union": self.union_based_sqli
        }

        method = attack_methods.get(attack_type.lower(), self.basic_sqli)

        # Create and start attack threads
        for i in range(threads):
            thread = threading.Thread(target=method, args=(duration,))
            thread.daemon = True
            thread.start()
            self.attack_threads.append(thread)

        # Wait for all threads to complete
        for thread in self.attack_threads:
            thread.join(timeout=duration + 2)

        self.attack_active = False
        print(f"[INFO] Attack finished. Total queries attempted: {self.queries_attempted}, Successful injections: {self.successful_injections}")

    def stop_attack(self):
        """Stop the ongoing attack"""
        self.attack_active = False
        print("[INFO] Attack stopped by user")

# Import random at the top if we use it
import random

if __name__ == "__main__":
    # Example usage
    simulator = SQLInjectionSimulator()
    print("SQL Injection Attack Simulator")
    print("1. Basic SQLi (Authentication Bypass)")
    print("2. DDL Hijacking (Schema Alteration)")
    print("3. UNION-based SQLi (Data Extraction)")

    choice = input("Select attack type (1-3): ").strip()
    attack_type = {"1": "basic", "2": "ddl", "3": "union"}.get(choice, "basic")

    duration = int(input("Enter attack duration (seconds): ") or "10")
    threads = int(input("Enter number of threads: ") or "3")

    try:
        simulator.start_attack(attack_type, duration, threads)
    except KeyboardInterrupt:
        simulator.stop_attack()