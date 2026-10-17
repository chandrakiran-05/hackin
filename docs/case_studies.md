# Banking Hack Case Studies

## 1. Bangladesh Bank Heist (2016)
- **What happened**: Attackers attempted to steal $1 billion from the Bangladesh Bank's account at the Federal Reserve Bank of New York. They successfully transferred $81 million before the attack was discovered.
- **How it was executed**: 
  - The attackers used malware to gain access to the bank's systems.
  - They sent fraudulent SWIFT messages requesting money transfers.
  - The transfers were routed to accounts in the Philippines and Sri Lanka, where the money was lauded.
- **Impact**: 
  - Direct financial loss of $81 million (with attempts for much more).
  - Highlighted vulnerabilities in the SWIFT interbank messaging system.
  - Led to increased security measures for SWIFT and central banks.
- **Lessons learned**: 
  - Importance of monitoring and validating SWIFT messages.
  - Need for multi-factor authentication and strict access controls for critical systems.
  - Value of anomaly detection in transaction patterns.

## 2. Capital One Data Breach (2019)
- **What happened**: A hacker accessed the personal data of over 100 million Capital One credit card applicants and customers.
- **How it was executed**:
  - The attacker exploited a misconfigured web application firewall (WAF) in Capital One's AWS infrastructure.
  - This allowed the attacker to gain access to sensitive data stored in S3 buckets.
  - The data included names, addresses, credit scores, and bank account numbers.
- **Impact**:
  - Exposure of 106 million records in the U.S. and 6 million in Canada.
  - Estimated costs of $100-$150 million for the bank.
  - Regulatory fines and legal settlements.
- **Lessons learned**:
  - Importance of proper cloud configuration and security (especially for AWS S3 buckets).
  - Need for regular security audits and penetration testing.
  - Value of encryption and tokenization for sensitive data.

## 3. Equifax Breach (2017) - Note: While not a bank, it's a major financial data breach
- **What happened**: Personal data of 147 million people was exposed, including Social Security numbers, birth dates, and addresses.
- **How it was executed**:
  - Attackers exploited a known vulnerability in Apache Struts (CVE-2017-5638) that Equifax had not patched.
  - The breach went undetected for several months.
- **Impact**:
  - One of the largest data breaches in history.
  - Equifax paid up to $700 million in settlements.
  - Severe reputational damage.
- **Lessons learned**:
  - Critical importance of timely patching of known vulnerabilities.
  - Need for robust vulnerability management and scanning.
  - Value of network segmentation to limit attacker movement.

## 4. JPMorgan Chase Breach (2014)
- **What happened**: Compromise of data affecting 76 million households and 7 million small businesses.
- **How it was executed**:
  - Attackers gained access through a vulnerability in a JPMorgan Chase website.
  - They then moved laterally within the network to access customer data.
  - The breach was not detected for about two months.
- **Impact**:
  - Exposure of names, addresses, phone numbers, and email addresses (but no account numbers or passwords, according to the bank).
  - Increased focus on cybersecurity in the financial sector.
- **Lessons learned**:
  - Importance of multi-factor authentication for all remote access.
  - Need for network segmentation and monitoring for lateral movement.
  - Value of timely incident response and breach disclosure.

## 5. Banco Central do Brasil (2016) - ATM Jackpotting via Malware
- **What happened**: Criminals used malware to force ATMs to dispense cash without using cards.
- **How it was executed**:
  - Malware was introduced via USB devices or network connections to the ATMs.
  - The malware allowed attackers to control the cash dispenser mechanism.
  - Multiple ATMs were targeted across Brazil.
- **Impact**:
  - Theft of millions of Brazilian reais (local currency).
  - Highlighted the vulnerability of ATMs to logical attacks.
- **Lessons learned**:
  - Need for physical security and monitoring of ATMs.
  - Importance of application whitelisting on ATM systems.
  - Value of transaction anomaly detection to spot unusual cash dispense patterns.

## 6. SOCAR (Société Générale) - Insider Trading via Hacking (2008)
- **What happened**: A trader at Société Générale (Kerviel) concealed unauthorized and fraudulent trades, leading to losses of €4.9 billion.
- **How it was executed**:
  - Not a traditional external hack, but an insider who abused his access to the trading systems.
  - He used fake transactions to hide the true extent of his positions.
  - The fraud was only discovered when the losses became too large to conceal.
- **Impact**:
  - One of the largest trading losses in history due to rogue trading.
  - Led to the arrest and conviction of the trader.
  - Forced the bank to seek a government bailout.
- **Lessons learned**:
  - Importance of segregation of duties and independent checks.
  - Need for real-time monitoring of trading positions and anomalies.
  - Value of strict access controls and regular audits of employee activities.

These case studies illustrate various attack vectors: external hacking (exploiting vulnerabilities, misconfigurations, phishing), insider threats, and specific techniques like ATM jackpotting. They emphasize the need for a multi-layered security approach in banking.