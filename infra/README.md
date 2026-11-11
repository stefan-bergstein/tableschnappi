# Workshop infrastructure: OpenShift 4.22 and OpenShift AI 3.5

This guide show how to install and configure **Red Hat OpenShift AI Self-Managed 3.5** on an existing **OpenShift Container Platform 4.22** cluster. It does not provision the cluster itself. Use a connected, disposable workshop cluster.

## What the notebooks require

The following inventory comes from reading all seven notebooks, the two requirements files, pipeline helpers and the Helm chart in this repository.

| Notebook | Exercise | Required infrastructure |
| --- | --- | --- |
| `01_connect_and_explore.ipynb` | Connectivity, experiments, MCP tools | MLflow, tool-calling model, assistant, MCP, NeMo guardrails |
| `02_prompt_tuning.ipynb` | Register/promote prompt versions, compare evaluations | Same services; write access to the namespace's MLflow workspace |
| `03_guardrails_and_eval.ipynb` | Safety checks and logged metrics | TrustyAI-managed guardrails; namespace permission to change its ConfigMap |
| `04_guardrails_eval_automated.ipynb` | Automated guardrail evaluation | Live guardrails and MLflow; pipeline support for the companion pipeline |
| `05_garak_redteam.ipynb` | DAN probes against guardrails | CPU garak dependencies, reachable guardrails, MLflow |
| `06_evalhub_native.ipynb` | Submit/poll native evaluations | TrustyAI EvalHub, PostgreSQL, provider images, tenant RBAC and route |
| `prompt-tuning-workshop.ipynb` | Visual comparison of four prompts | Workbench, model, guardrails and MLflow |

Prompt “tuning” here means editing system prompts and comparing responses. No GPU training, distributed trainer, Ray, Kueue or model registry is needed. The model server may require GPUs; the notebook itself does not. `sekki_pipeline.py` additionally uses Llama Stack vector storage, PDF generation and ingestion; that optional RAG extension is separate from notebooks 01–06 and is not provisioned by this script.

## Before installation

