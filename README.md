# Terraclaw

> Infrastructure as Code for Private AI Agents

Terraclaw is a production-ready deployment framework that combines [ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw) (Rust-based AI agent runtime) with private DeepSeek inference to create a compliance-friendly AI agent that learns from its own interactions while keeping all data within your infrastructure.

## Problem Statement

Many organizations want AI agents but face critical blockers:
- **Security compliance**: External AI services (OpenAI, Anthropic, etc.) violate data governance policies
- **Cost unpredictability**: Pay-per-token pricing scales poorly with heavy usage
- **Data sovereignty**: Sensitive conversations leave the organization's control
- **Static behavior**: Agents don't improve from real-world usage patterns

Terraclaw solves these by providing a **fully private, self-improving agent** that runs entirely within your Google Cloud infrastructure.

## Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   ZeroClaw      │────│   DeepSeek      │────│   RAG Vector    │
│   Runtime       │    │   Inference     │    │   Store         │
│   (Cloud Run)   │    │   (Cloud Run    │    │   (Vertex AI)   │
│                 │    │    + GPU)       │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │              ┌─────────────────┐              │
         └──────────────│   Litestream    │──────────────┘
                        │   SQLite →GCS   │
                        │   (HA Backup)   │
                        └─────────────────┘
                                 │
                        ┌─────────────────┐
                        │  Self-Learning  │
                        │  Reflection Job │
                        │  (Scheduled)    │
                        └─────────────────┘
```

## Key Features

### 🔒 **Full Privacy & Compliance**
- Zero external LLM API calls - all inference runs on your GCP infrastructure
- Private DeepSeek model deployment via vLLM on Cloud Run with GPU support
- All data stays within your VPC and security boundaries
- IAM-controlled access with least-privilege principles

### ⚡ **Serverless & Cost-Optimized**
- Everything scales to zero when not in use
- Cloud Run handles traffic spikes automatically
- Spot GPU instances for inference workloads
- Target: $15-50/month for moderate usage (vs $100s+ for external APIs)

### 🧠 **Self-Improving Intelligence**
- Automated reflection loop analyzes conversation outcomes
- Generates improved prompts, tool descriptions, and memory entries
- RAG pipeline accumulates organizational knowledge over time
- Learning happens privately using your own DeepSeek model

### 🚀 **High Availability**
- Litestream provides real-time SQLite replication to GCS
- Multi-region Cloud Run deployment with global load balancing
- Automatic failover and cold-start restoration
- Persistent memory across instance restarts

### 📦 **One-Command Deployment**
- Complete infrastructure provisioned via Pulumi (Python)
- Includes monitoring, logging, security policies, and cost controls
- Easy to modify, version, and reproduce across environments

## Technology Stack

| Component | Service | Purpose |
|-----------|---------|---------|
| **Agent Runtime** | ZeroClaw (Rust) on Cloud Run | Multi-channel agent orchestration |
| **LLM Inference** | DeepSeek vLLM on Cloud Run + L4 GPU | Private reasoning and generation |
| **Agent Memory** | SQLite + Litestream → GCS | Conversation history and short-term facts |
| **Knowledge Base** | Vertex AI Vector Search | Long-term RAG index for retrieval |
| **Self-Learning** | Scheduled Cloud Run job | Automated improvement and memory pruning |
| **Infrastructure** | Pulumi (Python) | Complete IaC deployment |

## Implementation Plan

### Phase 1: Core Infrastructure (Week 1)
- [x] Set up Pulumi Python project structure
- [x] Deploy private DeepSeek inference (vLLM + Cloud Run GPU)
- [x] Deploy ZeroClaw runtime with Litestream SQLite backup (Dockerfile + `scripts/build-push.sh`)
- [x] Configure Cloud Run services with bucket-scoped IAM and (optional) Scheduler → reflection OIDC
- [ ] Test basic agent functionality with private LLM (needs `OPENAI_API_KEY` / provider secrets on Cloud Run)

### Phase 2: High Availability (Week 2)
- [ ] Implement Litestream real-time replication
- [ ] Add global load balancer with health checks
- [ ] Configure auto-scaling and cold-start optimization
- [ ] Add monitoring, logging, and alerting
- [ ] Test failover scenarios

### Phase 3: Self-Learning Pipeline (Week 3)
- [ ] Set up Vertex AI Vector Search for RAG
- [ ] Implement conversation analysis and reflection job
- [ ] Add automated SQLite pruning and summarization
- [ ] Create feedback loop for prompt/tool improvements
- [ ] Test learning capabilities with real conversations

### Phase 4: Production Readiness (Week 4)
- [ ] Add security scanning and vulnerability management
- [ ] Implement cost monitoring and budget alerts
- [ ] Create deployment docs and troubleshooting guides
- [ ] Performance testing and optimization
- [ ] Open source release with deployment scripts

## Target Outcomes

### Business Impact
- **Compliance**: Meets strict enterprise AI governance requirements
- **Cost Control**: Predictable infrastructure costs vs variable API pricing  
- **Knowledge Retention**: Organization-specific learning accumulates over time
- **Vendor Independence**: No lock-in to external AI service providers

### Technical Achievements
- Production-grade serverless AI architecture on GCP
- Real-time SQLite replication for stateful serverless applications
- Private LLM deployment with auto-scaling GPU inference
- Self-improving agent system using reinforcement learning principles
- Complete Infrastructure as Code with security best practices

### Career Development
- Demonstrates ability to architect production AI systems
- Shows deep understanding of cloud security and compliance
- Proves cost optimization and operational excellence skills
- Creates reusable open source contribution
- Provides concrete talking points for senior engineering roles

## Getting Started

### Prerequisites

- [Pulumi](https://www.pulumi.com/docs/install/) and [Google Cloud SDK](https://cloud.google.com/sdk) (`gcloud`)
- GCP project with billing; enable APIs: `run.googleapis.com`, `artifactregistry.googleapis.com`, `cloudscheduler.googleapis.com`, `aiplatform.googleapis.com` (if using Vertex index), `compute.googleapis.com` (only if `terraclaw:enable-global-lb=true`)

### Configure and deploy

```bash
git clone https://github.com/dakaii/terraclaw.git
cd terraclaw
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pulumi login
pulumi stack init dev   # once
pulumi config set gcp:project YOUR_GCP_PROJECT_ID
pulumi config set gcp:region us-central1   # optional

# Optional: terraclaw:enable-vector-index, terraclaw:enable-global-lb, terraclaw:image-tag

# First apply may create Artifact Registry then fail on Cloud Run until images exist — that is OK.
./scripts/deploy.sh

pulumi stack output artifact_registry_docker_prefix
pulumi stack output artifact_registry_name

# Build and push images (Rust build can take 15–30+ minutes the first time)
./scripts/build-push.sh YOUR_GCP_PROJECT_ID us-central1 terraclaw-XXXX latest

./scripts/deploy.sh
```

Set provider secrets on the ZeroClaw Cloud Run service (e.g. `OPENAI_API_KEY` for OpenAI-compatible endpoints, or ZeroClaw-specific auth) via Secret Manager or `gcloud run services update` — the stack wires `OPENAI_BASE_URL` to your private vLLM service.

**Note:** Leave `terraclaw:enable-global-lb` false until you attach a **managed SSL certificate** and DNS; the load balancer HTTPS proxy requires certificates. Use the default Cloud Run URLs from `pulumi stack output` for development.

---

**Terraclaw**: Because your organization's AI should be as private as your other critical infrastructure.