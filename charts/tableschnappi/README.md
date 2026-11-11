# Deploying a multi-user workshop

Use one release per participant namespace. `values-multi-user.yaml` is a small
profile for a restaurant, notebook-only workbench, shared namespace-authorized
MLflow, NeMo and the native RHOAI 3.5 AI asset entry. Copy it to your ignored
`my-values.yaml`, replace the example domain/model/image references and set
`workbench.name`/`workbench.username` to the participant's OpenShift identity.

## Shared platform versus application release

A platform administrator supplies OpenShift AI with workbenches, MLflow and
TrustyAI managed, a ready shared MLflow server/storage, participant projects,
quotas/LimitRanges, network policy and any cross-project image-pull grants.
Label projects `opendatahub.io/dashboard: "true"` for dashboard discovery. The
chart does not install cluster operators, create identity-provider accounts,
build application images or manage shared MLflow infrastructure.

The release owns its restaurant Deployments/Services/Route, NeMo CR/config,
workbench PVC/Notebook/service account, local RoleBindings and optional AI asset
registration. Native operators reconcile the Notebook and NeMo children.
The profile disables per-user pipelines so a workbench does not imply another
DSPA, MinIO and MariaDB installation. Existing `values-workshop.yaml` retains
its pipelines-enabled default.

## Render, review, install

Create the external model Secret from a private file, not an inline Helm value:

```bash
oc create secret generic model-api-key -n tableschnappi-user01 \
  --from-file=api_key=/private/path/model-api-key
helm template tableschnappi charts/tableschnappi -n tableschnappi-user01 \
  -f my-values.yaml > /tmp/user01.yaml
# Inspect the rendered YAML, then install:
helm upgrade --install tableschnappi charts/tableschnappi -n tableschnappi-user01 \
  -f my-values.yaml --wait --timeout 15m
```

Build/publish images separately and set `components.<name>.image` to a complete
`registry/repository@sha256:...` reference. The legacy shared
`image.registry`/`components.<name>.repository`/`image.tag` values still work when
the full-reference override is empty. `model.secretKey` defaults to `token` for
compatibility; use `api_key` to match the native custom endpoint Secret.
`model.extraBody: false` disables Qwen-specific request options for other APIs.

Repeat in each participant's namespace with their identity values. The profile
requires an installer authorized to create the local role grants; in particular,
`workbench.grantEdit: true` grants the human and notebook SA edit in that namespace.
It grants no cluster-wide role binding. Assistant/seed and workbench use separate
SAs, bound to the operator's MLflow integration ClusterRole in their own namespace.
Verify real participant SSO and foreign-workspace denial before the event.

## MLflow and participant content

The Notebook's top-level `opendatahub.io/mlflow-instance` annotation enables
native connection/auth injection. It does not instrument arbitrary notebook code.
The assistant and seed hook explicitly select the release namespace as their
workspace. The initial seed registers a prompt only if absent; upgrades preserve
participant versions and propagate authorization/service errors instead of
mistaking them for a missing prompt.

`workbench.repoRef` accepts a full source commit. Initial Git fetch uses that
revision; existing PVC content is preserved on restart, including participant
edits. Failed first fetches can retry. The selected workbench image needs Bash
and Git. Git credentials use an askpass helper and are not embedded into the
saved remote URL.

For an offline/prepackaged lab, set `workbench.sourceConfigMap` to an existing
ConfigMap with `source.tar.gz` and `SOURCE_COMMIT`. Optionally list notebook/helper
filenames under `workbench.seedFiles`; these keys are copied from the same
ConfigMap only when absent. The source archive must not include credentials.
Changing source values/ConfigMaps does not overwrite existing participant files.
Export notebooks before a deliberate PVC reset.

## AI asset and guardrails

`aiAsset.enabled` creates the native project ConfigMap
`gen-ai-aa-custom-model-endpoints` with the same endpoint/model/Secret reference.
Enable the RHOAI 3.5 dashboard custom endpoint feature separately. This is
Technology Preview and configures AI assets/Playground discovery; it does not
proxy model traffic, watch/reconfigure the application or create a local served
model. It owns that fixed-name ConfigMap: enable it only in a dedicated lab
project without an existing UI-managed endpoint registry.

`genaiStudio.enabled` remains off in the multi-user profile because its existing
MCP registration is a shared singleton. No MaaS/Kuadrant gateway is installed.

`guardrails.enabled: true` keeps NeMo available; `shieldsEnabled: false` starts
the assistant without shields for the exercise. Its local assistant-settings
ConfigMap controls `GUARDRAILS_ENABLED`; restart that assistant after changing it.
The upstream main branch's empty initial NeMo policy is preserved. After enabling
policies/restarting NeMo, warm it with allowed/blocked requests before a chat and
inspect traces/logs for fail-open: the existing 15-second timeout/fail-open policy
and workshop TLS settings are unchanged by this chart PR.

## Upgrade and cleanup

Version 0.2 moves persistent model Secrets, assistant SAs and RoleBindings from
hooks into normal release resources. Wait/seed/model-check Jobs run post-install
and post-upgrade, after those resources exist. Normal persistent resources are
then tracked for `helm uninstall`; hook Jobs use delete policies, except the
existing garak result Job retained for inspection.

For a **0.1 release**, inspect the old persistent hook resources before upgrading.
If they lack Helm ownership metadata, explicitly adopt only this release's old
assistant SA, MLflow RoleBinding and chart-created model Secret. For each owned
resource use the following metadata (replace resource/name/release/namespace):

```bash
oc label RESOURCE NAME -n NAMESPACE app.kubernetes.io/managed-by=Helm --overwrite
oc annotate RESOURCE NAME -n NAMESPACE \
  meta.helm.sh/release-name=RELEASE meta.helm.sh/release-namespace=NAMESPACE --overwrite
```

Never adopt a supplied `model.existingSecret` or another release's resources.
Do not delete a running SA/Secret to get past an ownership error. Existing
DSPA resources must be assessed/backed up before turning pipelines off on an
old release; the multi-user profile is intended for new notebook-only releases.
For the event's current plain-apply deployment, there is no Helm release to
upgrade: plan a separate ownership/PVC migration or reset, after merge.

```bash
helm uninstall tableschnappi -n tableschnappi-user01 --wait
```

Export participant files first: the release owns the workbench PVC. If garak
was enabled, inspect/export and delete its retained hook Job separately. Supplied
Secrets/ConfigMaps and the participant namespace stay outside release ownership.
Shared MLflow history/storage and cross-project pull grants are also external;
remove them through the platform runbook when the event ends.

## Validation

```bash
helm lint charts/tableschnappi
python3 charts/tableschnappi/tests/test_workshop.py
```

Regression checks need PyYAML and Helm, and cover all 50 namespaces, token/key
consumers, normal resource ownership/post-hook order, MLflow opt-out, notebook
source pin/retry/edit preservation and prompt seed preservation/error handling.
Cluster admission tests do not replace a full install/upgrade/uninstall rehearsal.