1. Obtain OpenShift AI entitlement and configure registry pull credentials. Configure a real identity provider and log in with an identity-provider user holding `cluster-admin`; the installation guide excludes `kubeadmin` for OpenShift AI access.
2. Confirm OCP 4.22 and the supported RHOAI patch combination in the [supported configurations](https://access.redhat.com/articles/rhoai-supported-configs) and [operator lifecycle matrix](https://access.redhat.com/support/policy/updates/openshift_operators). The 3.5 installation guide still contains older OCP version wording; resolve discrepancies against the current matrix before installing.
3. Provide a default dynamic storage class, functioning ingress DNS/TLS and the integrated image registry. The chart workbench image references an ImageStream in `redhat-ods-applications`; verify that tag exists rather than assuming installation populated it.
4. Budget platform capacity separately from participants and model serving. Red Hat's [installation requirements](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.5/html/installing_and_uninstalling_openshift_ai_self-managed/installing-and-deploying-openshift-ai_install) specify at least two workers with 8 CPUs/32 GiB each, or 32 CPUs/128 GiB for single-node OpenShift. The chart requests 2 CPUs/4 GiB per workbench (limits 4 CPUs/8 GiB), plus application and pipeline pods. Each participant uses a 5 GiB notebook PVC and two 10 GiB pipeline PVCs; MLflow adds a shared 10 GiB PVC. Allow additional space for package caches, evaluation jobs and model weights.
5. Allow worker egress to Red Hat registries, Quay, GitHub, PyPI/package files, the PyTorch CPU wheel index, and model/dataset repositories used by evaluation providers. Air-gapped operation requires mirrored images, wheels and datasets; this script does not implement mirroring. No Open Data Hub or OpenShift AI add-on should coexist with this self-managed installation.
6. Install Bash, `oc` matching the cluster, `jq`, Git and Helm 3 on the administrator workstation. Obtain `oc` from the cluster console's Command Line Tools and Helm from its official distribution. The script validates tools rather than modifying the workstation package manager.

## Install and configure OpenShift AI

From the repository root:

```bash
oc login https://api.cluster.example.com:6443
bash infra/install-prerequisites.sh --help
bash infra/install-prerequisites.sh
```

The script checks OCP version, administrator access, default storage and the `redhat-operators` catalog. It selects a channel whose current CSV reports version 3.5.x, creates the all-namespace OperatorGroup and RHOAI Subscription in `redhat-ods-operator`, and approves only the initial plan containing that selected CSV. Future upgrades remain manual. Set `RHOAI_CHANNEL` to explicitly choose among available channels. It fails when a 3.5 head is unavailable rather than installing another minor version.

It then creates the v2 DataScienceCluster from `datasciencecluster.yaml`, or merge-patches just the required components on the existing singleton: dashboard, workbenches, AI pipelines (including Argo controllers), KServe, TrustyAI and MLflow operator. KServe supplies the InferenceService CRD required by TrustyAI, even when the workshop uses an external model endpoint. Before configuring these components, the script installs the Red Hat cert-manager Operator on its `stable-v1` channel if the certificate API is absent, and waits for a webhook endpoint. This dependency subscription uses automatic approval; existing cert-manager installations are preserved. Existing unrelated component settings are preserved. An existing RHOAI installation outside 3.5 needs a separately reviewed upgrade; this bootstrap is not an upgrade tool. Do not enable the bundled Argo controller if your cluster already operates an independently managed Argo installation without reviewing the pipeline documentation.

The script waits for the operator and DSC, then creates the development MLflow CR only if no MLflow instance exists. Inspect existing instances yourself; the script does not replace their storage. The bundled cluster-scoped MLflow CR explicitly enables `serveArtifacts`, as required by the installed 3.5.2 CRD for a `file://` artifact destination. Clients upload through the tracking server, which writes to its PVC. Without artifact serving, the CRD instead requires `defaultArtifactRoot`. Override `MLFLOW_MANIFEST` with a reviewed PostgreSQL/S3 configuration for larger workshops. The [MLflow installation guide](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.5/html/working_with_mlflow/installing-mlflow_mlflow) contains different file-storage guidance; validate your configuration against the installed CRD. Notebook 05 deliberately omits artifact uploads.

Check readiness and obtain actual endpoints:

```bash
oc get csv -n redhat-ods-operator
oc get datasciencecluster
oc get mlflow -o yaml
oc get pods,pvc,route -n redhat-ods-applications
oc get imagestreamtag s2i-generic-data-science-notebook:3.5 -n redhat-ods-applications
oc get clusterrole -o name | rg mlflow
```

A Ready DSC does not establish that the subsequently created MLflow server is ready. Wait for its deployment, storage and route to become ready, then test tracking using notebook 01. Copy the MLflow tracking URI from the dashboard; do not assume a particular route hostname.

In the OpenShift AI dashboard, configure administrator/user groups and add the workshop identity-provider users. Grant each participant `edit` in their own project; retain cluster-level installation duties with the instructor. The chart creates an MLflow RoleBinding for its assistant service account, but **does not grant MLflow access to the workbench service account**. After chart installation, inspect the Notebook pod's `spec.serviceAccountName` and bind the installed MLflow integration role to that identity in the participant namespace:

```bash
oc create rolebinding workbench-mlflow -n "$NAMESPACE" \
  --clusterrole=mlflow-operator-mlflow-integration \
  --serviceaccount="$NAMESPACE:$WORKBENCH_SA"
```

Set `NAMESPACE` and `WORKBENCH_SA` first. Verify the role name on your cluster and replace it if needed. For shared `default` service accounts, this grants all pods using that account the same access; prefer a dedicated workbench identity when customizing the chart. MLflow workspaces map to project namespaces. See [SDK authentication and access](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.5/html/working_with_mlflow/installing-and-authenticating-mlflow-sdk_mlflow).

## Provide the model endpoint

To optionally browse models through the OpenShift AI model catalog, follow
[Enable the model catalog in OpenShift AI 3.5](model-catalog.md) and run the
companion `enable-model-catalog.sh` script.

Supply an OpenAI-compatible endpoint with functioning `/v1/models`, `/v1/chat/completions` and tool calling. Verify a tool-call response, not just a successful chat. Use the exact model ID returned by the endpoint. Set the base URL without `/v1` or a trailing slash.

The bootstrap enables KServe and installs cert-manager as a TrustyAI prerequisite. For local model hosting, configure standard KServe serving and a supported vLLM runtime through OpenShift AI. On NVIDIA hardware, install Node Feature Discovery and the NVIDIA GPU Operator, configure their operands, and verify allocatable `nvidia.com/gpu` before deploying the model. Configure a model storage connection/download credentials, GPU count, memory, PVC/object storage and the runtime's tool-call parser/chat template for your chosen model. Size these for the model and concurrent class traffic. The script accepts the resulting endpoint; it does not guess a GPU vendor, model license, weight location or runtime configuration. Advanced llm-d additionally needs Connectivity Link and Leader Worker Set and is unnecessary for these exercises. Follow the component-specific links in the [3.5 installation guide](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.5/html/installing_and_uninstalling_openshift_ai_self-managed/installing-and-deploying-openshift-ai_install).

For the full guardrail exercises, use a model endpoint reachable without a bearer token from the workshop namespace. The current chart guardrails configuration hardcodes `api_key: EMPTY`; it cannot authenticate to MaaS. A token-authenticated endpoint can support an application-only profile, but disabling guardrails removes prerequisites for notebooks 03–06. Do not put a real token into the guardrails ConfigMap.

## Install the participant workload

Once MLflow and the model are operational, set the values and rerun:

```bash
export NAMESPACE=tableschnappi-alice
export MODEL_ENDPOINT=http://model-predictor.models.svc.cluster.local:8080
export MODEL_NAME=your-served-model-id
export MLFLOW_URI=https://your-mlflow-route.example.com/mlflow
INSTALL_WORKSHOP=true bash infra/install-prerequisites.sh
```

The chart installs the frontend/backend, assistant, MCP, NeMo Guardrails CR, workbench and per-project DataSciencePipelinesApplication, then imports the evaluation pipeline. Its post-install wait/seed hooks need working model/MLflow endpoints. For notebook-only per-user releases, see [the multi-user chart profile](../charts/tableschnappi/README.md). It uses the repository's development MinIO and MariaDB pipeline storage; this is not production storage. No Tekton/OpenShift Pipelines installation is required for these Kubeflow pipelines. The optional post-install garak job is off; notebook 05 installs garak itself. Keep GenAI Studio registration off in participant releases because its ConfigMap is a shared singleton.

For private images or custom workbench/repository URLs, copy `charts/tableschnappi/values-workshop.yaml` to an untracked `my-values.yaml`, fill in its fields and install with Helm directly. Set `imagePullSecrets`, `workbench.image` and `workbench.repoUrl` as necessary. The bootstrap's convenience Helm invocation uses chart defaults.

```bash
oc get notebook,datasciencepipelinesapplication,pvc,pods -n "$NAMESPACE"
oc get jobs -n "$NAMESPACE"
oc get events -n "$NAMESPACE" --sort-by=.lastTimestamp
```

Ensure all PVCs are Bound, the workbench is Ready, the pipeline server is available, and the seed/import hooks succeeded before handing the project to a participant.

## EvalHub for notebook 06

TrustyAI management alone does not create an EvalHub server. Provision PostgreSQL with persistent storage and create a Secret named `evalhub-db-credentials` in the participant namespace containing key `db-url` with its PostgreSQL connection URI. Use your managed PostgreSQL service or supported database operator and keep credentials outside Git. Create an EvalHub CR named `evalhub` in that same namespace with `spec.database.type: postgresql`, `spec.database.secret: evalhub-db-credentials`, and the `lm-evaluation-harness` provider enabled. Use the installed CRD (`oc explain evalhub.spec --recursive`) and the [EvalHub deployment procedure](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html-single/evaluating_ai_systems/evaluating_ai_systems#evaluate-llms-with-evalhub_evaluate) as a schema reference; that accessible procedure is 3.4, so validate against the installed 3.5 schema before applying. The notebook's 3.5 reference is only a product landing page.

Save the reviewed manifest outside Git and pass `EVALHUB_MANIFEST=/path/to/evalhub.yaml` to the script, or apply it directly with `oc apply -n "$NAMESPACE" -f ...`. The script performs server-side dry-run validation first. Configure tenant authorization for the actual workbench service account using a namespace Role and RoleBinding granting the needed `get/list/create/update/delete` verbs on `evaluations`, `collections`, and `providers` in `trustyai.opendatahub.io`. Follow the deployment procedure's tenant setup for job service accounts, MLflow authorization and NetworkPolicies. Permit the provider job pods to reach guardrails, EvalHub, MLflow and benchmark downloads.

Check the `evalhub` route in the participant namespace, `/api/v1/health`, and `/api/v1/evaluations/providers` with a bearer token and `X-Tenant: <participant-namespace>`. Confirm `lm_evaluation_harness` advertises `truthfulqa_mc1` before submission. The notebook invokes `oc` inside the workbench to discover this route and reads its mounted service-account token; install `oc` in the image if absent. A shared EvalHub in another namespace requires changing that discovery cell and configuring cross-namespace tenants.

## Notebook environment and acceptance checks

In a workbench terminal, from the cloned repository:

```bash
python -m pip install -r workshop/requirements-notebooks.in
# Use a separate environment for compiling pipelines:
python -m venv /tmp/tableschnappi-kfp
/tmp/tableschnappi-kfp/bin/pip install -r workshop/requirements-pipeline.in
```

The KFP dependency pins do not resolve cleanly with the Docling/Transformers notebook stack; keep them separate. Notebook 05 installs `garak>=0.17` separately using the PyTorch CPU index; reserve disk/cache space and confirm it installed CPU wheels. Garak runs against a remote model, so CUDA wheels are unnecessary. The optional garak container is amd64-specific.

The chart injects `VLLM_URL`, `VLLM_MODEL`, `CLUSTER_DOMAIN`, `GUARDRAILS_URL`, `ASSISTANT_URL`, `MCP_URL`, `MLFLOW_TRACKING_URI` and `MLFLOW_WORKSPACE`. MLflow uses `kubernetes-namespaced` authentication with the pod token. The notebooks currently disable TLS verification; for a trusted workshop setup, distribute the cluster/ingress CA and configure clients to verify it.

Known notebook assumptions to address during rehearsal:

- Notebook 02 overwrites the configured MLflow URI with `https://rh-ai.<CLUSTER_DOMAIN>/mlflow`. Replace that assignment with the actual `MLFLOW_URI` if your route differs. Other cells and Markdown links contain similar hostname/namespace assumptions; inspect the printed configuration after setup.
- The combined prompt notebook contains later fallback assignments. Confirm they still target the participant namespace and chosen model.
- Notebook 03 examples assume a release name; inspect the generated guardrails ConfigMap name before editing.
- Notebook 06 evaluates a general truth benchmark through a restaurant-only guardrail. Refusals can make accuracy low even when the infrastructure works; this is an evaluation outcome, not necessarily a deployment failure.

Run notebook 01 top to bottom: model calls succeed, MLflow experiments are readable, MCP lists seven tools, and guardrails accept reservation requests and reject unrelated requests. Run 02 and verify prompt registration, evaluation metrics and rollback. Run 03–04 and inspect guardrail results in the correct workspace. Run 05 and require nonzero **scoreable** attempts; HTTP errors or empty generations are not evidence of safety. Finally submit a small notebook 06 job and confirm terminal state and logged MLflow metrics. Check the live UI produces traces in the participant workspace.

A 403 from MLflow usually means missing workspace RBAC for the calling service account. A pending workbench/PVC points to capacity, quotas or storage. ImagePullBackOff calls for checking registry credentials and ImageStream tags. Model/guardrail 401s indicate the unsupported authenticated-model path. Helm hook timeouts require inspecting hook Job logs and endpoint connectivity before retrying.

## Validation and lifecycle

The repository addition was checked with Bash syntax validation and the script help path; no live OCP installation was performed. Run the above acceptance checks on the target cluster before the workshop. The script is designed for reruns and does not uninstall shared infrastructure. A partial failed operator installation may need manual inspection of its Subscription, OperatorGroup and InstallPlan before retrying.

After the workshop, uninstall participant Helm releases and remove their projects only after exporting needed work. Keep shared RHOAI and MLflow until all participants are done. Back up MLflow metadata and volumes before any shared teardown; do not delete the DSC as a routine participant cleanup step.

### Recovering from TrustyAI `PreConditionFailed`

The original bootstrap enabled TrustyAI without KServe. On OpenShift AI 3.5.2 this leaves `DependenciesAvailable=False` with “InferenceServices CRD does not exist, please enable serving component first”. `INSTALL_WORKSHOP=false` only skips the participant Helm chart; it still installs the platform components. Rerun the updated script to install cert-manager when needed and enable KServe on the existing DSC, preserving the other components:

```bash
INSTALL_WORKSHOP=false ./infra/install-prerequisites.sh
oc get crd inferenceservices.serving.kserve.io
oc get trustyai.components.platform.opendatahub.io -o yaml
oc get datascienceclusters -o yaml
```

Do not delete the DSC or reinstall OpenShift AI. The updated script prints DSC, TrustyAI and KServe conditions if readiness times out. An existing cert-manager Subscription using manual approval must have its installation approved by the administrator.

Cert-manager installation follows the [Red Hat operator procedure](https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/security_and_compliance/cert-manager-operator-for-red-hat-openshift), including the `stable-v1` channel and all-namespace OperatorGroup.
