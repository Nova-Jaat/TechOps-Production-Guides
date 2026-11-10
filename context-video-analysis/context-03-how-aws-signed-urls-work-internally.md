# Context 03: How AWS Signed URLs Work Internally
*Complete Video Masterclass Breakdown & Architecture Analysis*

---

## 📺 Video Metadata & Context Overview

| Field | Detail |
|---|---|
| **Context / Video Title** | How AWS Signed URLs Work Internally |
| **Topic Domain** | Cloud Security, Cryptography, Storage Architecture, IAM SigV4 |
| **Target Roles** | Backend Engineers, Security Architects, Cloud Architects, Full-Stack Engineers |
| **Prerequisites** | Cryptographic hashing concepts (HMAC, SHA-256), REST APIs, AWS IAM |
| **Primary AWS Services** | Amazon S3, AWS STS (Security Token Service), AWS IAM, Amazon CloudFront |
| **Key Takeaway** | Signed URLs require zero AWS API calls to generate. They are purely mathematical constructions using AWS SigV4 HMAC-SHA256. If generated using STS/IAM Roles, URLs cannot outlive the underlying temporary session token. |

---

## ⏱️ Video Breakdown & Timestamp Agenda

- `00:00 - 03:15` | **The Architectural Problem**: Why passing multi-gigabyte files through API Gateway/Lambda fails.
- `03:15 - 08:00` | **What is an S3 Pre-Signed URL?**: Delegating granular, temporary authorization directly to clients.
- `08:00 - 14:30` | **The AWS SigV4 Cryptographic Process**: Canonical Request $\rightarrow$ StringToSign $\rightarrow$ Key Derivation $\rightarrow$ Signature.
- `14:30 - 19:45` | **Anatomy of the URL Parameters**: Deconstructing `X-Amz-Algorithm`, `Credential`, `Expires`, and `SignedHeaders`.
- `19:45 - 24:00` | **What S3 Does on Receiving the Request**: Independent recalculation, tamper detection, and current IAM policy checks.
- `24:00 - 28:30` | **Hands-On Python Code**: Generating pre-signed upload (`PUT`) and download (`GET`) URLs using `boto3`.
- `28:30 - 33:15` | **Production War Stories**: The 1-hour STS session expiration trap and Header Mismatch bugs.
- `33:15 - End`   | **Senior Staff Interview Drill**: CloudFront Signed URLs vs S3 Presigned URLs, KMS encryption header gotchas.

---

## 🧠 Section 1: In-Depth Conceptual & Architectural Analysis

### 1.1 The Mathematical Engine: AWS Signature Version 4 (SigV4)

Generating a Pre-signed URL does **not** call Amazon S3 over the network. It is executed entirely in your local application process using CPU cycles and standard cryptographic libraries.

```mermaid
flowchart TD
    subgraph Phase1["Phase 1: Canonical Request"]
        C1["HTTP Verb: PUT / GET"]
        C2["Canonical URI: /my-bucket/contracts/doc1.pdf"]
        C3["Canonical Query String: Sorted key=value params"]
        C4["Canonical Headers: host, x-amz-*"]
        C5["Signed Headers: host;content-type"]
        C6["Payload Hash: UNSIGNED-PAYLOAD"]
        C1 & C2 & C3 & C4 & C5 & C6 --> CanReq["Canonical Request String"]
        CanReq --> HashCR["SHA256(Canonical Request)"]
    end

    subgraph Phase2["Phase 2: String to Sign"]
        HashCR --> STS["StringToSign =
        'AWS4-HMAC-SHA256' + '\n' +
        RequestTimestamp + '\n' +
        CredentialScope (Date/Region/s3/aws4_request) + '\n' +
        HashedCanonicalRequest"]
    end

    subgraph Phase3["Phase 3: Hierarchical Key Derivation"]
        SecKey["Secret Access Key"]
        KDate["HMAC-SHA256('AWS4' + SecKey, Date)"]
        KRegion["HMAC-SHA256(KDate, Region)"]
        KService["HMAC-SHA256(KRegion, 's3')"]
        KSigning["HMAC-SHA256(KService, 'aws4_request')"]
        SecKey --> KDate --> KRegion --> KService --> KSigning
    end

    subgraph Phase4["Phase 4: Signature Output"]
        KSigning & STS --> FinalSig["HMAC-SHA256(KSigning, StringToSign)
        Hex-encoded 64-character string"]
    end
```

---

### 1.2 Anatomy of the Query String

```http
https://customer-vault.s3.us-east-1.amazonaws.com/invoices/2026-11.pdf?
X-Amz-Algorithm=AWS4-HMAC-SHA256
&X-Amz-Credential=ASIAIOSFODNN7EXAMPLE%2F20261109%2Fus-east-1%2Fs3%2Faws4_request
&X-Amz-Date=20261109T153000Z
&X-Amz-Expires=900
&X-Amz-SignedHeaders=content-type%3Bhost
&X-Amz-Signature=8d9f4c3a2b1e0f...
&X-Amz-Security-Token=IQoJb3JpZ2luX2Vj...
```

