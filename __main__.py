"""
Terraclaw: Infrastructure as Code for Private AI Agents

Deploys on Google Cloud:
- ZeroClaw + Litestream → GCS (SQLite durability)
- Optional: DeepSeek / vLLM on Cloud Run (GPU)
- Optional: Vertex AI Vector Search index for RAG
- Optional: Scheduled reflection job (HTTP + OIDC → Cloud Run)
- Optional: Global HTTPS load balancer (needs managed cert + DNS; off by default)
"""

from __future__ import annotations

import base64

import pulumi
import pulumi_gcp as gcp
import pulumi_random as random

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
cfg = pulumi.Config()
gcp_cfg = pulumi.Config("gcp")

project_id = gcp_cfg.require("project")

# Project number is required for Cloud Scheduler → OIDC → Cloud Run IAM wiring.
_project = gcp.organizations.get_project(project_id=project_id)
_cloud_scheduler_agent = f"serviceAccount:service-{_project.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
region = gcp_cfg.get("region") or "us-central1"

deepseek_model = cfg.get("deepseek-model") or "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"
min_instances = int(cfg.get("instance-count") or "0")
max_instances = int(cfg.get("max-instances") or "10")
memory_limit = cfg.get("memory-limit") or "1Gi"
cpu_limit = cfg.get("cpu-limit") or "1000m"
gpu_type = cfg.get("gpu-type") or "nvidia-l4"

enable_self_learning = cfg.get_bool("enable-self-learning")
if enable_self_learning is None:
    enable_self_learning = True

learning_schedule = cfg.get("learning-schedule") or "0 2 * * *"
vector_dimensions = int(cfg.get("vector-search-dimensions") or "768")

enable_global_lb = cfg.get_bool("enable-global-lb")
if enable_global_lb is None:
    enable_global_lb = False

enable_vector_index = cfg.get_bool("enable-vector-index")
if enable_vector_index is None:
    enable_vector_index = False

allow_unauthenticated = cfg.get_bool("allow-unauthenticated")
if allow_unauthenticated is None:
    allow_unauthenticated = True

image_tag = cfg.get("image-tag") or "latest"

suffix = random.RandomId("resource-suffix", byte_length=4).hex

# -----------------------------------------------------------------------------
# 1. Storage (Litestream replica target)
# -----------------------------------------------------------------------------
storage_bucket = gcp.storage.Bucket(
    "terraclaw-storage",
    name=pulumi.Output.concat("terraclaw-storage-", suffix),
    location=region,
    uniform_bucket_level_access=True,
    versioning=gcp.storage.BucketVersioningArgs(enabled=True),
    lifecycle_rules=[
        gcp.storage.BucketLifecycleRuleArgs(
            condition=gcp.storage.BucketLifecycleRuleConditionArgs(age=90),
            action=gcp.storage.BucketLifecycleRuleActionArgs(type="Delete"),
        )
    ],
)

# -----------------------------------------------------------------------------
# 2. Service accounts
# -----------------------------------------------------------------------------
zeroclaw_sa = gcp.serviceaccount.Account(
    "zeroclaw-service-account",
    account_id=pulumi.Output.concat("zeroclaw-sa-", suffix),
    display_name="Terraclaw ZeroClaw Runtime",
)

deepseek_sa = gcp.serviceaccount.Account(
    "deepseek-service-account",
    account_id=pulumi.Output.concat("deepseek-sa-", suffix),
    display_name="Terraclaw DeepSeek / vLLM",
)

reflection_sa = gcp.serviceaccount.Account(
    "reflection-service-account",
    account_id=pulumi.Output.concat("reflect-sa-", suffix),
    display_name="Terraclaw Reflection Job",
)

# Bucket-scoped IAM (avoid project-wide IAMBinding)
zeroclaw_bucket_iam = gcp.storage.BucketIAMMember(
    "zeroclaw-sa-object-admin",
    bucket=storage_bucket.name,
    role="roles/storage.objectAdmin",
    member=zeroclaw_sa.email.apply(lambda e: f"serviceAccount:{e}"),
)

reflection_bucket_iam = gcp.storage.BucketIAMMember(
    "reflection-sa-object-admin",
    bucket=storage_bucket.name,
    role="roles/storage.objectAdmin",
    member=reflection_sa.email.apply(lambda e: f"serviceAccount:{e}"),
)

# -----------------------------------------------------------------------------
# 3. Artifact Registry
# -----------------------------------------------------------------------------
artifact_registry = gcp.artifactregistry.Repository(
    "terraclaw-registry",
    repository_id=pulumi.Output.concat("terraclaw-", suffix),
    location=region,
    format="DOCKER",
    description="Terraclaw container images",
)

