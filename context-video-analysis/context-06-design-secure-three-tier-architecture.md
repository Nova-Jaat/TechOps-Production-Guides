# Context 06: How To Design a Secure Three-Tier Architecture on AWS
*Complete Video Masterclass Breakdown & Architecture Analysis*

---

## 📺 Video Metadata & Context Overview

| Field | Detail |
|---|---|
| **Context / Video Title** | How To Design a Secure Three Tier Architecture on AWS |
| **Topic Domain** | Enterprise Cloud Architecture, High Availability, Defense-in-Depth, Compliance |
| **Target Roles** | Enterprise Architects, Solutions Architects, Lead Cloud Engineers, DevOps Leads |
| **Prerequisites** | VPC networking, Auto Scaling, Relational Databases, Load Balancers |
| **Primary AWS Services** | Application Load Balancer, Amazon EC2 / ECS, Amazon RDS Multi-AZ, AWS Secrets Manager, AWS SSM |
| **Key Takeaway** | A production three-tier architecture guarantees strict network isolation. Workloads never expose public IPs, database credentials rotate automatically, and administration occurs without open SSH/RDP ports via AWS Systems Manager. |

---

## ⏱️ Video Breakdown & Timestamp Agenda

- `00:00 - 03:30` | **The Philosophy of 3-Tier Design**: Separation of concerns, fault domains, and regulatory compliance (PCI-DSS, SOC2).
- `03:30 - 08:15` | **Tier 1: Presentation & Web Edge**: CloudFront CDN, AWS WAF, and public Application Load Balancers.
- `08:15 - 14:00` | **Tier 2: Application Logic**: Private subnets, container tasks / Auto Scaling Groups, and NAT Gateway routing.
- `14:00 - 19:30` | **Tier 3: Database & State Isolation**: Zero-egress isolated subnets, RDS Multi-AZ synchronous replication, and ElastiCache.
- `19:30 - 24:45` | **Eliminating Bastion Hosts & SSH Keys**: Bastionless server administration using AWS Systems Manager (SSM) Session Manager.
- `24:45 - 29:30` | **Automated Secrets Rotation**: AWS Secrets Manager integration with Lambda for zero-downtime DB password cycling.
- `29:30 - 34:00` | **Production War Stories**: The accidental public DB subnet disaster and the failed Multi-AZ failover test.
- `34:00 - End`   | **Senior Staff Interview Drill**: RPO vs RTO in Multi-AZ vs Aurora Global Database, Cross-AZ data transfer optimization.

---

## 🧠 Section 1: In-Depth Conceptual & Architectural Analysis

### 1.1 Complete Enterprise Topology Diagram

```mermaid
flowchart TD
    Users((Internet Users))
    
    subgraph EdgePerimeter["Edge Perimeter"]
        R53["Amazon Route 53 (DNS / Latency Routing)"]
        CF["Amazon CloudFront (Edge CDN)"]
        WAF["AWS WAF (OWASP Top 10 + Rate Limiting)"]
        R53 --> CF --> WAF
    end

    Users --> R53

    subgraph AWS_VPC["Amazon VPC (10.0.0.0/16)"]
        subgraph AZ_1["Availability Zone: us-east-1a"]
            direction TB
            subgraph Web1["Tier 1: Public Web Subnet (10.0.1.0/24)"]
                ALB_1["Application Load Balancer Node A"]
                NAT_1["NAT Gateway A (Elastic IP A)"]
            end
            subgraph App1["Tier 2: Private App Subnet (10.0.11.0/24)"]
                ASG_1["App Server Instances / ECS Tasks A"]
            end
            subgraph Data1["Tier 3: Isolated Data Subnet (10.0.21.0/24)"]
                RDS_Primary[("Amazon RDS Primary (Writer)<br/>KMS Encrypted Storage")]
                Redis_1[("ElastiCache Redis Primary")]
            end
        end

        subgraph AZ_2["Availability Zone: us-east-1b"]
            direction TB
            subgraph Web2["Tier 1: Public Web Subnet (10.0.2.0/24)"]
                ALB_2["Application Load Balancer Node B"]
                NAT_2["NAT Gateway B (Elastic IP B)"]
            end
            subgraph App2["Tier 2: Private App Subnet (10.0.12.0/24)"]
                ASG_2["App Server Instances / ECS Tasks B"]
            end
            subgraph Data2["Tier 3: Isolated Data Subnet (10.0.22.0/24)"]
                RDS_Standby[("Amazon RDS Standby (Synchronous)<br/>Automated DNS Failover")]
                Redis_2[("ElastiCache Redis Replica")]
            end
        end

        IGW["Internet Gateway"]
    end

    WAF --> ALB_1 & ALB_2
    ALB_1 & ALB_2 --> ASG_1 & ASG_2
    ASG_1 & ASG_2 --> RDS_Primary
    ASG_1 & ASG_2 --> Redis_1
    RDS_Primary -.->|Synchronous Storage Replication (RPO=0)| RDS_Standby
    Redis_1 -.->|Asynchronous Replication| Redis_2
    
    ASG_1 --> NAT_1 --> IGW
    ASG_2 --> NAT_2 --> IGW
```

---

### 1.2 Strict Tier-by-Tier Security Isolation Matrix