* **`X-Amz-Algorithm`**: Fixed string `AWS4-HMAC-SHA256`.
* **`X-Amz-Credential`**: Identifies the public signer (`AccessKeyID`) and the validity boundary (`YYYYMMDD/region/service/aws4_request`).
* **`X-Amz-Date`**: UTC creation timestamp. S3 checks this against server time.
* **`X-Amz-Expires`**: Time-to-live in seconds (e.g. 900 = 15 minutes). Max 604,800 seconds (7 days) for IAM Users.
* **`X-Amz-SignedHeaders`**: Whitelist of headers that must be passed verbatim by the client during the request.
* **`X-Amz-Signature`**: The HMAC hex signature verifying the entire request is unmodified.
* **`X-Amz-Security-Token`**: Present whenever signing using temporary STS credentials (e.g. EC2 Instance Profile, Lambda Execution Role, ECS Task Role).

---

### 1.3 What S3 Validates at Request Time

```mermaid
flowchart TD
    Req[Incoming HTTP PUT/GET to S3] --> CheckExpiry{Is Current Time > Date + Expires?}
    CheckExpiry -- Yes --> Expired[403: Request has expired]
    
    CheckExpiry -- No --> Recompute[S3 fetches Secret Key for AccessKey<br/>Recomputes Canonical Request & SigV4]
    Recompute --> Compare{Calculated Sig == X-Amz-Signature?}
    Compare -- No --> Tampered[403: SignatureDoesNotMatch]
    
    Compare -- Yes --> CheckSession{Is X-Amz-Security-Token still valid in STS?}
    CheckSession -- Expired --> STSFail[403: ExpiredToken]
    
    CheckSession -- Valid --> CheckIAM{Does Signer IAM Role still have s3:PutObject / s3:GetObject?}
    CheckIAM -- No --> IAMFail[403: Access Denied]
    
    CheckIAM -- Yes --> Success[200 OK: Complete Object Stream]
```

> **Crucial Insight**: A Pre-signed URL does **not** "freeze" permissions into the URL. If the backend IAM Role that generated the URL has its policy modified or deleted 2 minutes after generating the URL, S3 will reject all subsequent requests using that URL!

---

## 🛠️ Section 2: Production Code & Implementation

```python
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Use SigV4 explicitly
s3_client = boto3.client(
    's3',
    region_name='us-east-1',
    config=Config(signature_version='s3v4')
)

def create_presigned_upload(bucket_name: str, object_key: str, content_type: str, expires_in: int = 900):
    """
    Generates a secure PUT pre-signed URL requiring strict Content-Type enforcement.
    """
    try:
        url = s3_client.generate_presigned_url(
            ClientMethod='put_object',
            Params={
                'Bucket': bucket_name,
                'Key': object_key,
                'ContentType': content_type  # Client MUST upload with this exact header!
            },
            ExpiresIn=expires_in,
            HttpMethod='PUT'
        )
        return {
            "upload_url": url,
            "required_headers": {
                "Content-Type": content_type
            },
            "expires_in_seconds": expires_in
        }
    except ClientError as e:
        print(f"Failed to generate signed URL: {e}")
        raise e
```

---

## 💥 Section 3: Real-World War Stories & Edge Cases

### Incident 1: The 7-Day URL That Died in 45 Minutes (The STS Trap)
- **What happened**: A company sent automated emails to users containing a pre-signed invoice download URL configured with `ExpiresIn=604800` (7 days). The URL was generated by an AWS Lambda function running with an IAM Execution Role.
- **The Failure**: Customers clicking the link 2 hours later received `403 ExpiredToken`.
- **The Root Cause**: Lambda uses temporary credentials provided by **AWS STS**, which refresh every hour. A pre-signed URL signed by an STS token **cannot outlive the lifetime of that STS token**, regardless of what `ExpiresIn` specifies!
- **The Solution**: For URLs that must remain valid for multiple days, use **CloudFront Signed URLs** or CloudFront Signed Cookies backed by a private RSA key group, or generate the URL via an IAM User (with strict KMS restrictions).

### Incident 2: The Header Mismatch `SignatureDoesNotMatch` Error
- **What happened**: A backend developer included `Params={'Bucket': b, 'Key': k, 'ContentType': 'image/jpeg'}` when generating the URL. The frontend developer uploaded the file using `axios.put(url, file)` without setting the `Content-Type` header (or Axios defaulted it to `application/x-www-form-urlencoded`).
- **The Failure**: S3 threw `403 SignatureDoesNotMatch`.
- **The Root Cause**: `SignedHeaders` included `content-type`. When the client passed a different `Content-Type` header (or none), S3's recomputed canonical hash did not match the signature.

---

## 🎯 Section 4: Senior Staff Interview Drill

**Q1: What is the primary architectural difference between an Amazon S3 Pre-signed URL and an Amazon CloudFront Signed URL?**
> **Answer**:
> - **S3 Pre-signed URL**: Signed using AWS SigV4 (IAM credentials). Direct connection to S3. Maximum duration is bounded by the STS session lifetime (1–12 hours for roles, up to 7 days for IAM users). Does not cache responses at the CDN edge.
> - **CloudFront Signed URL**: Signed using custom RSA/ECDSA public-private key pairs (CloudFront Key Groups). Requests terminate at CloudFront Edge locations with global caching. Can have an arbitrary expiration date (e.g. 1 year, 10 years) because it is independent of IAM/STS credentials.

**Q2: Can an attacker who intercepts an S3 Pre-signed PUT URL change the target file name from `avatar.jpg` to `malware.exe`?**
> **Answer**: No. The target object key (`avatar.jpg`) is embedded inside the Canonical Request that was hashed into the `StringToSign`. If the client alters the path to `malware.exe`, S3's recalculated HMAC hash will not match `X-Amz-Signature`, and S3 will immediately reject the request with `SignatureDoesNotMatch`.
