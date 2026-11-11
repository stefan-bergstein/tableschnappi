# TableSchnappi

Full-stack AI-powered restaurant management and reservation system built on **Red Hat OpenShift AI (RHOAI)**. Used as a hands-on workshop demonstrating LLM serving, guardrails, observability, and MCP tool integration.

> **Demo software.** A personal project, not affiliated with or endorsed by Red Hat, NVIDIA, Meta or IBM. It is built to teach and to be attacked, not to run a real restaurant — see [SECURITY.md](SECURITY.md). Licensed [MIT](LICENSE); third-party material is recorded in [THIRD_PARTY.md](THIRD_PARTY.md).

```
Browser  ──►  React + Vite frontend  (real-time floor plan, QR ordering)
                    │
                    ▼
         Node.js / Express backend  (REST + Socket.IO)
                    │
          ┌─────────┴──────────┐
          │                    │
          ▼                    ▼
  Python mlflow-proxy    MCP server (8 tools)
  (assistant + tracing)  (Streamable HTTP)
          │
     NeMo Guardrails ──► any OpenAI-compatible model
          │
        MLflow  (GenAI Traces, Prompt Registry)
          │
        Garak   (red-team evaluation)
```

## Status and known limitations

Worth knowing before you spend an afternoon on this:

- **Six of the seven workshop notebooks have never been executed end to end.**
  They are kept in sync with the code by review, not by running them, so treat
  them as a guide rather than as something known to run clean. The exception is
  `05_garak_redteam.ipynb`, which has been run against a live MaaS endpoint on
  RHOAI 3.5 — 4 of 4 probes scored, in about two minutes.
- **There is no automated test suite.** No runner, no config, no `test`
  script. The automated checks that do exist are the greps in
  `.github/workflows/ci.yml` and a post-install hook that curls health
  endpoints.
- **The in-app garak panel is four probes of one prompt each.** "100%" means
  the model refused four known jailbreaks. It is not a safety certificate,
  and the panel says which fraction of the probes the score rests on.
- **The guardrails shield fails open.** If the guardrails pod is unreachable
  the turn goes through. On the Compose and MaaS profiles there is no shield
  at all; the in-code reservation checks still apply.
- **The backend store is in-memory.** Data resets on pod restart. That is
  deliberate so each workshop participant starts fresh.
- **The garak image is not published.** Build it yourself — see below. The
  other four are on `quay.io/tableschnappi` and public.

## Run the demo

