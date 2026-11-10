# AWS VPC Peering: Architecture, Routing Rules & Production Blueprint

## 1. Context & What Is AWS VPC Peering?

A **VPC Peering Connection** is a networking connection between two Virtual Private Clouds (VPCs) that enables you to route traffic between them using private IPv4 or IPv6 addresses.

Instances in either VPC communicate with each other as if they were within the same local network:
- Traffic moves over the **AWS global private network backbone**.
- Traffic **never traverses the public internet**, reducing exposure to sniffing, DDoS, and man-in-the-middle attacks.
- Supports both **Intra-Region Peering** (same region) and **Inter-Region Peering** (across different geographic regions, with built-in hardware AES-256 encryption).

```mermaid
flowchart LR
    subgraph VPC_A["VPC A (Production Services)\nCIDR: 10.100.0.0/16 (us-east-1)"]
        App["App Server\nIP: 10.100.1.50"]
    end

    subgraph VPC_B["VPC B (Analytics & Data Lake)\nCIDR: 10.200.0.0/16 (us-east-1)"]
        DB["Analytics Engine\nIP: 10.200.5.20"]
    end

    App <-->|VPC Peering Connection (pcx-0123456789abcdef)\nPrivate AWS Backbone (Sub-millisecond)| DB
```

---

## 2. The 3 Immutable Rules & Constraints of VPC Peering

Understanding the hard constraints of VPC Peering is essential for cloud architecture design and AWS certification exams:

### Rule 1: No Overlapping CIDR Blocks
You **cannot** create a peering connection between VPCs that have matching or overlapping CIDR blocks.
- `10.0.0.0/16` $\leftrightarrow$ `10.1.0.0/16` $\rightarrow$ ✅ **Allowed**
- `10.0.0.0/16` $\leftrightarrow$ `10.0.1.0/24` $\rightarrow$ ❌ **Rejected by AWS API**

---

### Rule 2: No Transitive Routing (The Most Tested Rule)
VPC Peering is strictly a **point-to-point (1:1) non-transitive relationship**.
If VPC A is peered with VPC B, and VPC B is peered with VPC C:
$$\text{VPC A} \centernot\longleftrightarrow \text{VPC C}$$
Traffic from VPC A **cannot pass through VPC B to reach VPC C**.
To connect A to C, you must either:
1. Establish a direct peering connection between A and C.
2. Upgrade to a hub-and-spoke architecture using **AWS Transit Gateway (TGW)**.

```mermaid
flowchart LR
    VPC_A["VPC A (10.1.0.0/16)"] <-->|pcx-ab (Direct Peer)| VPC_B["VPC B (10.2.0.0/16)"]
    VPC_B <-->|pcx-bc (Direct Peer)| VPC_C["VPC C (10.3.0.0/16)"]
    VPC_A -.->|❌ BLOCKED! No Transitive Routing| VPC_C
```

---

### Rule 3: No Edge-to-Edge Routing
A VPC cannot share its Internet Gateway (IGW), NAT Gateway, Direct Connect, or Site-to-Site VPN with a peered VPC.
If VPC A has an Internet Gateway, instances in peered VPC B cannot route out to the internet through VPC A's IGW.

---

## 3. FinOps Comparison: VPC Peering vs. AWS Transit Gateway

When connecting 10 or 20 VPCs, architects must choose between **VPC Peering** and **AWS Transit Gateway (TGW)**:

| Architectural Metric | AWS VPC Peering | AWS Transit Gateway (TGW) |
|----------------------|-----------------|---------------------------|
| **Topology** | Full Mesh ($N(N-1)/2$ connections) | Centralized Hub-and-Spoke |
| **Transitive Routing** | ❌ No | ✅ Yes |
| **Hourly Cost** | **\$0.00 / hour (Free)** | **\$0.05 / hr per VPC attachment** (~\$36/mo per VPC) |
| **Data Processing Cost**| Intra-Region: \$0.01/GB (standard inter-AZ) | **\$0.02 / GB processing fee** + inter-AZ fees |
| **Best Use Case** | 2 to 5 VPCs with high throughput data transfers | Large enterprise with 20+ VPCs and on-prem Direct Connect |

> [!TIP]
> For heavy data pipelines (e.g., transferring 50 TB/month between an analytics VPC and a production database), VPC Peering saves over **\$1,000/month** compared to Transit Gateway because it incurs zero Transit Gateway processing fees.

---

## 4. Complete Terraform Reference Blueprint

This blueprint provisions two VPCs in the same account/region, creates the peering connection, auto-accepts it, and updates both route tables:

```hcl
# 1. VPC A (Requester)
resource "aws_vpc" "vpc_a" {
  cidr_block           = "10.100.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = { Name = "production-vpc" }
}

# 2. VPC B (Accepter)
resource "aws_vpc" "vpc_b" {
  cidr_block           = "10.200.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = { Name = "analytics-vpc" }
}

# 3. VPC Peering Connection
resource "aws_vpc_peering_connection" "peer_a_to_b" {
  vpc_id      = aws_vpc.vpc_a.id
  peer_vpc_id = aws_vpc.vpc_b.id
  auto_accept = true # Valid when both VPCs are in the same account

  accepter {
    allow_remote_vpc_dns_resolution = true
  }

  requester {
    allow_remote_vpc_dns_resolution = true
  }

  tags = { Name = "pcx-prod-to-analytics" }
}

# 4. Route in VPC A pointing to VPC B's CIDR
resource "aws_route" "route_a_to_b" {
  route_table_id            = aws_vpc.vpc_a.default_route_table_id
  destination_cidr_block    = aws_vpc.vpc_b.cidr_block
  vpc_peering_connection_id = aws_vpc_peering_connection.peer_a_to_b.id
}

# 5. Route in VPC B pointing to VPC A's CIDR (Bidirectional Routing)
resource "aws_route" "route_b_to_a" {
  route_table_id            = aws_vpc.vpc_b.default_route_table_id
  destination_cidr_block    = aws_vpc.vpc_a.cidr_block
  vpc_peering_connection_id = aws_vpc_peering_connection.peer_a_to_b.id
}
```

---

## 5. Security Group Referencing Across Peered VPCs

In Intra-Region VPC Peering, you don't need to hardcode brittle CIDR IP blocks in your Security Groups. You can **directly reference the peer Security Group ID**!

```hcl
# In VPC B: Allow traffic only from VPC A's application servers
resource "aws_vpc_security_group_ingress_rule" "allow_peer_app" {
  security_group_id            = aws_security_group.analytics_db_sg.id
  description                  = "Allow PostgreSQL from Prod App SG"
  referenced_security_group_id = aws_security_group.prod_app_sg.id # Cross-VPC SG Reference!
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}
```

---

## 6. Key Takeaways for DevOps Interviews

1. **Both Sides Must Route**: Establishing a peering connection does nothing until route tables in **both** VPCs are updated with destination routes pointing to `pcx-xxxx`.
2. **DNS Resolution**: To resolve public DNS hostnames to private IPs across peered VPCs, enable `allow_remote_vpc_dns_resolution` on both the requester and accepter connection attributes.
3. **Cross-Account Workflow**: When peering across two distinct AWS accounts, the requester initiates the connection, and the accepter account must execute `AcceptVpcPeeringConnection` via IAM or Terraform.