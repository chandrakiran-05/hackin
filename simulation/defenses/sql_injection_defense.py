"""
SQL Injection Defense Simulation
Simulates defense mechanisms against SQL injection attacks.
"""

import time
import re
import threading
from datetime import datetime

class SQLInjectionDefense:
    def __init__(self):
        self.attack_attempts = 0
        self.blocked_attempts = 0
        self.allowed_queries = 0
        self.lock = threading.Lock()

        # Common SQL injection patterns to detect
        self.sql_injection_patterns = [
            r"(?i)(\bunion\b.*\bselect\b)",  # UNION SELECT
            r"(?i)(\bselect\b.*\bfrom\b)",   # Basic SELECT
            r"(?i)(\binsert\b.*\binto\b)",   # INSERT
            r"(?i)(\bupdate\b.*\bset\b)",    # UPDATE
            r"(?i)(\bdelete\b.*\bfrom\b)",   # DELETE
            r"(?i)(\bdrop\b)",               # DROP
            r"(?i)(\balter\b)",              # ALTER
            r"(?i)(\bcreate\b)",             # CREATE
            r"(?i)(\bexec\b)",               # EXEC
            r"(?i)(\bwaitfor\b)",            # WAITFOR (SQL Server)
            r"(?i)(\bdbms_\w+\b)",           # Oracle PL/SQL
            r"('.*?--)",                     # Commenting out rest of query
            r"('.*?;.*)",                    # Statement termination
            r"(?i)(\bor\b\s*['\"]?\d+['\"]?\s*=)",   # OR '1'='1
            r"(?i)(\band\b\s*['\"]?\d+['\"]?\s*=)",  # AND '1'='1
        ]

        self.compiled_patterns = [re.compile(pattern) for pattern in self.sql_injection_patterns]

    def detect_sql_injection(self, input_string):
        """
        Check if the input string contains SQL injection patterns.
        :param input_string: User input to check.
        :return: True if SQL injection detected, False otherwise.
        """
        for pattern in self.compiled_patterns:
            if pattern.search(input_string):
                return True
        return False

    def sanitize_input(self, input_string):
        """
        Sanitize input by escaping special characters (simplified).
        In practice, use parameterized queries or ORM.
        :param input_string: User input.
        :return: Sanitized string.
        """
        # This is a very basic example. Real defense uses parameterized queries.
        # We'll just escape single quotes by doubling them.
        return input_string.replace("'", "''")

    def check_query(self, query, ip_address="unknown"):
        """
        Simulate checking a query for SQL injection.
        :param query: The query string to check.
        :param ip_address: Source IP for logging.
        :return: Tuple (is_safe, action_taken)
        """
        with self.lock:
            self.attack_attempts += 1

        is_injection = self.detect_sql_injection(query)

        if is_injection:
            with self.lock:
                self.blocked_attempts += 1
            print(f"[DEFENSE] Blocked SQL injection attempt from {ip_address}: {query[:50]}...")
            return False, "BLOCKED"
        else:
            with self.lock:
                self.allowed_queries += 1
            print(f"[DEFENSE] Allowed query from {ip_address}: {query[:50]}...")
            return True, "ALLOWED"

    def simulate_parameterized_query(self, user_input):
        """
        Simulate how a parameterized query would handle user input.
        :param user_input: User input that would be used as a parameter.
        :return: Safe query string.
        """
        # In a parameterized query, the user input is never interpreted as SQL.
        # We simulate this by showing the input would be treated as data.
        safe_query = f"SELECT * FROM users WHERE username = ? AND password = ?"
        print(f"[DEFENSE] Parameterized query would safely handle input: {user_input}")
        return safe_query

    def reset(self):
        """Zero all defense counters (used by the dashboard reset control)."""
        with self.lock:
            self.attack_attempts = 0
            self.blocked_attempts = 0
            self.allowed_queries = 0

    def get_stats(self):
        """Get defense statistics."""
        with self.lock:
            total = self.attack_attempts
            blocked = self.blocked_attempts
            allowed = self.allowed_queries
            return {
                'total_attempts': total,
                'blocked_attempts': blocked,
                'allowed_queries': allowed,
                'block_rate': (blocked / total * 100) if total > 0 else 0
            }

if __name__ == "__main__":
    # Example usage and testing
    defense = SQLInjectionDefense()

    # Test queries
    test_queries = [
        "SELECT * FROM users WHERE username = 'admin' AND password = 'pass'",  # Normal
        "SELECT * FROM users WHERE username = 'admin' OR '1'='1'",            # SQLi
        "SELECT * FROM users; DROP TABLE users; --",                         # SQLi
        "admin' --",                                                         # SQLi
        "normal input",                                                      # Normal
        "1; ALTER TABLE users ADD COLUMN backdoor VARCHAR(50);",             # DDL SQLi
    ]

    print("Testing SQL Injection Defense...")
    for query in test_queries:
        defense.check_query(query, ip_address="192.168.1.100")
        time.sleep(0.2)

    print("\nDefense Statistics:")
    stats = defense.get_stats()
    for key, value in stats.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.2f}%")
        else:
            print(f"  {key}: {value}")

    print("\nTesting parameterized query simulation:")
    defense.simulate_parameterized_query("admin' OR '1'='1")