zeroclaw_image_uri = pulumi.Output.concat(
    region,
    "-docker.pkg.dev/",
    project_id,
    "/",
    artifact_registry.repository_id,
    "/zeroclaw:",
    image_tag,
)
reflection_image_uri = pulumi.Output.concat(
    region,
    "-docker.pkg.dev/",
    project_id,
    "/",
    artifact_registry.repository_id,
    "/reflection:",
    image_tag,
)

# -----------------------------------------------------------------------------
# 4. Vertex AI Vector Search index (optional — needs GCS data + endpoint for queries)
# -----------------------------------------------------------------------------
vector_search_index: gcp.vertex.AiIndex | None = None
if enable_vector_index:
    vector_search_index = gcp.vertex.AiIndex(
        "terraclaw-vector-index",
        display_name=pulumi.Output.concat("terraclaw-vector-", suffix),
        description="RAG embeddings index",
        region=region,
        metadata=gcp.vertex.AiIndexMetadataArgs(
            contents_delta_uri=storage_bucket.url.apply(lambda u: f"{u}/vector-index/"),
            config=gcp.vertex.AiIndexMetadataConfigArgs(
                dimensions=vector_dimensions,
                approximate_neighbors_count=150,
                distance_measure_type="COSINE_DISTANCE",
                algorithm_config=gcp.vertex.AiIndexMetadataConfigAlgorithmConfigArgs(
                    tree_ah_config=gcp.vertex.AiIndexMetadataConfigAlgorithmConfigTreeAhConfigArgs(
                        leaf_node_embedding_count=500,
                        leaf_nodes_to_search_percent=7,
                    )
                ),
            ),
        ),
    )

vector_index_name_out: pulumi.Output[str] = (
    vector_search_index.name.apply(lambda n: n)
    if vector_search_index
    else pulumi.Output.from_input("")
)

# -----------------------------------------------------------------------------
# 5. Cloud Run: DeepSeek / vLLM (GPU)
# -----------------------------------------------------------------------------
deepseek_service = gcp.cloudrunv2.Service(
    "deepseek-inference",
    name=pulumi.Output.concat("terraclaw-deepseek-", suffix),
    location=region,
    project=project_id,
    template=gcp.cloudrunv2.ServiceTemplateArgs(
        service_account=deepseek_sa.email,
        scaling=gcp.cloudrunv2.ServiceTemplateScalingArgs(
            min_instance_count=0,
            max_instance_count=max_instances,
        ),
        containers=[
            gcp.cloudrunv2.ServiceTemplateContainerArgs(
                name="vllm",
                image="vllm/vllm-openai:latest",
                args=[
                    "--model",
                    deepseek_model,
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8000",
                    "--gpu-memory-utilization",
                    "0.9",
                ],
                resources=gcp.cloudrunv2.ServiceTemplateContainerResourcesArgs(
                    limits={
                        "memory": "8Gi",
                        "cpu": "4",
                        "nvidia.com/gpu": "1",
                    },
                    startup_cpu_boost=True,
                ),
                ports=[
                    gcp.cloudrunv2.ServiceTemplateContainerPortArgs(
                        name="http1",
                        container_port=8000,
                    )
                ],
            )
        ],
        timeout="3600s",
        node_selector=gcp.cloudrunv2.ServiceTemplateNodeSelectorArgs(
            accelerator=gcp.cloudrunv2.ServiceTemplateNodeSelectorAcceleratorArgs(
                type=gpu_type,
                count=1,
            )
        ),
    ),
    traffics=[
        gcp.cloudrunv2.ServiceTrafficArgs(
            type="TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST",
            percent=100,
        )
    ],
)

# -----------------------------------------------------------------------------
# 6. Cloud Run: ZeroClaw + Litestream
# -----------------------------------------------------------------------------
zeroclaw_service = gcp.cloudrunv2.Service(
    "zeroclaw-runtime",
    name=pulumi.Output.concat("terraclaw-zeroclaw-", suffix),
    location=region,
    project=project_id,
    template=gcp.cloudrunv2.ServiceTemplateArgs(
        service_account=zeroclaw_sa.email,
        scaling=gcp.cloudrunv2.ServiceTemplateScalingArgs(
            min_instance_count=min_instances,
            max_instance_count=max_instances,
        ),
        containers=[
            gcp.cloudrunv2.ServiceTemplateContainerArgs(
                name="zeroclaw",
                image=zeroclaw_image_uri,
                resources=gcp.cloudrunv2.ServiceTemplateContainerResourcesArgs(
                    limits={
                        "memory": memory_limit,
                        "cpu": cpu_limit,
                    }
                ),
                env=[
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="OPENAI_BASE_URL",
                        value=pulumi.Output.concat(deepseek_service.uri, "/v1"),
                    ),
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="LITESTREAM_BUCKET",
                        value=storage_bucket.name,
                    ),
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="GCP_PROJECT",
                        value=project_id,
                    ),
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="GCP_REGION",
                        value=region,
                    ),
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="VECTOR_SEARCH_INDEX",
                        value=vector_index_name_out,
                    ),
                ],
                ports=[
                    gcp.cloudrunv2.ServiceTemplateContainerPortArgs(
                        name="http1",
                        container_port=8080,
                    )
                ],
            )
        ],
        timeout="300s",
    ),
    traffics=[
        gcp.cloudrunv2.ServiceTrafficArgs(
            type="TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST",
            percent=100,
        )
    ],
)

