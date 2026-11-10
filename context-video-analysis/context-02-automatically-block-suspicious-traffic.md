# Context 02: How to Automatically Block Suspicious Traffic in AWS
*Complete Video Masterclass Breakdown & Architecture Analysis*

---

## 📺 Video Metadata & Context Overview

| Field | Detail |
|---|---|
| **Context / Video Title** | How to Automatically Block Suspicious Traffic in AWS |
| **Topic Domain** | DevSecOps, Cloud Security Automation, Threat Intelligence, Edge Defense |
| **Target Roles** | Security Engineers, DevSecOps, Cloud Architects, Platform Engineers |
| **Prerequisites** | Familiarity with AWS WAF, VPC Flow Logs, and serverless automation |
| **Primary AWS Services** | AWS WAFv2, Amazon GuardDuty, Amazon EventBridge, AWS Lambda, Amazon DynamoDB |
| **Key Takeaway** | Manual IP blacklisting fails during high-velocity attacks. Event-driven pipelines dynamically push malicious IPs to WAF IP Sets with TTL expiration, dropping attacks at the edge before hitting compute. |

---

## ⏱️ Video Breakdown & Timestamp Agenda

- `00:00 - 03:00` | **The Attack Landscape**: Layer 7 DDoS, credential stuffing, SSH/RDP scans, and why manual ops fail.
- `03:00 - 07:15` | **Detection Engine Deep Dive**: How GuardDuty uses machine learning and threat feeds on VPC Flow Logs & DNS.
- `07:15 - 12:30` | **Automated Remediation Architecture**: The EventBridge $\rightarrow$ Lambda $\rightarrow$ WAF IP Set pipeline.
- `12:30 - 17:45` | **NACL vs WAF IP Set Comparison**: The 20-rule NACL hard ceiling vs 10,000 WAF IP capacity.
- `17:45 - 23:15` | **Hands-On Lambda Implementation**: Step-by-step code review of Python auto-blocker with LockToken handling.
- `23:15 - 27:30` | **Auto-Unblock with DynamoDB TTL**: Preventing permanent stale IP blacklists and collateral damage.
- `27:30 - 32:00` | **Production War Stories**: Race conditions on WAF LockTokens and blocking residential carrier NAT pools.
- `32:00 - End`   | **Senior Staff Interview Drill**: Handling distributed botnets, rate limiting vs IP blocking, and false positives.

---

## 🧠 Section 1: In-Depth Conceptual & Architectural Analysis

### 1.1 The Attack Vector & Threat Lifecycle
Modern threats against cloud workloads fall into two broad categories:
1. **Application-Layer (L7) Attacks**: Web scraping, SQL injection scanners, credential brute-forcing, and HTTP request floods.
2. **Infrastructure / Transport (L3/L4) Attacks**: Port sweeps, SYN floods, and unauthorized SSH/RDP brute-force connection attempts.

```mermaid
sequenceDiagram
    autonumber
    actor Attacker as Malicious Actor / Botnet
    participant Edge as AWS WAF (ALB / CloudFront)
    participant VPC as Target VPC Workload
    participant GD as Amazon GuardDuty
    participant EB as Amazon EventBridge
    participant Lambda as Remediation Lambda
    participant WAF_Set as WAF IP Set
    participant DDB as DynamoDB (TTL Ledger)

    Attacker->>Edge: Sends malicious payload / rapid port probe
    Edge->>VPC: Request reaches instance / VPC Flow Log generated
    VPC->>GD: Flow Logs & DNS logs ingested by GuardDuty
    GD->>EB: Emits High Severity Finding (e.g. UnauthorizedAccess:EC2/SSHBruteForce)
    EB->>Lambda: Invokes Lambda with Finding JSON payload
    Lambda->>WAF_Set: Fetches LockToken, appends Attacker IP/32
    Lambda->>DDB: Writes IP with 24-Hour Expiration Unix Epoch
    Note over Attacker,Edge: Subsequent Attacker Request
    Attacker->>Edge: Next HTTP Request
    Edge-->>Attacker: 403 Forbidden (Blocked at AWS Edge; Zero Compute Load)
```

---

### 1.2 The WAF IP Set vs. Network ACL Architectural Dilemma

Engineers often debate whether to block IPs in **Network ACLs (NACLs)** or **AWS WAF**:

```
Layer 4: Network ACL (Subnet Boundary)
├── Pros: Completely free; drops packets at the VPC border.
└── Cons: STRICT RULE LIMIT. AWS allows only 20 rules by default (max 40 with quota increase).
          Once 20 malicious IPs are added, your script crashes and fails!

Layer 7 / Edge: AWS WAF IP Set
├── Pros: Supports up to 10,000 IP addresses/CIDRs per IP Set.
│         Can return customizable JSON error responses or HTTP 403.
│         Runs at CloudFront Edge or Application Load Balancer.
└── Cons: Incurs AWS WAF evaluation charges.
```

> **Architectural Verdict**: Use **AWS WAF IP Sets** for automated dynamic blocking. Use NACLs only for static, broad CIDR blocks (e.g., blocking an entire unneeded `/16` geographic range).

---

## 🛠️ Section 2: Production Code & Implementation

### 2.1 Lambda Auto-Blocker Handler (`handler.py`)

