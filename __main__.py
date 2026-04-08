"""
Terraclaw: Infrastructure as Code for Private AI Agents

This Pulumi program deploys a complete private AI agent stack on Google Cloud:
- ZeroClaw agent runtime with Litestream SQLite backup
- Private DeepSeek inference with vLLM on Cloud Run + GPU
- Vertex AI Vector Search for RAG capabilities
- Automated self-learning reflection jobs
- Serverless, cost-optimized, and fully compliant with enterprise security
"""

import pulumi
import pulumi_gcp as gcp
import pulumi_random as random

# Configuration
config = pulumi.Config()
gcp_config = pulumi.Config("gcp")

project_id = gcp_config.require("project")
region = gcp_config.get("region") or "us-central1"

# Terraclaw-specific config with defaults
deepseek_model = config.get("deepseek-model") or "deepseek-r1-distill-llama-8b"
min_instances = int(config.get("instance-count") or "0")
max_instances = int(config.get("max-instances") or "10") 
memory_limit = config.get("memory-limit") or "1Gi"
cpu_limit = config.get("cpu-limit") or "1000m"
gpu_type = config.get("gpu-type") or "nvidia-l4"
enable_self_learning = config.get_bool("enable-self-learning") or True
learning_schedule = config.get("learning-schedule") or "0 2 * * *"
vector_dimensions = int(config.get("vector-search-dimensions") or "768")

# Random suffix for unique resource names
suffix = random.RandomId("resource-suffix", byte_length=4).hex

# ============================================================================
# 1. STORAGE: GCS bucket for Litestream SQLite backups
# ============================================================================

storage_bucket = gcp.storage.Bucket(
    "terraclaw-storage",
    name=pulumi.Output.concat("terraclaw-storage-", suffix),
    location=region,
    uniform_bucket_level_access=True,
    versioning=gcp.storage.BucketVersioningArgs(enabled=True),
    lifecycle_rules=[
        gcp.storage.BucketLifecycleRuleArgs(
            condition=gcp.storage.BucketLifecycleRuleConditionArgs(age=90),
            action=gcp.storage.BucketLifecycleRuleActionArgs(type="Delete")
        )
    ]
)

# ============================================================================
# 2. IAM: Service accounts with least-privilege permissions
# ============================================================================

# Service account for ZeroClaw runtime
zeroclaw_sa = gcp.serviceaccount.Account(
    "zeroclaw-service-account", 
    account_id=pulumi.Output.concat("zeroclaw-sa-", suffix),
    display_name="Terraclaw ZeroClaw Runtime Service Account"
)

# Service account for DeepSeek inference
deepseek_sa = gcp.serviceaccount.Account(
    "deepseek-service-account",
    account_id=pulumi.Output.concat("deepseek-sa-", suffix), 
    display_name="Terraclaw DeepSeek Inference Service Account"
)

# Service account for reflection/learning jobs
reflection_sa = gcp.serviceaccount.Account(
    "reflection-service-account",
    account_id=pulumi.Output.concat("reflection-sa-", suffix),
    display_name="Terraclaw Self-Learning Service Account"
)

# Grant ZeroClaw access to storage bucket for Litestream
zeroclaw_bucket_access = gcp.projects.IAMBinding(
    "zeroclaw-bucket-access",
    project=project_id,
    role="roles/storage.objectAdmin",
    members=[zeroclaw_sa.email.apply(lambda email: f"serviceAccount:{email}")],
    condition=gcp.projects.IAMBindingConditionArgs(
        title="Terraclaw Storage Access",
        description="Access to Terraclaw storage bucket only",
        expression=storage_bucket.name.apply(
            lambda name: f'resource.name.startsWith("projects/{project_id}/buckets/{name}/")'
        )
    )
)

# Grant reflection job access to storage and vector search  
reflection_storage_access = gcp.projects.IAMBinding(
    "reflection-storage-access",
    project=project_id,
    role="roles/storage.objectViewer", 
    members=[reflection_sa.email.apply(lambda email: f"serviceAccount:{email}")],
    condition=gcp.projects.IAMBindingConditionArgs(
        title="Reflection Storage Access",
        description="Read access to SQLite backups for analysis",
        expression=storage_bucket.name.apply(
            lambda name: f'resource.name.startsWith("projects/{project_id}/buckets/{name}/")'
        )
    )
)

# ============================================================================
# 3. ARTIFACT REGISTRY: Container registry for our images
# ============================================================================

artifact_registry = gcp.artifactregistry.Repository(
    "terraclaw-registry",
    repository_id=pulumi.Output.concat("terraclaw-", suffix),
    location=region,
    format="DOCKER",
    description="Container images for Terraclaw private AI agent stack"
)

# ============================================================================
# 4. VERTEX AI VECTOR SEARCH: For RAG knowledge base
# ============================================================================

