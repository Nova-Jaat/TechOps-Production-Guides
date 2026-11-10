# Cloud Disaster Recovery (DR) Strategies: RTO, RPO & Architecture Blueprints

## 1. Context & The Core Metrics: RTO and RPO

Disaster Recovery in cloud engineering revolves around two non-negotiable business metrics:

```
[ Last Valid Backup / Sync ] <------- RPO -------> [ Disaster Occurs ] <------- RTO -------> [ System Restored ]
                                (Data Loss Window)                       (Downtime Window)
```

1. **RPO (Recovery Point Objective)**: The maximum acceptable data loss measured in time. It answers: *"How much transactional data can the business afford to lose between the last backup and the moment of catastrophic failure?"*
2. **RTO (Recovery Time Objective)**: The maximum acceptable downtime before systems are restored to operational status. It answers: *"How long can the application be down before business viability is threatened?"*

---

## 2. The 4 Cloud Disaster Recovery Strategies

AWS defines four primary DR architectures on a spectrum balancing **Cost** against **Recovery Speed**:

```mermaid
quadrantChart
    title Disaster Recovery Cost vs Recovery Speed Trade-Off
    x-axis Low Cost --> High Cost
    y-axis Slow Recovery (Hours/Days) --> Instant Recovery (Seconds/Real-Time)
    quadrant-1 Multi-Region Active-Active
    quadrant-2 Warm Standby
    quadrant-3 Backup & Restore
    quadrant-4 Pilot Light
    Backup & Restore: [0.15, 0.15]
    Pilot Light: [0.4, 0.45]
    Warm Standby: [0.7, 0.75]
    Multi-Region Active-Active: [0.95, 0.95]
```

---

## 3. Deep Dive into the 4 DR Architecture Blueprints

### Strategy 1: Backup & Restore
- **RTO**: 12 to 24+ Hours
- **RPO**: 1 to 24 Hours
- **Cost**: 💲 (Cheapest)
- **Mechanics**: Data is regularly backed up using AWS Backup, S3 Cross-Region Replication (CRR), or database snapshots exported to a secondary AWS region. No compute resources run in the recovery region.
- **Failover**: In a disaster, infrastructure is rebuilt from scratch via Terraform / CloudFormation, and databases are restored from snapshots.
- **Best For**: Internal back-office tools, non-critical reporting databases, development environments.

---

### Strategy 2: Pilot Light
- **RTO**: 10 to 30 Minutes
- **RPO**: Sub-minute / Real-Time
- **Cost**: 💲💲
- **Mechanics**: The core data layer is kept **live and continuously replicated** in the secondary region (e.g., Aurora Global Database read replica or DynamoDB Global Table). Compute infrastructure (EKS, EC2, ALB) is **not running** or kept at minimal standby (e.g., ASG min=0).
- **Failover**: Route 53 health check detects primary outage $\rightarrow$ Secondary Aurora replica is promoted to standalone master $\rightarrow$ Terraform or Auto Scaling rapidly scales compute instances from 0 to 50 $\rightarrow$ Traffic cutover.

```mermaid
flowchart TD
    subgraph Primary["Primary Region (us-east-1) - ACTIVE"]
        ALB1["Application Load Balancer"] --> EC2_1["EC2 Auto Scaling Fleet (100 Instances)"]
        EC2_1 --> RDS1[("Aurora Primary (Writer)")]
    end

    subgraph Secondary["Secondary Region (us-west-2) - PILOT LIGHT"]
        RDS2[("Aurora Global Replica (Reader)\nContinuously Synced (< 1s lag)")]
        ASG2["EC2 ASG (Scale: min=0, max=100)\nAMI pre-baked & ready"]
    end

    RDS1 -->|Storage Engine Asynchronous Replication| RDS2
    
    Note over Secondary: On Disaster: Promote RDS2 to Writer & Scale ASG2 from 0 to 100
```

---