```python
import os
import boto3
import json
from datetime import datetime, timezone

wafv2 = boto3.client('wafv2')
dynamodb = boto3.resource('dynamodb')

IP_SET_NAME = os.environ['WAF_IP_SET_NAME']
IP_SET_ID = os.environ['WAF_IP_SET_ID']
WAF_SCOPE = os.environ.get('WAF_SCOPE', 'REGIONAL')  # 'REGIONAL' or 'CLOUDFRONT'
TABLE_NAME = os.environ['BLOCK_LEDGER_TABLE']

def lambda_handler(event, context):
    print("Received event:", json.dumps(event))
    
    # 1. Parse Malicious IP from GuardDuty Finding
    try:
        detail = event['detail']
        remote_ip = (
            detail.get('service', {})
                  .get('action', {})
                  .get('networkConnectionAction', {})
                  .get('remoteIpDetails', {})
                  .get('ipAddressV4')
        )
        if not remote_ip:
            print("No IP found in networkConnectionAction. Checking portProbeAction...")
            remote_ip = (
                detail.get('service', {})
                      .get('action', {})
                      .get('portProbeAction', {})
                      .get('portProbeDetails', [{}])[0]
                      .get('remoteIpDetails', {})
                      .get('ipAddressV4')
            )
            
        if not remote_ip:
            print("Skipping: Could not extract target IP.")
            return {"status": "skipped", "reason": "No IP extracted"}
            
        target_cidr = f"{remote_ip}/32"
        print(f"Malicious IP identified: {target_cidr}")
        
        # 2. Get Current IP Set & LockToken (Handles Optimistic Locking)
        response = wafv2.get_ip_set(
            Name=IP_SET_NAME,
            Scope=WAF_SCOPE,
            Id=IP_SET_ID
        )
        current_ips = response['IPSet']['Addresses']
        lock_token = response['LockToken']
        
        # 3. Append to WAF IP Set if not already blocked
        if target_cidr not in current_ips:
            current_ips.append(target_cidr)
            wafv2.update_ip_set(
                Name=IP_SET_NAME,
                Scope=WAF_SCOPE,
                Id=IP_SET_ID,
                Addresses=current_ips,
                LockToken=lock_token
            )
            print(f"Successfully blocked {target_cidr} in WAF IP Set.")
            
            # 4. Save to DynamoDB with 24-Hour TTL
            ttl = int(datetime.now(timezone.utc).timestamp()) + (24 * 3600)
            table = dynamodb.Table(TABLE_NAME)
            table.put_item(
                Item={
                    'IP': target_cidr,
                    'BlockedAt': datetime.now(timezone.utc).isoformat(),
                    'ExpiresAt': ttl,
                    'FindingType': detail.get('type', 'Unknown'),
                    'Severity': str(detail.get('severity', 'High'))
                }
            )
        else:
            print(f"IP {target_cidr} already in block list.")

        return {"status": "success", "blocked_ip": target_cidr}

    except Exception as e:
        print(f"Auto-blocker failed: {str(e)}")
        raise e
```

---

## 💥 Section 3: Real-World War Stories & Edge Cases

### Incident 1: The WAF LockToken Concurrency Conflict
- **What happened**: During a distributed DDoS attack from 500 IPs simultaneously, GuardDuty generated 500 concurrent findings in 5 seconds.
- **The Failure**: 500 Lambda instances spun up in parallel. Instance 1 fetched `LockToken_A` and updated the WAF IP Set. Instance 2 attempted to update with `LockToken_A`, but WAF rejected it with `WAFOptimisticLockException` because the token had changed! 450 of the 500 IPs failed to be added.
- **The Fix**: Route GuardDuty events into a single **Amazon SQS FIFO Queue** or configure Lambda with **Reserved Concurrency = 1** (or batch IP updates every 10 seconds), ensuring serialized, collision-free WAF updates.

### Incident 2: The CGNAT Collateral Damage Outage
- **What happened**: A single smartphone infected with malware sent automated brute-force login requests from an IP belonging to a mobile carrier's Carrier-Grade NAT (CGNAT) gateway.
- **The Failure**: The auto-blocker added the carrier IP (`/32`) to the WAF blacklist. That single IP was shared by **40,000 legitimate mobile app users**, blocking all 40,000 customers from using the mobile application.
- **The Fix**: Never permanently block IPs. Always use **AWS WAF Rate-Based Rules** combined with CAPTCHA/Challenge actions for web requests, and implement automatic 12-hour or 24-hour DynamoDB TTL unblocking.

---

## 🎯 Section 4: Senior Staff Interview Drill

**Q1: Why should you prefer AWS WAF Rate-Based rules over custom Lambda-based IP blocking for HTTP Floods?**
> **Answer**: AWS WAF Rate-Based rules operate directly inside the AWS network edge hardware with zero cold-start delay, zero execution cost, and evaluate traffic natively over rolling 5-minute windows. A custom Lambda pipeline introduces latency (GuardDuty detection delay + EventBridge routing + Lambda execution) and costs compute fees. Custom Lambda pipelines should be reserved for cross-service intelligence (e.g. GuardDuty finding on an internal port scan triggering an edge WAF block).

**Q2: What is the purpose of the `LockToken` parameter in AWS WAFv2 API calls?**
> **Answer**: `LockToken` implements **Optimistic Concurrency Control**. Since multiple administrators, Terraform runs, or automated scripts might update an IP Set or WebACL concurrently, the LockToken ensures that an update will only succeed if the resource has not been altered since it was last read, preventing accidental race-condition overwrites.