# -----------------------------------------------------------------------------
# 7. Reflection job + Scheduler (HTTP POST + OIDC)
# -----------------------------------------------------------------------------
reflection_service: gcp.cloudrunv2.Service | None = None
reflection_scheduler: gcp.cloudscheduler.Job | None = None

if enable_self_learning:
    scheduler_invoker_sa = gcp.serviceaccount.Account(
        "scheduler-invoker",
        account_id=pulumi.Output.concat("sched-inv-", suffix),
        display_name="Terraclaw Cloud Scheduler OIDC",
    )

    scheduler_invoker_binding = gcp.serviceaccount.IAMMember(
        "scheduler-agent-can-use-invoker-sa",
        service_account_id=scheduler_invoker_sa.email,
        role="roles/iam.serviceAccountUser",
        member=_cloud_scheduler_agent,
    )

    reflection_service = gcp.cloudrunv2.Service(
        "reflection-job",
        name=pulumi.Output.concat("terraclaw-reflection-", suffix),
        location=region,
        project=project_id,
        template=gcp.cloudrunv2.ServiceTemplateArgs(
            service_account=reflection_sa.email,
            scaling=gcp.cloudrunv2.ServiceTemplateScalingArgs(
                min_instance_count=0,
                max_instance_count=1,
            ),
            containers=[
                gcp.cloudrunv2.ServiceTemplateContainerArgs(
                    name="reflection",
                    image=reflection_image_uri,
                    resources=gcp.cloudrunv2.ServiceTemplateContainerResourcesArgs(
                        limits={
                            "memory": "1Gi",
                            "cpu": "1000m",
                        }
                    ),
                    env=[
                        gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                            name="OPENAI_BASE_URL",
                            value=pulumi.Output.concat(deepseek_service.uri, "/v1"),
                        ),
                        gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                            name="LITESTREAM_BUCKET",
                            value=storage_bucket.name,
                        ),
                        gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                            name="GCP_PROJECT",
                            value=project_id,
                        ),
                        gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                            name="GCP_REGION",
                            value=region,
                        ),
                        gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                            name="VECTOR_SEARCH_INDEX",
                            value=vector_index_name_out,
                        ),
                    ],
                    ports=[
                        gcp.cloudrunv2.ServiceTemplateContainerPortArgs(
                            name="http1",
                            container_port=8080,
                        )
                    ],
                )
            ],
            timeout="1800s",
        ),
        traffics=[
            gcp.cloudrunv2.ServiceTrafficArgs(
                type="TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST",
                percent=100,
            )
        ],
    )

    reflection_invoker = gcp.cloudrunv2.ServiceIamMember(
        "reflection-scheduler-invoker",
        project=project_id,
        location=region,
        name=reflection_service.name,
        role="roles/run.invoker",
        member=scheduler_invoker_sa.email.apply(lambda e: f"serviceAccount:{e}"),
    )

    reflection_uri_with_path = pulumi.Output.concat(reflection_service.uri, "/run")

    reflection_scheduler = gcp.cloudscheduler.Job(
        "reflection-scheduler",
        name=pulumi.Output.concat("terraclaw-learn-", suffix),
        region=region,
        project=project_id,
        schedule=learning_schedule,
        time_zone="UTC",
        attempt_deadline="1800s",
        http_target=gcp.cloudscheduler.JobHttpTargetArgs(
            uri=reflection_uri_with_path,
            http_method="POST",
            headers={"Content-Type": "application/json"},
            body=base64.b64encode(b'{"trigger":"scheduled_reflection"}').decode(),
            oidc_token=gcp.cloudscheduler.JobHttpTargetOidcTokenArgs(
                service_account_email=scheduler_invoker_sa.email,
                audience=reflection_service.uri,
            ),
        ),
        opts=pulumi.ResourceOptions(depends_on=[reflection_invoker, scheduler_invoker_binding]),
    )

