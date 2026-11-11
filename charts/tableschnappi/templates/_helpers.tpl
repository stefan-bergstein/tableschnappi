{{/*
Expand the name of the chart.
*/}}
{{- define "tableschnappi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified release name.
*/}}
{{- define "tableschnappi.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Chart label value (name-version).
*/}}
{{- define "tableschnappi.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "tableschnappi.labels" -}}
helm.sh/chart: {{ include "tableschnappi.chart" . }}
{{ include "tableschnappi.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (used in matchLabels + Service selectors).
*/}}
{{- define "tableschnappi.selectorLabels" -}}
app.kubernetes.io/name: {{ include "tableschnappi.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Image helper — resolves quay.io/tableschnappi/<repo>:<tag>.
Usage: {{ include "tableschnappi.image" (list . "mcpServer") }}
*/}}
{{- define "tableschnappi.image" -}}
{{- $root := index . 0 }}
{{- $key  := index . 1 }}
{{- $comp := index $root.Values.components $key }}
{{- if $comp.image -}}
{{- $comp.image -}}
{{- else -}}
{{- printf "%s/%s:%s" $root.Values.image.registry $comp.repository $root.Values.image.tag -}}
{{- end }}
{{- end }}

{{/*
Standard pod security context (required by OpenShift restricted-v2 SCC).
*/}}
{{- define "tableschnappi.securityContext" -}}
allowPrivilegeEscalation: false
runAsNonRoot: true
seccompProfile:
  type: RuntimeDefault
capabilities:
  drop: ["ALL"]
{{- end }}

{{/*
Backend service name.
*/}}
{{- define "tableschnappi.backendService" -}}
{{- printf "%s-backend" (include "tableschnappi.fullname" .) }}
{{- end }}

{{/*
MCP server service name.
*/}}
{{- define "tableschnappi.mcpService" -}}
{{- printf "%s-mcp" (include "tableschnappi.fullname" .) }}
{{- end }}

{{/*
MLflow proxy service name.
*/}}
{{- define "tableschnappi.mlflowProxyService" -}}
{{- printf "%s-mlflow-proxy" (include "tableschnappi.fullname" .) }}
{{- end }}

{{/*
Model endpoint base URL, with no trailing /v1 — callers append it.
Prefers the model.* block; falls back to the older rhoai.vllm* keys so
existing values files keep working.
*/}}
{{- define "tableschnappi.modelEndpoint" -}}
{{- $v := default .Values.rhoai.vllmEndpoint .Values.model.endpoint -}}
{{- required "model.endpoint is required: the OpenAI-compatible base URL of your model, with no trailing /v1. For a model in the cluster use http://<name>-predictor.<namespace>.svc.cluster.local:8080; for a gateway use https://<host>." $v -}}
{{- end }}

{{/*
Exact model string the endpoint expects in the OpenAI "model" field.
*/}}
{{- define "tableschnappi.modelName" -}}
{{- $v := default .Values.rhoai.vllmModel .Values.model.name -}}
{{- required "model.name is required: the exact model string your endpoint expects. Confirm it with: curl <model.endpoint>/v1/models . It must be a model that supports tool calling." $v -}}
{{- end }}

{{/*
Name of the Secret holding the model bearer token. Either one the user
manages themselves, or the one this chart creates from model.apiKey.
*/}}
{{- define "tableschnappi.modelSecretName" -}}
{{- if .Values.model.existingSecret -}}
{{- .Values.model.existingSecret -}}
{{- else if .Values.rhoai.modelApiKeySecret -}}
{{- .Values.rhoai.modelApiKeySecret -}}
{{- else -}}
{{- printf "%s-model-api-key" (include "tableschnappi.fullname" .) -}}
{{- end -}}
{{- end }}

{{/*
Whether a model bearer token is in play at all. False for an unauthenticated
in-cluster endpoint, which is the usual self-hosted case.
*/}}
{{- define "tableschnappi.modelAuthEnabled" -}}
{{- if or .Values.model.apiKey .Values.model.existingSecret .Values.rhoai.modelApiKeySecret -}}
true
{{- end -}}
{{- end }}

{{/*
Optional imagePullSecrets, rendered under a pod spec when set.
Usage: {{- include "tableschnappi.imagePullSecrets" . | nindent 6 }}
*/}}
{{- define "tableschnappi.imagePullSecrets" -}}
{{- if .Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml .Values.imagePullSecrets | nindent 2 }}
{{- end }}
{{- end }}

{{/* Notebook, PVC and service-account identity within the release namespace. */}}
{{- define "tableschnappi.workbenchName" -}}
{{- default (printf "%s-workbench" (include "tableschnappi.fullname" .)) .Values.workbench.name -}}
{{- end }}
{{- define "tableschnappi.workbenchServiceAccount" -}}
{{- default (include "tableschnappi.workbenchName" .) .Values.workbench.serviceAccountName -}}
{{- end }}
