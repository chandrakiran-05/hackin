"""
Rate Limiter Defense Simulation
Simulates a rate limiting defense mechanism.
"""

import time
import threading
from collections import defaultdict
from datetime import datetime, timedelta

class RateLimiter:
    def __init__(self, max_requests=10, time_window=60):
        """
        Initialize rate limiter.
        :param max_requests: Maximum number of requests allowed in the time window.
        :param time_window: Time window in seconds.
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)  # IP -> list of timestamps
        self.blocked_ips = set()
        self.lock = threading.Lock()
        self._unblock_timers = {}  # IP -> Timer, so they can be cancelled on reset

    def is_allowed(self, ip):
        """
        Check if an IP is allowed to make a request.
        :param ip: Client IP address.
        :return: True if allowed, False if rate limited.
        """
        with self.lock:
            now = time.time()
            # Clean old requests
            if ip in self.requests:
                self.requests[ip] = [t for t in self.requests[ip] if now - t < self.time_window]
            else:
                self.requests[ip] = []

            # Check if IP is blocked
            if ip in self.blocked_ips:
                return False

            # Check if under limit
            if len(self.requests[ip]) < self.max_requests:
                self.requests[ip].append(now)
                return True
            else:
                # Block the IP for a period (e.g., 5 minutes)
                self.blocked_ips.add(ip)
                # Start a timer to unblock the IP after 5 minutes. Only one
                # timer per IP; keep a reference so reset() can cancel it.
                if ip not in self._unblock_timers:
                    unblock_timer = threading.Timer(300, self.unblock_ip, args=[ip])
                    unblock_timer.daemon = True
                    self._unblock_timers[ip] = unblock_timer
                    unblock_timer.start()
                print(f"[DEFENSE] IP {ip} blocked for exceeding rate limit ({len(self.requests[ip])} requests in {self.time_window}s)")
                return False

    def unblock_ip(self, ip):
        """Unblock an IP after the block period."""
        with self.lock:
            self._unblock_timers.pop(ip, None)
            if ip in self.blocked_ips:
                self.blocked_ips.remove(ip)
                print(f"[DEFENSE] IP {ip} unblocked")

    def blocked_ip_set(self):
        """Return a thread-safe snapshot of the currently blocked IPs."""
        with self.lock:
            return set(self.blocked_ips)

    def reset(self):
        """Clear all rate-limit state and cancel pending unblock timers."""
        with self.lock:
            for timer in self._unblock_timers.values():
                timer.cancel()
            self._unblock_timers.clear()
            self.requests.clear()
            self.blocked_ips.clear()

    def get_stats(self):
        """Get current statistics."""
        with self.lock:
            total_requests = sum(len(times) for times in self.requests.values())
            blocked_count = len(self.blocked_ips)
            return {
                'total_requests': total_requests,
                'blocked_ips': blocked_count,
                'active_ips': len(self.requests)
            }

if __name__ == "__main__":
    # Example usage and testing
    limiter = RateLimiter(max_requests=5, time_window=10)  # 5 requests per 10 seconds for testing

    # Simulate requests from different IPs
    test_ips = ["192.168.1.1", "192.168.1.2", "192.168.1.3"]

    print("Testing rate limiter (5 requests per 10 seconds)...")
    for i in range(15):
        ip = test_ips[i % len(test_ips)]
        allowed = limiter.is_allowed(ip)
        print(f"Request {i+1} from {ip}: {'ALLOWED' if allowed else 'BLOCKED'}")
        time.sleep(0.5)  # Wait 0.5 seconds between requests

    print("\nStatistics:", limiter.get_stats())
    # Wait a bit to see unblocking
    time.sleep(11)
    print("\nAfter waiting, statistics:", limiter.get_stats())