# -----------------------------------------------------------------------------
# 8. Optional public invoke (demo / dev)
# -----------------------------------------------------------------------------
if allow_unauthenticated:

    def _public_invoker(name: str, svc: gcp.cloudrunv2.Service) -> gcp.cloudrunv2.ServiceIamMember:
        return gcp.cloudrunv2.ServiceIamMember(
            f"{name}-public-invoker",
            project=project_id,
            location=region,
            name=svc.name,
            role="roles/run.invoker",
            member="allUsers",
        )

    _ = _public_invoker("zeroclaw", zeroclaw_service)
    _ = _public_invoker("deepseek", deepseek_service)
    if reflection_service:
        _ = _public_invoker("reflection", reflection_service)

# -----------------------------------------------------------------------------
# 9. Global HTTPS LB (optional — requires managed cert + DNS; do not enable until ready)
# -----------------------------------------------------------------------------
global_ip: gcp.compute.GlobalAddress | None = None
global_forwarding_rule: gcp.compute.GlobalForwardingRule | None = None

if enable_global_lb:
    global_ip = gcp.compute.GlobalAddress(
        "terraclaw-global-ip",
        name=pulumi.Output.concat("terraclaw-ip-", suffix),
        project=project_id,
    )

    zeroclaw_neg = gcp.compute.RegionNetworkEndpointGroup(
        "zeroclaw-neg",
        name=pulumi.Output.concat("terraclaw-neg-", suffix),
        project=project_id,
        network_endpoint_type="SERVERLESS",
        region=region,
        cloud_run=gcp.compute.RegionNetworkEndpointGroupCloudRunArgs(
            service=zeroclaw_service.name,
        ),
    )

    backend_service = gcp.compute.BackendService(
        "terraclaw-backend",
        name=pulumi.Output.concat("terraclaw-backend-", suffix),
        project=project_id,
        protocol="HTTP",
        timeout_sec=30,
        backends=[
            gcp.compute.BackendServiceBackendArgs(
                group=zeroclaw_neg.id,
            )
        ],
    )

    url_map = gcp.compute.URLMap(
        "terraclaw-url-map",
        name=pulumi.Output.concat("terraclaw-urlmap-", suffix),
        project=project_id,
        default_service=backend_service.id,
    )

    # Managed cert requires a verified domain; add terraclaw:lb-domain config later.
    # Placeholder: use self-signed or enable only after configuring sslCertificates.
    https_proxy = gcp.compute.TargetHttpsProxy(
        "terraclaw-https-proxy",
        name=pulumi.Output.concat("terraclaw-proxy-", suffix),
        project=project_id,
        url_map=url_map.id,
        ssl_certificates=[],  # noqa: S106 — must be set before production use
    )

    global_forwarding_rule = gcp.compute.GlobalForwardingRule(
        "terraclaw-forwarding-rule",
        name=pulumi.Output.concat("terraclaw-fwd-", suffix),
        project=project_id,
        ip_protocol="TCP",
        port_range="443",
        ip_address=global_ip.address,
        target=https_proxy.id,
    )

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------
pulumi.export("project_id", project_id)
pulumi.export("region", region)
pulumi.export("artifact_registry_name", artifact_registry.name)
pulumi.export(
    "artifact_registry_docker_prefix",
    pulumi.Output.concat(
        region, "-docker.pkg.dev/", project_id, "/", artifact_registry.repository_id
    ),
)
pulumi.export("zeroclaw_image", zeroclaw_image_uri)
pulumi.export("reflection_image", reflection_image_uri)
pulumi.export("zeroclaw_service_url", zeroclaw_service.uri)
pulumi.export("deepseek_service_url", deepseek_service.uri)
pulumi.export("storage_bucket", storage_bucket.name)
pulumi.export("enable_global_lb", enable_global_lb)
pulumi.export("enable_vector_index", enable_vector_index)

if global_ip:
    pulumi.export("global_lb_ip", global_ip.address)

if vector_search_index:
    pulumi.export("vector_search_index", vector_search_index.name)

if reflection_service:
    pulumi.export("reflection_service_url", reflection_service.uri)

pulumi.export(
    "deploy_hint",
    pulumi.Output.concat(
        "Build and push images (after first apply creates Artifact Registry):\n",
        "  ./scripts/build-push.sh ",
        project_id,
        " ",
        region,
        " ",
        artifact_registry.repository_id,
        " ",
        image_tag,
        "\n",
        "Re-run: pulumi up\n",
        "If the first apply fails on Cloud Run (missing images), push images then apply again.",
    ),
)