| Layer | Subnet Type | Default Route (`0.0.0.0/0`) | Public IP? | Permitted Inbound Traffic |
|---|---|---|---|---|
| **Tier 1: Web** | Public | Targets **Internet Gateway** (`igw-xxxx`) | Yes (ALB ENIs) | Port 443 from CloudFront or Internet |
| **Tier 2: App** | Private | Targets **NAT Gateway** in same AZ (`nat-xxxx`) | **No (Strictly Private)** | Port 8080 strictly from `sg-web-alb` |
| **Tier 3: Data** | Isolated | **NONE** (Local VPC route only) | **No (Strictly Private)** | Port 5432 strictly from `sg-app-compute` |

---

### 1.3 Bastionless Administration: AWS Systems Manager Session Manager

Traditional architectures deployed an EC2 "Bastion Host" in the public subnet, opening port 22 (SSH) to allow developers to access backend instances.
**Why Bastion Hosts are an Anti-Pattern in 2026:**
1. Attack surface: Port 22 is constantly targeted by automated brute-force botnets.
2. Key sprawl: Private SSH keys leak in developer Slack channels or laptops.
3. Lack of auditability: Hard to monitor what commands an engineer executed.

**The Modern Solution: AWS SSM Session Manager**
- Instances run the SSM Agent.
- Instances only need outbound HTTPS (port 443) to AWS Systems Manager endpoints (via NAT Gateway or PrivateLink Interface Endpoints).
- **Zero inbound ports are open in the Security Group**.
- Authentication is governed by **AWS IAM** (with MFA enforcement).
- Every keystroke and session command is recorded to an encrypted **Amazon S3 bucket** and **CloudWatch Logs** for compliance auditing.

---

## 🛠️ Section 2: Production Code & Implementation

```hcl
# 1. Isolated Subnet Group for Amazon RDS
resource "aws_db_subnet_group" "rds_subnets" {
  name       = "prod-isolated-rds-subnet-group"
  subnet_ids = [aws_subnet.isolated_1a.id, aws_subnet.isolated_1b.id]

  tags = {
    Name = "Production Database Subnet Group"
  }
}

# 2. Production Multi-AZ RDS PostgreSQL Instance
resource "aws_db_instance" "postgres" {
  identifier            = "prod-core-db"
  allocated_storage     = 100
  max_allocated_storage = 1000  # Storage Auto-Scaling up to 1TB
  storage_type          = "gp3"
  engine                = "postgres"
  engine_version        = "16.1"
  instance_class        = "db.r6g.xlarge"
  multi_az              = true   # Synchronous High Availability
  
  db_subnet_group_name   = aws_db_subnet_group.rds_subnets.name
  vpc_security_group_ids = [aws_security_group.db_sg.id]
  
  # Security Controls
  storage_encrypted = true
  kms_key_id        = aws_kms_key.db_key.arn
  publicly_accessible = false   # Impossible to reach from the internet
  skip_final_snapshot = false
  final_snapshot_identifier = "prod-core-db-final-snapshot"

  # Integration with AWS Secrets Manager
  manage_master_user_password   = true # AWS natively manages and rotates the master password!
  master_user_secret_kms_key_id = aws_kms_key.secrets_key.arn
  username                      = "dbadmin"

  tags = { Environment = "production" }
}
```

---

## 💥 Section 3: Real-World War Stories & Edge Cases

### Incident 1: The Accidental Public Subnet Flag
- **What happened**: A DevOps engineer automated database provisioning using a script that had `map_public_ip_on_launch = true` inherited from a public subnet module.
- **The Failure**: The RDS instance was launched into a subnet attached to an Internet Gateway with `publicly_accessible = true`. Security scanners identified the port 5432 listener within 14 minutes, initiating thousands of password brute-force queries.
- **The Fix**: Enforce AWS Organizations **Service Control Policies (SCPs)** and AWS Config Rules (`rds-instance-public-access-check`) that automatically terminate or alter any RDS instance configured with public access.

### Incident 2: The Cascading Connection Storm on Multi-AZ Failover
- **What happened**: During a routine AWS maintenance event, the primary database instance in AZ-1 experienced a hardware fault. RDS automatically flipped DNS to the standby in AZ-2.
- **The Failure**: When the database came back online 70 seconds later, 400 application containers simultaneously reconnected, opening 12,000 PostgreSQL client connections at once. The database CPU instantly spiked to 100%, deadlocking the database and extending the outage by 45 minutes.
- **The Fix**: Deploy **Amazon RDS Proxy** between the Application Tier and the Database Tier. RDS Proxy pools and multiplexes connections, absorbing connection storms and reducing failover recovery times by **up to 66%**.

---

## 🎯 Section 4: Senior Staff Interview Drill

**Q1: What is the Recovery Point Objective (RPO) and Recovery Time Objective (RTO) of Amazon RDS Multi-AZ synchronous replication?**
> **Answer**:
> - **RPO = 0**: Because replication between the primary and standby instance is **synchronous**, a write is only acknowledged to the application once it is committed to both AZ storage layers. No committed data is lost during an AZ outage.
> - **RTO = 60–120 seconds**: The time required for RDS automated health checks to detect the node failure, promote the standby storage volume to master, and update the RDS endpoint CNAME DNS record.

**Q2: Why should you avoid putting an internal Application Load Balancer between Tier 2 (Application) and Tier 3 (Database)?**
> **Answer**: ALBs operate at Layer 7 (HTTP/HTTPS) and do not support arbitrary TCP protocols like PostgreSQL (5432) or MySQL (3306). Placing a load balancer in front of a relational database is an anti-pattern. Instead, application compute connects directly to the RDS Cluster Endpoint (for writes) or Reader Endpoint (for load-balanced read replicas), or connects through an **Amazon RDS Proxy** / **Network Load Balancer (NLB)** operating at Layer 4.
