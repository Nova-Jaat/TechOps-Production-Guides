# How MxPlayer Scales with Amazon EKS Spot Instances: 70% Cloud Compute Savings

## 1. Context & The Streaming Scale Challenge

MX Player (one of the largest OTT video streaming platforms in the world, with over 300 million monthly active users) faces extreme, spiky traffic profiles:
- During major live sporting events (e.g., cricket tournaments, IPL) or blockbuster movie premieres, video transcoding, recommendation engines, and ad-insertion workloads spike **10x to 50x within minutes**.
- Provisioning 100% **On-Demand EC2 instances** to absorb peak loads would result in millions of dollars in idle capacity bills during off-peak hours.

To solve this, MX Player re-architected their container infrastructure onto **Amazon EKS running on EC2 Spot Instances**, slashing their compute infrastructure bills by **over 70%** while maintaining **99.99% service availability**.

---

## 2. The Mechanics of EC2 Spot Instances

**EC2 Spot Instances** represent unused compute capacity in the AWS cloud sold at discounts of up to **70% to 90%** compared to On-Demand prices.

### The Catch: The 2-Minute Interruption Notice
When AWS needs the capacity back for full-paying On-Demand customers, AWS issues a **Spot Interruption Notice**:
> AWS gives your instance a **hard 2-minute countdown** before abruptly terminating or stopping the machine!

If your Kubernetes cluster is not specifically designed to handle unexpected node terminations, pods get abruptly killed, leading to dropped video streams, failed API requests, and broken user sessions.

---

## 3. The Resilient EKS Spot Architecture

```mermaid
flowchart TD
    subgraph ControlPlane["AWS Control Plane & Event Stream"]
        AWS_Event["AWS EC2 Spot Interruption Notice\n(2-Minute Warning via EventBridge / Metadata)"]
    end

    subgraph AutoScaler["Dynamic Scaling Engine"]
        Karpenter["Karpenter Autoscaler\n(Instance Diversification: 40+ instance types)"]
    end

    subgraph EKSCluster["Amazon EKS Worker Fleet"]
        subgraph OnDemandPool["Baseline Pool (15% On-Demand)"]
            CoreAPI["Stateless API & Ingress\nCore Services (PDB: minAvailable 80%)"]
        end

        subgraph SpotPool["Elastic Burst Pool (85% Spot Instances)"]
            Node1["Spot Node A (c6i.4xlarge) - 🚨 Interruption Detected!"]
            Node2["Spot Node B (c6a.4xlarge) - Healthy"]
            Node3["Spot Node C (m7g.4xlarge) - Healthy"]
        end
    end

    AWS_Event -->|Instant Webhook (< 1s)| Karpenter
    Karpenter -->|1. Cordon & Drain Node A| Node1
    Karpenter -->|2. Spin up replacement Spot node immediately| Node3
    Node1 -->|Gracefully migrate pods (SIGTERM + 30s)| Node2
```

---

## 4. The 4 Engineering Pillars of MX Player's Spot Architecture

### Pillar 1: Massively Diversified Spot Allocation
Never configure an EKS cluster to request only a single instance type (e.g., asking only for `c5.2xlarge`). If that specific pool runs out of spot capacity in `us-east-1a`, your cluster will fail to scale.

**Best Practice**: Configure your autoscaler (Karpenter or Cluster Autoscaler) with **extreme diversification across 30+ instance types**:
- Multiple instance families: `c5`, `c6i`, `c6a`, `c7g`, `m5`, `m6i`, `m6a`, `m7g`
- Multiple sizes: `2xlarge`, `4xlarge`, `8xlarge`
- Multiple Availability Zones: `us-east-1a`, `us-east-1b`, `us-east-1c`
- Allocation Strategy: **Price-Capacity-Optimized** (launches instances from the deepest capacity pools with the lowest risk of interruption).

---

### Pillar 2: Karpenter Native Interruption Handling
Modern Kubernetes architectures replace the legacy AWS Node Termination Handler with **Karpenter's native interruption queue**:
1. Karpenter listens to an **Amazon SQS queue** subscribed to EC2 EventBridge interruption events (`EC2 Spot Instance Interruption Warning`, `EC2 Instance Rebalance Recommendation`).
2. The instant AWS emits the warning (at $t = 0\text{s}$):
   - Karpenter **cordons** the doomed node (prevents new pods from scheduling).
   - Karpenter provisions a replacement node in parallel **before the old node even shuts down**.
   - Karpenter executes a graceful **`kubectl drain`**, allowing application pods 30–60 seconds to finish active video chunks and terminate cleanly.

---

### Pillar 3: Pod Disruption Budgets (PDB) & High-Availability Quotas
Every microservice deployed on Spot instances must define a **Pod Disruption Budget (PDB)**:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: video-transcoder-pdb
spec:
  minAvailable: "80%" # Guaranteed minimum healthy pods during Spot drains
  selector:
    matchLabels:
      app: video-transcoder
```
Even if multiple spot nodes are interrupted simultaneously, Kubernetes blocks node drains until replacement pods pass readiness probes, guaranteeing zero downtime.

---

### Pillar 4: Mixed Node Architecture (On-Demand Baseline + Spot Bursts)
- **Stateful & Core Workloads (15–20%)**: Databases, Kafka brokers, Redis clusters, and core routing control planes run on stable **On-Demand** or Savings Plan instances.
- **Stateless & Batch Workloads (80–85%)**: Video transcoding, thumbnail generation, ad bidding algorithms, and recommendation workers run on **100% Spot Instances**.

---

## 5. Production Karpenter NodePool Manifest

```yaml
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata:
  name: spot-compute-fleet
spec:
  template:
    spec:
      requirements:
        # 1. Enforce Spot capacity
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["spot"]
        
        # 2. Allow both AMD64 and ARM64 (Graviton)
        - key: "kubernetes.io/arch"
          operator: In
          values: ["amd64", "arm64"]

        # 3. Massively diversify across compute and general purpose families
        - key: "karpenter.k8s.aws/instance-family"
          operator: In
          values: ["c6i", "c6a", "c7g", "m6i", "m6a", "m7g"]

        # 4. Filter instance sizes
        - key: "karpenter.k8s.aws/instance-size"
          operator: In
          values: ["2xlarge", "4xlarge"]

      nodeClassRef:
        name: default-ec2-node-class

  # Auto-consolidate underutilized nodes to save further costs
  disruption:
    consolidationPolicy: WhenUnderutilized
    expireAfter: 720h # 30 days
```

---

## 6. Key Takeaways for DevOps Interviews

1. **Spot is Not for Everything**: Never put stateful quorum clusters (etcd, Zookeeper, Ceph) or relational databases directly on Spot instances. Spot is engineered for stateless, idempotent, horizontally auto-scaled services.
2. **Rebalance Recommendations**: AWS sends an `EC2 Instance Rebalance Recommendation` signal **before** the 2-minute termination notice when a pool is becoming constrained. Karpenter can proactively drain nodes ahead of time with zero rush.
3. **The Financial Impact**: Knowing how to combine Karpenter + EKS Spot Instances is one of the highest-paid skills in 2026 DevOps because it directly saves enterprises hundreds of thousands of dollars in cloud infrastructure spend.