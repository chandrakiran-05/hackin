"""
DDoS Attack Simulation
Simulates various types of DDoS attacks for educational purposes.
"""

import time
import random
import threading
from datetime import datetime

class DDoSSimulator:
    def __init__(self, target_ip="127.0.0.1", target_port=80):
        self.target_ip = target_ip
        self.target_port = target_port
        self.attack_active = False
        self.attack_threads = []
        self.packets_sent = 0

    def http_flood(self, duration=10):
        """Simulate HTTP flood attack"""
        print(f"[ATTACK] Starting HTTP flood on {self.target_ip}:{self.target_port}")
        end_time = time.time() + duration

        while time.time() < end_time and self.attack_active:
            # Simulate sending HTTP request
            self.packets_sent += 1
            if self.packets_sent % 100 == 0:
                print(f"[ATTACK] HTTP flood: {self.packets_sent} requests sent")
            time.sleep(0.01)  # Simulate network delay

        print(f"[ATTACK] HTTP flood completed. Total requests: {self.packets_sent}")

    def udp_flood(self, duration=10):
        """Simulate UDP flood attack"""
        print(f"[ATTACK] Starting UDP flood on {self.target_ip}:{self.target_port}")
        packets = 0
        end_time = time.time() + duration

        while time.time() < end_time and self.attack_active:
            # Simulate sending UDP packet
            packets += 1
            self.packets_sent += 1
            if packets % 1000 == 0:
                print(f"[ATTACK] UDP flood: {packets} packets sent")
            time.sleep(0.001)  # UDP is typically faster

        print(f"[ATTACK] UDP flood completed. Total UDP packets: {packets}")

    def syn_flood(self, duration=10):
        """Simulate SYN flood attack"""
        print(f"[ATTACK] Starting SYN flood on {self.target_ip}:{self.target_port}")
        connections = 0
        end_time = time.time() + duration

        while time.time() < end_time and self.attack_active:
            # Simulate sending SYN packet (half-open connection)
            connections += 1
            self.packets_sent += 1
            if connections % 500 == 0:
                print(f"[ATTACK] SYN flood: {connections} SYN packets sent")
            time.sleep(0.002)

        print(f"[ATTACK] SYN flood completed. Total SYN packets: {connections}")

    def start_attack(self, attack_type="http", duration=10, threads=5):
        """Start DDoS attack with specified type"""
        self.attack_active = True
        self.packets_sent = 0

        print(f"[INFO] Starting {attack_type.upper()} flood attack with {threads} threads for {duration} seconds")

        attack_methods = {
            "http": self.http_flood,
            "udp": self.udp_flood,
            "syn": self.syn_flood
        }

        method = attack_methods.get(attack_type.lower(), self.http_flood)

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
        print(f"[INFO] Attack finished. Total packets simulated: {self.packets_sent}")

    def stop_attack(self):
        """Stop the ongoing attack"""
        self.attack_active = False
        print("[INFO] Attack stopped by user")

if __name__ == "__main__":
    # Example usage
    simulator = DDoSSimulator()
    print("DDoS Attack Simulator")
    print("1. HTTP Flood")
    print("2. UDP Flood")
    print("3. SYN Flood")

    choice = input("Select attack type (1-3): ").strip()
    attack_type = {"1": "http", "2": "udp", "3": "syn"}.get(choice, "http")

    duration = int(input("Enter attack duration (seconds): ") or "10")
    threads = int(input("Enter number of threads: ") or "5")

    try:
        simulator.start_attack(attack_type, duration, threads)
    except KeyboardInterrupt:
        simulator.stop_attack()