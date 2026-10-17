# Banking Security Simulation System

This project provides a simulation environment to demonstrate various banking attack types and defense mechanisms. It includes:

1. **Attack Simulations**:
   - DDoS attacks (HTTP, UDP, SYN flood)
   - SQL Injection attacks (including DDL hijacking)
   
2. **Defense Mechanisms**:
   - Rate limiting
   - SQL injection detection and prevention

3. **Live Dashboard**:
   - Web-based interface to visualize attacks and defenses in real-time
   - Live logs and statistics

## Project Structure

```
.
├── docs/
│   ├── attack_types.md        # Description of various attack types
│   └── case_studies.md        # Real-world bank hack case studies
├── simulation/
│   ├── attacks/
│   │   ├── ddos_simulation.py     # DDoS attack simulation
│   │   └── sql_injection_simulation.py  # SQL injection simulation
│   └── defenses/
│       ├── rate_limiter.py        # Rate limiting defense
│       └── sql_injection_defense.py   # SQL injection defense
├── dashboard/
│   ├── app.py                   # Flask web application
│   └── templates/
│       └── index.html           # Dashboard HTML template
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

## Installation

1. **Clone or download this repository**
2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Running the Simulation Dashboard

1. **Start the Flask application**:
   ```bash
   python dashboard/app.py
   ```

2. **Open your web browser** and navigate to:
   ```
   http://localhost:5001
   ```

### Using the Dashboard

The dashboard provides controls to:
- **Start DDoS attacks** (HTTP, UDP, or SYN flood) with configurable duration and thread count
- **Start SQL injection attacks** (basic, DDL hijacking, or UNION-based) with configurable duration and thread count
- **Test defense mechanisms**:
  - Rate limiting simulation
  - SQL injection detection simulation

### Features

- **Real-time visualization** of attack and defense activities
- **Live logs** showing attack attempts, successes, and blocks
- **Statistics panel** showing:
  - Number of DDoS packets sent
  - SQL injection attempts and blocks
  - Number of IPs rate-limited
- **Attack controls** to start/stop different types of attacks
- **Defense testing** to see how protections work

## Educational Purpose

This simulation is designed for **educational and demonstration purposes only**. It:
- Does not perform actual attacks on real systems
- Uses simulated network traffic and requests
- Is safe to run on localhost
- Helps understand how attacks work and how defenses mitigate them

## Attack Types Covered

See `docs/attack_types.md` for detailed descriptions of:
- DDoS attacks
- SQL Injection (including DDL hijacking)
- Ransomware
- Phishing
- Insider threats
- Man-in-the-Middle attacks
- ATM jackpotting
- Credential stuffing
- Supply chain attacks

## Case Studies

See `docs/case_studies.md` for real-world examples of:
- Bangladesh Bank Heist (2016)
- Capital One Data Breach (2019)
- Equifax Breach (2017)
- JPMorgan Chase Breach (2014)
- Banco Central do Brasil ATM Jackpotting (2016)
- SOCAR Insider Trading (2008)

## Customization

You can extend this simulation by:
1. Adding more attack types in the `simulation/attacks/` directory
2. Adding more defense mechanisms in the `simulation/defenses/` directory
3. Enhancing the dashboard with more visualizations
4. Integrating with actual security tools (for advanced users)

## Safety Notice

This simulation is intended to run in a **controlled, isolated environment** (localhost). 
Do not point the simulations at any real systems or networks without explicit authorization.

---

**Generated with [Claude Code](https://claude.com/claude-code)**