Three ways in, easiest first. Paths A and B need none of the operator or
cluster-admin setup described under [Full workshop install](#full-workshop-install-rhoai-35).

The assistant works entirely through tool calls, so whichever model you point
it at **must support tool calling**. A model without it will chat happily and
never book a table.

### A. On your laptop (Podman or Docker)

Runs all four services locally. No cluster.

```bash
git clone https://github.com/KiriGould/tableschnappi
cd tableschnappi
cp .env.example .env
```

Pick a model backend in `.env` — either a local model or a shared gateway.

**Local model, via RamaLama.** In a separate terminal:

```bash
ramalama serve --port 8081 qwen2.5:7b
```

The defaults in `.env.example` already point at it. `qwen2.5:7b` does tool
calling and needs roughly 8GB; `llama3.1:8b` also works.

**Or a MaaS gateway.** Comment out the local block in `.env` and set
`MODEL_BASE_URL`, `MODEL_NAME`, and `MODEL_API_KEY` instead.

Then:

```bash
podman compose up --build      # or: docker compose up --build
```

Open <http://localhost:8080>.

Runs without MLflow or guardrails: the assistant falls back to its built-in
prompt, skips tracing, and skips the shield calls. The reservation checks
enforced in application code still apply.

### B. On a cluster, minimal

Frontend, backend, MCP server, chat, **and MLflow tracing** — no guardrails,
no workbench, and none of the Kuadrant or Gateway setup below. One
`helm install`, no manual secret creation.

Tracing is on by default here, because it is independent of where the model
runs: MaaS decides where inference happens, MLflow records what happened.
Every turn is traced and tagged with the restaurant, session, model and — when
the guest is chatting from a QR-code menu — the table number. Turn it off with
`--set mlflow.enabled=false` if you only have namespace rights, since the
MLflow RoleBinding needs permission to bind an operator ClusterRole.

**Against a MaaS gateway:**

```bash
oc new-project tableschnappi-$(oc whoami)

helm install tableschnappi charts/tableschnappi \
  -f charts/tableschnappi/values-maas.yaml \
  --set rhoai.appsDomain=<your-apps-domain> \
  --set model.endpoint=https://<maas-host> \
  --set model.name=<model-id> \
  --set model.apiKey=<your-token> \
  --set rhoai.mlflowUri=https://mlflow.redhat-ods-applications.svc:8443/mlflow

oc get route tableschnappi-frontend
```

Get your apps domain with:

```bash
oc get ingresses.config/cluster -o jsonpath='{.spec.domain}'
```

Helm creates the token Secret itself. Find the model id with
`curl -H "Authorization: Bearer <token>" https://<maas-host>/v1/models`.

**Against a model you host in the cluster** — same command, but point at the
model's internal service and drop the token:

```bash
helm install tableschnappi charts/tableschnappi \
  -f charts/tableschnappi/values-maas.yaml \
  --set rhoai.appsDomain=<your-apps-domain> \
  --set model.mode=self-hosted \
  --set model.endpoint=http://<model>-predictor.<namespace>.svc.cluster.local:8080 \
  --set model.name=<model-id>
```

Either way a pre-install hook checks the endpoint answers and that your model
is actually served, so a wrong URL or token fails immediately with a clear
message rather than surfacing later as a broken chat.

### C. Full workshop

MLflow tracing and prompt registry, NeMo Guardrails, and the workbench with the
notebooks. Continue below.

Two extras are **off by default** and are opt-in rather than part of this path:

- **Garak** needs an image you build yourself — `--set garak.enabled=true` plus
  `--set garak.image=...`, see [Building garak on the cluster](#building-garak-on-the-cluster).
- **GenAI Studio** writes a cluster-wide singleton ConfigMap, so it is unsafe
  for more than one concurrent install — `--set genaiStudio.enabled=true`, once,
  by an admin.

## Full workshop install (RHOAI 3.5)

| Requirement | Version |
|---|---|
| Red Hat OpenShift AI | 3.5+ |
| Red Hat Connectivity Link | 1.4+ |
| OpenShift Service Mesh 3 | 3.4+ |
| Helm | 3.14+ |
| `oc` CLI | 4.19+ |
| Cluster-admin access | Required for MCP, Guardrails CRDs, and gateway setup |
| Quay.io pull access | `quay.io/tableschnappi/*` images are public |

RHOAI components that must be enabled in the DataScienceCluster before installing:
- `kserve` (model serving)
- `ogx` (GenAI Studio Playground — replaces `llamastackoperator` which must be set to `Removed`)
- `aigateway` (AI Gateway for model routing and HTTPRoutes)
- `trustyai` (NeMo Guardrails CRD)
- `mlflowoperator` (MLflow tracking server — required for prompt registry + GenAI tracing)
- `mcplifecycleoperator` (MCP server management)

### Cluster Setup (RHOAI 3.5)

These are one-time admin steps. Run them before any `helm install`.

**1. Enable required DSC components:**

```bash
oc patch datasciencecluster default-dsc --type=merge -p '{
  "spec": {
    "components": {
      "llamastackoperator": {"managementState": "Removed"},
      "ogx":                {"managementState": "Managed"},
      "aigateway":          {"managementState": "Managed"}
    }
  }
}'
```

> `llamastackoperator` is deprecated in 3.5 and blocks OGX — it must be `Removed` first.

**2. Activate Red Hat Connectivity Link (Kuadrant):**

The RHCL operator installs the CRDs, but you must create a `Kuadrant` CR to activate the AuthPolicy controller. Without this, LLMInferenceService reports "AuthPolicy CRD is not available."

```bash
cat <<'EOF' | oc apply -f -
apiVersion: kuadrant.io/v1beta1
kind: Kuadrant
metadata:
  name: kuadrant
  namespace: openshift-ingress
spec: {}
EOF
```

**3. Create the inference Gateway:**

KServe's `inferenceservice-config` references a Gateway named `openshift-ai-inference`, but nothing auto-creates it. Create it manually with `allowedRoutes.namespaces.from: All` so user namespaces can attach HTTPRoutes:

```bash
cat <<'EOF' | oc apply -f -
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: openshift-ai-inference
  namespace: openshift-ingress
spec:
  gatewayClassName: data-science-gateway-class
  infrastructure:
    parametersRef:
      group: ""
      kind: ConfigMap
      name: data-science-gateway-config
  listeners:
  - name: https
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate
      certificateRefs:
      - group: ""
        kind: Secret
        name: data-science-gateway-service-tls
    allowedRoutes:
      namespaces:
        from: All
EOF
```

**4. Enable GenAI Studio in the dashboard:**

```bash
oc patch odhdashboardconfig odh-dashboard-config -n redhat-ods-applications \
  --type=merge -p '{"spec":{"dashboardConfig":{"genAiStudio":true}}}'
```

**5. Verify everything is ready:**

```bash
oc get datasciencecluster default-dsc \
  -o jsonpath='{range .status.conditions[*]}{.type}: {.status}{"\n"}{end}' \
  | grep -E 'OGXReady|AIGatewayReady|KServeReady'
# All three should show True

oc get kuadrant -n openshift-ingress
# Should show Ready

oc get gateway -n openshift-ingress
# Should show both data-science-gateway and openshift-ai-inference as Programmed
```

After this, deploy a model via the RHOAI dashboard with **"Add as AI asset endpoint"** checked. The model's LLMInferenceService should reach `Ready: True`.

## Install the workshop chart

```bash
# 1. Clone
git clone https://github.com/KiriGould/tableschnappi
cd tableschnappi

# 2. Copy and fill in the required values
cp charts/tableschnappi/values-workshop.yaml my-values.yaml
# Edit my-values.yaml: rhoai.appsDomain, rhoai.mlflowUri, rhoai.maasHost,
# rhoai.gatewayNamespace, and the model block (model.endpoint, model.name,
# and model.apiKey if your endpoint needs a token).
# gatewayNamespace is where your MaaS gateway lives. The chart writes an
# HTTPRoute and an MCPServerRegistration INTO that namespace, so getting it
# wrong writes into someone else's project. Ask whoever runs the gateway.
# model.endpoint/model.name are cluster- and model-specific — there is no
# working default. Find them with:
#   oc get inferenceservice -n <your-model-namespace>
#   curl <model.endpoint>/v1/models   # confirms the exact model name string

# 3. Install into your own namespace
helm install tableschnappi charts/tableschnappi \
  -n tableschnappi-$(oc whoami) --create-namespace \
  -f my-values.yaml

# 4. Open the app
oc get route tableschnappi-frontend -n tableschnappi-$(oc whoami)
```

For isolated per-participant releases with configurable workbench identity,
pinned source/images and no per-user pipeline database, use the
[multi-user chart profile and lifecycle guide](charts/tableschnappi/README.md).

The model Secret (if chart-created), service accounts and RoleBindings are
normal release resources. Hooks then run automatically in order:

| Hook | Type | What it does |
|---|---|---|
| `wait-mlflow` | post-install/post-upgrade (weight 0) | Polls MLflow until ready (max 5 min) |
| `seed-mlflow` | post-install/post-upgrade (weight 1) | Creates the experiment and initial prompt only if missing; preserves participant prompt versions |
| `wait-model` | post-install/post-upgrade (weight 2) | Checks the endpoint answers and serves your model, so a wrong URL or token fails here rather than as a broken chat |
| `smoke-test` | post-install (weight 10) | Hits every service health endpoint; fails the release if anything is down |
| `garak-eval` | post-install (weight 11) | Garak safety sweep — only runs when `garak.enabled=true` |
| `import-pipeline` | post-install (weights 19, 20) | Imports the sekki ingestion pipeline — only with `workbench.enabled=true` and `workbench.pipelines.enabled=true` |

## Configuration Reference

| Value | Default | Description |
|---|---|---|
| `image.registry` | `quay.io/tableschnappi` | Container registry prefix |
| `components.<name>.image` | `""` | Full image reference/digest override; empty retains shared registry/tag behavior |
| `image.tag` | `latest` | Image tag for all services |
| `model.secretKey` | `token` | Secret key shared by assistant, NeMo, workbench and hooks |
| `model.mode` | `self-hosted` | `self-hosted` for a model you run in the cluster, `maas` for a shared gateway |
| `model.endpoint` | _(required)_ | OpenAI-compatible base URL, **without** a trailing `/v1` — the chart appends it |
| `model.name` | _(required)_ | Exact model string the endpoint expects. Must support tool calling |
| `model.apiKey` | `""` | Bearer token. Helm creates the Secret from this, so no manual `oc create secret`. Pass with `--set` rather than committing it |
| `model.existingSecret` | `""` | Use instead of `model.apiKey` to reference a Secret you manage yourself, with the key selected by `model.secretKey` (default `token`) |
| `rhoai.appsDomain` | _(required)_ | Cluster apps domain for Route hostnames |
| `rhoai.mlflowUri` | _(required if `mlflow.enabled`)_ | RHOAI MLflow tracking URI |
| `rhoai.maasHost` | _(required if MCP gateway registration is wanted)_ | MaaS gateway hostname for the GenAI Studio HTTPRoute. Unrelated to `model.endpoint` |
| `rhoai.vllmEndpoint` / `rhoai.vllmModel` | `""` | Legacy aliases for `model.endpoint` / `model.name`. Still honoured so older values files keep working; prefer the `model` block |
| `assistant.enabled` | `true` | Deploy the assistant (chat, tool loop, shields). Turning this off removes chat entirely |
| `mlflow.enabled` | `true` | MLflow tracing, prompt registry, and the seed/wait hooks. Independent of `assistant.enabled` — with this off, chat still works using the built-in prompt, without tracing |
| `guardrails.enabled` | `true` | Deploy NeMo Guardrails CR |
| `mcp.enabled` | `true` | Deploy MCP server + gateway registration |
| `genaiStudio.enabled` | `false` | Create ConfigMap in `redhat-ods-applications`. This is a shared, cluster-wide singleton — enabling it for more than one concurrent participant install will cause ownership conflicts or data loss on uninstall. Leave disabled for workshop use; apply once, out-of-band, for a single admin-managed install. |
| `garak.enabled` | `false` | Run Garak safety evaluation post-install. Needs an image you build yourself |
| `rhoai.gatewayNamespace` | _(required if `rhoai.maasHost` is set)_ | Namespace the MaaS gateway lives in. The chart writes an HTTPRoute and an MCPServerRegistration **into** it, so there is no safe default — ask whoever runs your gateway |
| `workbench.enabled` | `false` | Create the RHOAI Notebook with the workshop notebooks. On in `values-workshop.yaml` |
| `workbench.image` / `workbench.repoUrl` | see `values.yaml` | Workbench image and the repo cloned into it |
| `imagePullSecrets` | `[]` | Only needed if you repoint `image.registry` at a private registry |
| `sekki.llamastackBase` | `""` | LlamaStack base URL for seasonal RAG. Both sekki values must be set or the feature stays off |
| `sekki.vectorStoreId` | `""` | Vector store holding the 24 sekki documents. The chart points at it; it does not create it |

## Component Map

| Pod | Port | What it does |
|---|---|---|
| `*-frontend` | 8080 | React app — floor plan, QR menu, chat widget |
| `*-backend` | 3001 | REST API + Socket.IO — in-memory restaurant store |
| `*-mlflow-proxy` | 8000 | AI assistant — prompt registry, tool loop, MLflow tracing |
| `*-mcp` | 3000 | MCP server — 8 tools for the GenAI Studio playground |
| `*-guardrails` | 80 | NeMo Guardrails proxy (created by TrustyAI operator) |

> **Note on persistence:** the backend uses an in-memory store seeded at startup. Data resets on pod restart — intentional for workshop use so each participant starts fresh.

## Workshop Guide

### 1. Explore the live app
Open the frontend route. Scan the QR code at a table, browse the menu, and use the reservation chat widget.

### 2. Prompt tuning in MLflow
Open RHOAI dashboard → **Experiments** → `restaurant-chatbot-traces`.

The `seed-mlflow` hook pre-loads `restaurant-assistant-prompt@v1`. Run the workshop notebooks, in order, from the RHOAI workbench (`jupyter lab workshop/<name>.ipynb`):

| Notebook | What it covers |
|---|---|
| `01_connect_and_explore.ipynb` | Verify connectivity to MLflow, vLLM, guardrails, and the MCP server |
| `02_prompt_tuning.ipynb` | Hand-write and register an improved prompt version, compare v1 vs v2 with `mlflow.genai.evaluate` |
| `03_guardrails_and_eval.ipynb` | Explore and evaluate the NeMo Guardrails rules |
| `04_guardrails_eval_automated.ipynb` | Automated guardrails evaluation with `mlflow.genai.evaluate` + LLM-as-judge scorers |
| `05_garak_redteam.ipynb` | Garak red-team probes against the guardrails endpoint, logged to MLflow |
| `06_evalhub_native.ipynb` | Submit a benchmark job through RHOAI's native EvalHub REST API |

`prompt-tuning-workshop.ipynb` is a standalone, self-contained alternative covering prompt tuning with visual (heatmap/radar/scatter) comparisons and a quick manual red-team check — useful as a single-notebook deep dive, independent of the 01–06 series.

### 3. Guardrails testing
Try off-topic questions in the chat widget (sports, weather, coding). NeMo Guardrails blocks them with a polite refusal.

### 4. GenAI Studio MCP playground
Open RHOAI → **Gen AI Studio** → **Playground**. Select your model, expand **MCP servers**, enable **TableSchnappi-MCP-Server**. Try: *"What restaurants do you have?"* or *"Is there a table available for 4 at Sakura?"*

### 5. Garak red-team evaluation (optional)

Two separate things share the name, and they are not interchangeable.

**a. The post-install sweep.** A Helm hook that runs once at install time
using the dedicated `packages/garak` image, and writes its results to the pod
log.

```bash
helm upgrade tableschnappi charts/tableschnappi \
  -n tableschnappi-$(oc whoami) \
  -f my-values.yaml \
  --set garak.enabled=true
```

**b. The in-app panel.** A button on the visitor page that runs four jailbreak
probes on demand against the live model and shows the attack transcript — what
was sent, what came back, and which detector judged it. This is the one worth
demoing to a room; the hook above is better suited to CI.

It needs garak inside the assistant image, which is off by default because it
pulls torch and roughly doubles the image:

```bash
podman build --platform linux/amd64 --build-arg INCLUDE_GARAK=true \
  -f packages/mlflow-proxy/Dockerfile \
  -t <your-registry>/tableschnappi-mlflow-proxy:garak \
  packages/mlflow-proxy
```

Or build it on the cluster, which avoids emulating amd64 on a laptop:

```bash
oc new-build --binary --strategy=docker --name tableschnappi-assistant-garak \
  --build-arg INCLUDE_GARAK=true -n <your-namespace>
oc start-build tableschnappi-assistant-garak \
  --from-dir=packages/mlflow-proxy --follow -n <your-namespace>
```

Without it the endpoint returns a clear 501 and the panel says so.

A full sweep takes about two minutes and costs four model calls. Read the
result carefully: it is four probes of one prompt each, so "100%" means this
model refused four known jailbreaks — not that the app is safe. Probes that
produce nothing a detector can score are reported as `NO RESULT` rather than
folded into the score, and the panel says how many of the four the number
actually rests on.

> Detector choice matters more than it looks. Each probe is pinned to its own
> `dan.*` detector instead of garak's recommended set, because the set adds
> `mitigation.MitigationBypass`, which recognises refusals by matching English
> phrases — a model that refused in Chinese was scored as jailbroken.

## Seasonal knowledge (sekki) — optional RAG

The menu is priced and filtered against the **24 sekki** (二十四節気), the
traditional Japanese micro-seasons — roughly fifteen days each. The app always
knows which term it is from a built-in calendar. This optional feature goes
further: it puts a short document per sekki into a vector store so the
assistant can *ground* its recommendations in what is actually at peak, rather
than improvising.

With it on, "what do you recommend?" gets you something like:

> Since it's 寒露 (Kanro — Cold Dew), a time when the weather turns crisp and
> our bodies crave warmth, I'd recommend the Vegetable Udon (野菜うどん) …
> shiitake mushrooms that are perfectly in season right now.

**It is off by default**, and the chart does not build the store — it only
points at one. Both values are required; with either empty the assistant skips
the lookup silently and answers from its prompt.

```yaml
sekki:
  llamastackBase: http://lsd-genai-playground-service.<ns>.svc.cluster.local:8321
  vectorStoreId: vs_<uuid>
```

### Building the store

Two routes. Both need a LlamaStack deployment with a vector-store backend.

**A. One script** — simplest, and the one to start with.

```bash
python workshop/generate_sekki_pdfs.py      # 24 PDFs from sekki_data.py

export LLAMASTACK_BASE=http://<llamastack>:8321
export DOCLING_URL=https://<your-gateway>   # optional, see below
export DOCLING_KEY=sk-...
python workshop/sekki_ingest.py             # prints the vector store id
```

`DOCLING_URL` points at a **docling-serve** endpoint. Set it and nothing needs
installing locally; leave it unset and the script falls back to a local Docling
install, then to plain text. Behind a LiteLLM/MaaS gateway the route is a
passthrough at `/docling/v1/convert/source`, and the body must still carry
`"model"` even though Docling is not a chat model — a chat-completions call
against it returns 404.

**B. The Kubeflow pipeline** — `workshop/sekki_pipeline.py`, the same six
stages as a scheduled KFP v2 job (clone → PDFs → Docling → chunk → ingest →
verify), so it can be re-run on a cron.

```bash
python workshop/sekki_pipeline.py           # compiles to pipelines_gen/
# then: RHOAI Dashboard -> Data Science Pipelines -> Import pipeline
```

> Keep `sekki_pipeline.py` **ASCII-only**. The compiled spec is stored in the
> Data Science Pipelines MariaDB, whose `PipelineSpec` column rejects
> multi-byte characters — a single `→` or kanji anywhere in the file fails the
> upload with `Error 1366 (22007): Incorrect string value`, and the API returns
> a bare 500 that does not say so. The Japanese content is unaffected; it lives
> in the documents the pipeline produces, not in its definition.

### What it looks like in MLflow

Ingestion logs one run (`sekki-ingestion-pipeline`) with chunk counts and the
store id — provenance, not evaluation.

More usefully, retrieval is its own span inside every traced chat turn:

```
LLM Agent             CHAIN      7310 ms
  Sekki Retrieval     RETRIEVER  5015 ms
  ChatOpenAI          CHAT_MODEL 2290 ms
```

That span is the point. Without it an empty retrieval and a good one look
identical from outside — the assistant answers plausibly either way — so a
broken store is invisible. It also shows retrieval is the slowest step in the
turn, which is not obvious until you can see it.

## Building Images

> **Architecture:** OpenShift nodes are `linux/amd64`. CI builds the frontend,
> backend, MCP and assistant images for both amd64 and arm64, but the **garak
> image is amd64 only** — it pins `torch` and building it for arm64 under
> emulation takes hours for an artifact nothing consumes.

### Building garak on the cluster

Because of that, the easiest way to build the garak image is on OpenShift
itself: the build runs natively on an amd64 node and pushes straight to the
internal registry, so you need no external registry credentials and no local
emulation.

```bash
oc apply -f packages/garak/openshift-build.yaml -n <your-namespace>
oc start-build tableschnappi-garak --from-dir=packages/garak --follow -n <your-namespace>

helm upgrade --install tableschnappi charts/tableschnappi \
  --set garak.enabled=true \
  --set garak.image=image-registry.openshift-image-registry.svc:5000/<your-namespace>/tableschnappi-garak:latest
```

The build pod needs egress to `pypi.org` and `download.pytorch.org`.


Images are built automatically by GitHub Actions on push to `main` and published to `quay.io/tableschnappi/tableschnappi-*`. Two tags are created per build: the short git SHA (e.g. `abc1234`) and `latest`.

To rebuild and publish to your own registry, use the script — it handles the
per-image build contexts, picks podman or docker, and prints the matching helm
command:

```bash
QUAY_ORG=<your-org> ./scripts/build-push.sh
QUAY_ORG=<your-org> TAG=v1.2.3 IMAGES="backend frontend" ./scripts/build-push.sh
```

To build all four application images locally with Podman, push them to Quay,
and roll out an existing OpenShift installation:

```bash
podman login quay.io
# Log into the target cluster with oc login first.
NAMESPACE=<your-project> QUAY_ORG=<your-org> ./scripts/build-push-rollout.sh
```

The script checks the four deployments, builds and pushes all images, then
updates each deployment by digest and waits for it to become ready. It keeps
the existing model and other deployment settings. Set `DEPLOYMENT_PREFIX` if
your deployment names do not start with `tableschnappi`; `TAG`, `PLATFORM`,
and `ROLLOUT_TIMEOUT` are also configurable (see `--help`). A later Helm
upgrade uses the image values configured in Helm, so keep those aligned with
the images you intend to run.

The script exists because the build context differs per image: `mlflow-proxy`
needs its own directory (its Dockerfile `COPY`s with no path prefix) while the
others need the repo root (they `COPY` from `packages/<name>/...`). It also
pins `--platform linux/amd64`, which matters on an Apple Silicon laptop —
without it you get arm64 images that push fine and then never schedule on an
OpenShift node.

`garak` is not in the default set, because it pins `torch` for amd64 only and
building it under emulation takes hours. Build that one on the cluster
instead, as above.

Pin a specific SHA in your values file for reproducibility:
```yaml
image:
  tag: "abc1234"
```

Add `QUAY_USERNAME` and `QUAY_PASSWORD` as GitHub repository secrets to enable CI pushes.

## Uninstall

Export workbench files first: the release owns its PVC. For 0.1 hook-resource
adoption before upgrading, see the [chart lifecycle guide](charts/tableschnappi/README.md#upgrade-and-cleanup).


```bash
NS=tableschnappi-$(oc whoami)
helm uninstall tableschnappi -n "$NS" --wait
# If garak was enabled, inspect/export its retained result Job, then remove it:
oc delete job tableschnappi-garak-eval -n "$NS" --ignore-not-found
# Delete this participant project only after exports and release cleanup:
oc delete namespace "$NS"
```

In 0.2 the release-owned service accounts, RoleBindings and chart-created model
Secret are removed by Helm. Supplied Secrets, shared MLflow/storage and external
image-pull grants remain the platform administrator's responsibility. Inspect
failed/retained hook Jobs before removing the project. Shared Gen AI Studio MCP
registration must stay disabled for per-participant releases.