vector_search_index = gcp.vertex.AiIndex(
    "terraclaw-vector-index",
    display_name=pulumi.Output.concat("terraclaw-vector-index-", suffix),
    description="Vector search index for Terraclaw RAG pipeline",
    region=region,
    metadata=gcp.vertex.AiIndexMetadataArgs(
        contents_delta_uri=storage_bucket.url.apply(lambda url: f"{url}/vector-index/"),
        config=gcp.vertex.AiIndexMetadataConfigArgs(
            dimensions=vector_dimensions,
            approximate_neighbors_count=150,
            distance_measure_type="COSINE_DISTANCE",
            algorithm_config=gcp.vertex.AiIndexMetadataConfigAlgorithmConfigArgs(
                tree_ah_config=gcp.vertex.AiIndexMetadataConfigAlgorithmConfigTreeAhConfigArgs(
                    leaf_node_embedding_count=500,
                    leaf_nodes_to_search_percent=7
                )
            )
        )
    )
)

# ============================================================================ 
# 5. CLOUD RUN: Serverless services for the agent stack
# ============================================================================

# DeepSeek inference service (with GPU support)
deepseek_service = gcp.cloudrunv2.Service(
    "deepseek-inference",
    name=pulumi.Output.concat("terraclaw-deepseek-", suffix),
    location=region,
    template=gcp.cloudrunv2.ServiceTemplateArgs(
        service_account=deepseek_sa.email,
        scaling=gcp.cloudrunv2.ServiceTemplateScalingArgs(
            min_instance_count=0,  # Scale to zero when not used
            max_instance_count=max_instances
        ),
        containers=[
            gcp.cloudrunv2.ServiceTemplateContainerArgs(
                name="vllm-deepseek",
                image="vllm/vllm-openai:latest",  # Will be replaced with custom image
                resources=gcp.cloudrunv2.ServiceTemplateContainerResourcesArgs(
                    limits={
                        "memory": "8Gi",
                        "cpu": "4",
                        f"nvidia.com/{gpu_type.replace('nvidia-', '')}": "1"
                    },
                    startup_cpu_boost=True
                ),
                env=[
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="MODEL_NAME",
                        value=deepseek_model
                    ),
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="TENSOR_PARALLEL_SIZE", 
                        value="1"
                    ),
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="GPU_MEMORY_UTILIZATION",
                        value="0.9"
                    )
                ],
                ports=[
                    gcp.cloudrunv2.ServiceTemplateContainerPortArgs(
                        name="http1",
                        container_port=8000
                    )
                ]
            )
        ],
        timeout="3600s",  # 1 hour timeout for model loading
        node_selector=gcp.cloudrunv2.ServiceTemplateNodeSelectorArgs(
            accelerator=gcp.cloudrunv2.ServiceTemplateNodeSelectorAcceleratorArgs(
                type=gpu_type,
                count=1
            )
        )
    ),
    traffics=[
        gcp.cloudrunv2.ServiceTrafficArgs(
            type="TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST",
            percent=100
        )
    ]
)

# ZeroClaw agent runtime service
zeroclaw_service = gcp.cloudrunv2.Service(
    "zeroclaw-runtime", 
    name=pulumi.Output.concat("terraclaw-zeroclaw-", suffix),
    location=region,
    template=gcp.cloudrunv2.ServiceTemplateScalingArgs(
        service_account=zeroclaw_sa.email,
        scaling=gcp.cloudrunv2.ServiceTemplateScalingArgs(
            min_instance_count=min_instances,
            max_instance_count=max_instances
        ),
        containers=[
            gcp.cloudrunv2.ServiceTemplateContainerArgs(
                name="zeroclaw-litestream", 
                image="gcr.io/cloudrun/placeholder",  # Will be replaced with built image
                resources=gcp.cloudrunv2.ServiceTemplateContainerResourcesArgs(
                    limits={
                        "memory": memory_limit,
                        "cpu": cpu_limit
                    }
                ),
                env=[
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="DEEPSEEK_ENDPOINT",
                        value=deepseek_service.uri
                    ),
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="LITESTREAM_BUCKET",
                        value=storage_bucket.name
                    ),
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="VECTOR_SEARCH_INDEX",
                        value=vector_search_index.name
                    ),
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="GCP_PROJECT",
                        value=project_id
                    ),
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="GCP_REGION", 
                        value=region
                    )
                ],
                ports=[
                    gcp.cloudrunv2.ServiceTemplateContainerPortArgs(
                        name="http1",
                        container_port=8080
                    )
                ]
            )
        ],
        timeout="300s"
    ),
    traffics=[
        gcp.cloudrunv2.ServiceTrafficArgs(
            type="TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", 
            percent=100
        )
    ]
)

# ============================================================================
# 6. CLOUD SCHEDULER: Automated self-learning reflection jobs
# ============================================================================

