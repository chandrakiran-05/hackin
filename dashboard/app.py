"""
Security Simulation Dashboard
A Flask web application to visualize attack and defense simulations.
"""

from flask import Flask, render_template, jsonify, request
import json
import os
import sys
import threading
import time

# Ensure the project root is on sys.path so this script works
# when run directly as `python dashboard/app.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulation.attacks.ddos_simulation import DDoSSimulator
from simulation.attacks.sql_injection_simulation import SQLInjectionSimulator
from simulation.defenses.rate_limiter import RateLimiter
from simulation.defenses.sql_injection_defense import SQLInjectionDefense

app = Flask(__name__)

# Global instances for simulation tracking
ddos_simulator = DDoSSimulator()
sql_simulator = SQLInjectionSimulator()
rate_limiter = RateLimiter(max_requests=10, time_window=60)
sql_defense = SQLInjectionDefense()

# Simulation state
simulation_state = {
    'ddos_active': False,
    'sql_active': False,
    'stats': {
        'ddos_packets': 0,
        'sql_attempts': 0,
        'blocked_attempts': 0,
        'rate_limited_ips': 0
    },
    'logs': [],
    'attack_types': [],
    'defense_actions': []
}

def add_log(message, level="INFO"):
    """Add a log entry with timestamp."""
    timestamp = time.strftime("%H:%M:%S")
    simulation_state['logs'].append({
        'timestamp': timestamp,
        'message': message,
        'level': level
    })
    # Keep only last 100 logs
    if len(simulation_state['logs']) > 100:
        simulation_state['logs'] = simulation_state['logs'][-100:]

@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('index.html')

@app.route('/start_ddos', methods=['POST'])
def start_ddos():
    """Start DDoS attack simulation."""
    data = request.json
    attack_type = data.get('type', 'http')
    duration = data.get('duration', 10)
    threads = data.get('threads', 5)

    def run_ddos():
        simulation_state['ddos_active'] = True
        add_log(f"Starting {attack_type.upper()} DDoS attack with {threads} threads for {duration}s", "ATTACK")

        # Override the simulator's print to capture logs
        original_print = print
        def custom_print(*args, **kwargs):
            message = ' '.join(str(arg) for arg in args)
            if "[ATTACK]" in message or "[INFO]" in message:
                add_log(message.replace("[ATTACK]", "").replace("[INFO]", "").strip())
            original_print(*args, **kwargs)

        # Temporarily replace print
        import builtins
        builtins.print = custom_print

        try:
            ddos_simulator.start_attack(attack_type, duration, threads)
            simulation_state['stats']['ddos_packets'] = ddos_simulator.packets_sent
        finally:
            # Restore print
            builtins.print = original_print
            simulation_state['ddos_active'] = False
            add_log("DDoS attack finished", "INFO")

    thread = threading.Thread(target=run_ddos)
    thread.daemon = True
    thread.start()

    return jsonify({'status': 'started', 'message': f'DDoS {attack_type} attack started'})

@app.route('/start_sql', methods=['POST'])
def start_sql():
    """Start SQL injection attack simulation."""
    data = request.json
    attack_type = data.get('type', 'basic')
    duration = data.get('duration', 10)
    threads = data.get('threads', 3)

    def run_sql():
        simulation_state['sql_active'] = True
        add_log(f"Starting {attack_type} SQL injection attack with {threads} threads for {duration}s", "ATTACK")

        # Override the simulator's print to capture logs
        original_print = print
        def custom_print(*args, **kwargs):
            message = ' '.join(str(arg) for arg in args)
            if "[ATTACK]" in message or "[INFO]" in message:
                clean_msg = message.replace("[ATTACK]", "").replace("[INFO]", "").strip()
                if "SUCCESS" in clean_msg or "FAILED" in clean_msg:
                    add_log(clean_msg, "ATTACK_DETAIL")
                else:
                    add_log(clean_msg)
            original_print(*args, **kwargs)

        # Temporarily replace print
        import builtins
        builtins.print = custom_print

        try:
            sql_simulator.start_attack(attack_type, duration, threads)
            simulation_state['stats']['sql_attempts'] = sql_simulator.queries_attempted
        finally:
            # Restore print
            builtins.print = original_print
            simulation_state['sql_active'] = False
            add_log("SQL injection attack finished", "INFO")

    thread = threading.Thread(target=run_sql)
    thread.daemon = True
    thread.start()

    return jsonify({'status': 'started', 'message': f'SQL {attack_type} attack started'})

@app.route('/test_defense', methods=['POST'])
def test_defense():
    """Test defense mechanisms."""
    data = request.json
    test_type = data.get('type', 'rate_limit')

    if test_type == 'rate_limit':
        ip = data.get('ip', '192.168.1.100')
        # Simulate multiple requests to trigger rate limiting
        results = []
        for i in range(15):
            allowed = rate_limiter.is_allowed(ip)
            results.append({'request': i+1, 'allowed': allowed, 'ip': ip})
            if not allowed:
                add_log(f"Rate limiter blocked IP {ip} (request {i+1})", "DEFENSE")
            time.sleep(0.1)

        simulation_state['stats']['rate_limited_ips'] = len(rate_limiter.blocked_ips)
        return jsonify({
            'status': 'completed',
            'message': f'Rate limit test completed for IP {ip}',
            'results': results,
            'stats': rate_limiter.get_stats()
        })

    elif test_type == 'sql_injection':
        query = data.get('query', "admin' OR '1'='1")
        ip = data.get('ip', '192.168.1.100')
        is_safe, action = sql_defense.check_query(query, ip)

        if action == "BLOCKED":
            add_log(f"SQL injection blocked: {query[:30]}...", "DEFENSE")
        else:
            add_log(f"Query allowed: {query[:30]}...", "DEFENSE")

        return jsonify({
            'status': 'completed',
            'message': f'SQL injection test {"blocked" if not is_safe else "allowed"}',
            'query': query,
            'safe': is_safe,
            'action': action,
            'stats': sql_defense.get_stats()
        })

    return jsonify({'status': 'error', 'message': 'Invalid test type'})

@app.route('/get_status')
def get_status():
    """Get current simulation status."""
    return jsonify({
        'ddos_active': simulation_state['ddos_active'],
        'sql_active': simulation_state['sql_active'],
        'stats': simulation_state['stats'],
        'logs': simulation_state['logs'][-10:],  # Last 10 logs
        'defense_stats': {
            'rate_limiter': rate_limiter.get_stats(),
            'sql_defense': sql_defense.get_stats()
        }
    })

@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    """Clear simulation logs."""
    simulation_state['logs'] = []
    return jsonify({'status': 'cleared'})

if __name__ == '__main__':
    add_log("Security Simulation Dashboard started", "INFO")
    app.run(debug=True, host='0.0.0.0', port=5001)