### Strategy 3: Warm Standby
- **RTO**: Under 5 Minutes
- **RPO**: Real-Time (Seconds)
- **Cost**: 💲💲💲
- **Mechanics**: A scaled-down, functional copy of the entire production environment runs 24/7 in the secondary region. The secondary cluster handles a tiny fraction of synthetic traffic or sits idle at minimal capacity (e.g., 20% size).
- **Failover**: Route 53 automatically flips DNS weights or updates ARC routing controls. The secondary Auto Scaling Group rapidly scales from 20% to 100% capacity.

---

### Strategy 4: Multi-Region Active-Active (Hot Standby)
- **RTO**: Near Zero (Sub-second)
- **RPO**: Near Zero
- **Cost**: 💲💲💲💲 (Most Expensive)
- **Mechanics**: Identical production environments run full-scale across multiple geographic regions simultaneously. Traffic is routed globally using Route 53 Latency-Based or Geoproximity Routing.
- **Data Layer**: Multi-master databases (DynamoDB Global Tables, CockroachDB, or Aurora Global Database with write forwarding).
- **Failover**: If a region suffers an outage, edge DNS automatically stops routing traffic to the failed region. Remaining regions absorb traffic seamlessly with **zero user-perceived downtime**.

```mermaid
flowchart TD
    Users((Global Users)) --> R53["Route 53 Global Anycast DNS"]

    subgraph RegionA["US-East-1 (Active)"]
        ALB_A["ALB"] --> EKS_A["EKS Cluster"]
        EKS_A --> DDB_A[("DynamoDB Global Table")]
    end

    subgraph RegionB["EU-West-1 (Active)"]
        ALB_B["ALB"] --> EKS_B["EKS Cluster"]
        EKS_B --> DDB_B[("DynamoDB Global Table")]
    end

    R53 -->|50% Latency Routing| ALB_A
    R53 -->|50% Latency Routing| ALB_B
    DDB_A <-->|Bidirectional Multi-Master Sync (< 1s)| DDB_B
```

---

## 4. Disaster Recovery Automation with Terraform & Route 53 ARC

Route 53 Application Recovery Controller (ARC) enables reliable regional failover without relying on fragile DNS cache TTL propagation:

```hcl
# Route 53 Routing Control for Region Failover
resource "aws_route53recoverycontrolconfig_cluster" "dr_cluster" {
  name = "global-failover-cluster"
}

resource "aws_route53recoverycontrolconfig_control_panel" "main_panel" {
  name        = "primary-disaster-recovery"
  cluster_arn = aws_route53recoverycontrolconfig_cluster.dr_cluster.arn
}

resource "aws_route53recoverycontrolconfig_routing_control" "primary_region" {
  name              = "us-east-1-active"
  control_panel_arn = aws_route53recoverycontrolconfig_control_panel.main_panel.arn
}

resource "aws_route53recoverycontrolconfig_routing_control" "secondary_region" {
  name              = "us-west-2-standby"
  control_panel_arn = aws_route53recoverycontrolconfig_control_panel.main_panel.arn
}
```

---

## 5. Key Takeaways for DevOps Interviews

1. **Split-Brain Risk**: In Multi-Region Active-Active, network partitions can cause split-brain scenarios where both regions accept conflicting writes for the same customer ID. Use monotonic timestamps or deterministic Last-Write-Wins (LWW) conflict resolution.
2. **DNS Caching Delays**: Even with Route 53 TTL set to 60 seconds, upstream ISPs and corporate resolvers frequently ignore TTLs and cache DNS records for hours. Route 53 ARC routing controls and CloudFront Origin Groups handle failovers at the network edge much faster than client DNS propagation.
3. **Regular GameDays**: A Disaster Recovery plan that hasn't been tested in 6 months is not a plan—it's a wish. High-performing engineering teams conduct regular **GameDays** by deliberately terminating primary region connections and verifying automated failovers.