if enable_self_learning:
    # Pub/Sub topic for triggering reflection jobs
    reflection_topic = gcp.pubsub.Topic(
        "reflection-trigger",
        name=pulumi.Output.concat("terraclaw-reflection-", suffix)
    )
    
    # Self-learning reflection service
    reflection_service = gcp.cloudrunv2.Service(
        "reflection-job",
        name=pulumi.Output.concat("terraclaw-reflection-", suffix),
        location=region,
        template=gcp.cloudrunv2.ServiceTemplateArgs(
            service_account=reflection_sa.email,
            scaling=gcp.cloudrunv2.ServiceTemplateScalingArgs(
                min_instance_count=0,
                max_instance_count=1
            ),
            containers=[
                gcp.cloudrunv2.ServiceTemplateContainerArgs(
                    name="reflection",
                    image="gcr.io/cloudrun/placeholder",  # Will be replaced with reflection image
                    resources=gcp.cloudrunv2.ServiceTemplateContainerResourcesArgs(
                        limits={
                            "memory": "1Gi",
                            "cpu": "1000m"
                        }
                    ),
                    env=[
                        gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                            name="DEEPSEEK_ENDPOINT",
                            value=deepseek_service.uri
                        ),
                        gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                            name="LITESTREAM_BUCKET", 
                            value=storage_bucket.name
                        ),
                        gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                            name="VECTOR_SEARCH_INDEX",
                            value=vector_search_index.name
                        ),
                        gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                            name="GCP_PROJECT",
                            value=project_id
                        )
                    ]
                )
            ],
            timeout="1800s"  # 30 minutes for reflection analysis
        ),
        traffics=[
            gcp.cloudrunv2.ServiceTrafficArgs(
                type="TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST",
                percent=100
            )
        ]
    )
    
    # Scheduler job to trigger reflection
    reflection_scheduler = gcp.cloudscheduler.Job(
        "reflection-scheduler",
        name=pulumi.Output.concat("terraclaw-learn-", suffix),
        schedule=learning_schedule,
        time_zone="UTC",
        attempt_deadline="1800s",
        pubsub_target=gcp.cloudscheduler.JobPubsubTargetArgs(
            topic_name=reflection_topic.id,
            data=pulumi.Output.concat('{"trigger": "scheduled_reflection"}').apply(
                lambda s: __import__('base64').b64encode(s.encode()).decode()
            )
        )
    )

# ============================================================================
# 7. LOAD BALANCER: Global HTTPS load balancer for HA
# ============================================================================

# Global external IP
global_ip = gcp.compute.GlobalAddress(
    "terraclaw-global-ip",
    name=pulumi.Output.concat("terraclaw-ip-", suffix)
)

# Cloud Run NEG (Network Endpoint Group) for ZeroClaw
zeroclaw_neg = gcp.compute.RegionNetworkEndpointGroup(
    "zeroclaw-neg",
    name=pulumi.Output.concat("terraclaw-neg-", suffix),
    network_endpoint_type="SERVERLESS",
    region=region,
    cloud_run=gcp.compute.RegionNetworkEndpointGroupCloudRunArgs(
        service=zeroclaw_service.name
    )
)

# Backend service
backend_service = gcp.compute.BackendService(
    "terraclaw-backend",
    name=pulumi.Output.concat("terraclaw-backend-", suffix),
    protocol="HTTP",
    timeout_sec=30,
    backends=[
        gcp.compute.BackendServiceBackendArgs(
            group=zeroclaw_neg.id
        )
    ]
)

# URL map for routing
url_map = gcp.compute.URLMap(
    "terraclaw-url-map",
    name=pulumi.Output.concat("terraclaw-urlmap-", suffix),
    default_service=backend_service.id
)

# HTTPS proxy (SSL certificate will be added later)
https_proxy = gcp.compute.TargetHttpsProxy(
    "terraclaw-https-proxy",
    name=pulumi.Output.concat("terraclaw-proxy-", suffix),
    url_map=url_map.id,
    ssl_certificates=[]  # Add managed SSL cert here
)

# Global forwarding rule
global_forwarding_rule = gcp.compute.GlobalForwardingRule(
    "terraclaw-forwarding-rule",
    name=pulumi.Output.concat("terraclaw-fwd-", suffix),
    ip_protocol="TCP",
    port_range="443",
    ip_address=global_ip.id,
    target=https_proxy.id
)

# ============================================================================ 
# OUTPUTS: Important endpoints and information
# ============================================================================

pulumi.export("project_id", project_id)
pulumi.export("region", region)
pulumi.export("global_ip", global_ip.address)
pulumi.export("zeroclaw_service_url", zeroclaw_service.uri)
pulumi.export("deepseek_service_url", deepseek_service.uri)
pulumi.export("storage_bucket", storage_bucket.name)
pulumi.export("vector_search_index", vector_search_index.name)
pulumi.export("artifact_registry", artifact_registry.name)

if enable_self_learning:
    pulumi.export("reflection_service_url", reflection_service.uri)
    pulumi.export("learning_schedule", learning_schedule)

# Instructions for next steps
pulumi.export("next_steps", pulumi.Output.concat(
    "Infrastructure deployed! Next steps:\n",
    "1. Build and push container images to: ", artifact_registry.name, "\n",
    "2. Update Cloud Run services with your custom images\n",
    "3. Configure DNS to point to: ", global_ip.address, "\n", 
    "4. Add SSL certificate for HTTPS\n",
    "5. Test ZeroClaw agent at: ", zeroclaw_service.uri
))