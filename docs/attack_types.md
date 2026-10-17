# Banking Attack Types

## 1. DDoS (Distributed Denial of Service)
- **Description**: Overwhelming a target's network or servers with a flood of internet traffic to disrupt normal service.
- **Mechanism**: Uses multiple compromised systems (botnet) to generate massive traffic volumes.
- **Impact**: Service downtime, financial loss, reputational damage.
- **Defense**: Rate limiting, traffic scrubbing, CDN, DDoS protection services.

## 2. SQL Injection
- **Description**: Injecting malicious SQL code into input fields to manipulate database queries.
- **Mechanism**: Exploits vulnerabilities in web application code that does not properly sanitize user input.
- **Impact**: Unauthorized access to sensitive data, data manipulation, potential for complete database compromise.
- **Defense**: Input validation, parameterized queries, web application firewalls (WAF).

## 3. DDL Hijacking (Data Definition Language Hijacking)
- **Description**: Attack where an attacker modifies database structure (tables, indexes, etc.) by injecting DDL statements.
- **Mechanism**: Similar to SQL injection but targets DDL commands (CREATE, ALTER, DROP) to change database schema.
- **Impact**: Data corruption, application failure, potential for data theft by creating backdoors.
- **Defense**: Principle of least privilege for database users, input validation, monitoring for unusual DDL statements.

## 4. Ransomware
- **Description**: Malware that encrypts victim's data and demands payment for decryption key.
- **Mechanism**: Often delivered via phishing emails or exploiting vulnerabilities; encrypts files and spreads across network.
- **Impact**: Data loss, operational disruption, financial extortion.
- **Defense**: Regular backups, email filtering, endpoint protection, network segmentation.

## 5. Phishing
- **Description**: Fraudulent attempt to obtain sensitive information by disguising as a trustworthy entity.
- **Mechanism**: Fake emails, websites, or messages that trick users into revealing credentials or installing malware.
- **Impact**: Credential theft, financial fraud, malware installation.
- **Defense**: Employee training, email authentication (DMARC, SPF, DKIM), anti-phishing tools.

## 6. Insider Threats
- **Description**: Malicious or negligent actions by employees, contractors, or business partners.
- **Mechanism**: Abuse of legitimate access to steal data, sabotage systems, or facilitate external attacks.
- **Impact**: Data breaches, financial loss, reputational damage.
- **Defense**: Access controls, monitoring user behavior, segregation of duties, regular audits.

## 7. Man-in-the-Middle (MitM) Attacks
- **Description**: Attacker secretly relays and possibly alters communication between two parties.
- **Mechanism**: Exploits unsecured networks (e.g., public Wi-Fi) or compromised routers to intercept data.
- **Impact**: Credential theft, session hijacking, data manipulation.
- **Defense**: Encryption (TLS/SSL), VPNs, certificate pinning, network monitoring.

## 8. ATM Jackpotting
- **Description**: Physical or logical attack on ATMs to dispense cash illegally.
- **Mechanism**: Malware installation via USB or network to control ATM cash dispenser.
- **Impact**: Direct cash theft.
- **Defense**: Physical security, ATM software whitelisting, anomaly detection in transactions.

## 9. Credential Stuffing
- **Description**: Using stolen username/password pairs to gain unauthorized access to accounts.
- **Mechanism**: Automated login attempts using credentials from data breaches.
- **Impact**: Account takeover, fraud, data theft.
- **Defense**: Multi-factor authentication (MFA), rate limiting, bot detection, passwordless authentication.

## 10. Supply Chain Attacks
- **Description**: Infiltrating a system through third-party vendors or software updates.
- **Mechanism**: Compromising a trusted supplier to distribute malicious code or gain access.
- **Impact**: Widespread compromise, data breaches, operational disruption.
- **Defense**: Vendor risk management, code signing, software bill of materials (SBOM), network segmentation.