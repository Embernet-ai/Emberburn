{{/*
Expand the name of the chart.
*/}}
{{- define "emberburn.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
Forced to .Release.Name for stable FQDN-based proxy routing.
*/}}
{{- define "emberburn.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "emberburn.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "emberburn.labels" -}}
helm.sh/chart: {{ include "emberburn.chart" . }}
{{ include "emberburn.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "emberburn.selectorLabels" -}}
app.kubernetes.io/name: {{ include "emberburn.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app: {{ include "emberburn.name" . }}
{{- end }}

{{/*
EmberNET Store labels — The Big Four
Applied to BOTH pod template labels AND Service labels.
Required for dashboard discovery via embernet.ai/store-app=true selector.
*/}}
{{- define "emberburn.storeLabels" -}}
embernet.ai/store-app: "true"
embernet.ai/gui-type: {{ .Values.gui.type | default "web" | quote }}
embernet.ai/app-name: {{ .Values.embernet.appName | default "EmberBurn" | quote }}
embernet.ai/gui-port: {{ .Values.gui.port | default .Values.service.webui.port | default "5000" | quote }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "emberburn.serviceAccountName" -}}
{{- if .Values.pod.serviceAccount.create }}
{{- default (include "emberburn.fullname" .) .Values.pod.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.pod.serviceAccount.name }}
{{- end }}
{{- end }}



{{/*
Get resource requests and limits based on preset
*/}}
{{- define "emberburn.resources" -}}
{{- $preset := .Values.emberburn.resources.preset }}
{{- if eq $preset "custom" }}
{{- toYaml .Values.emberburn.resources.custom }}
{{- else }}
{{- $presets := .Values.emberburn.resources.presets }}
{{- if hasKey $presets $preset }}
{{- toYaml (index $presets $preset) }}
{{- else }}
{{- toYaml $presets.medium }}
{{- end }}
{{- end }}
{{- end }}

{{/*
PVC name
*/}}
{{- define "emberburn.pvcName" -}}
{{- printf "%s-data" (include "emberburn.fullname" .) }}
{{- end }}

{{/*
App icon for the embernet.ai/app-icon annotation.

Embedded as a data URI so it renders in an air-gapped cluster and does not
depend on which origin the dashboard serves the tile from. Regenerate with
  python scripts/build-chart-icon.py
Must stay an annotation value — label values cannot contain '/' or ':'.
*/}}
{{- define "emberburn.appIcon" -}}
{{- if .Values.embernet.appIcon }}
{{- .Values.embernet.appIcon }}
{{- else }}
{{- print "data:image/png;base64,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" }}
{{- end }}
{{- end }}

{{/*
Secret name — an operator-supplied existingSecret wins, so credentials can be
managed outside the chart (sealed-secrets, external-secrets, vault).
*/}}
{{- define "emberburn.secretName" -}}
{{- if .Values.security.existingSecret }}
{{- .Values.security.existingSecret }}
{{- else }}
{{- printf "%s-secrets" (include "emberburn.fullname" .) }}
{{- end }}
{{- end }}

{{/*
ConfigMap name for tags
*/}}
{{- define "emberburn.tagsConfigMapName" -}}
{{- printf "%s-tags" (include "emberburn.fullname" .) }}
{{- end }}

{{/*
ConfigMap name for publishers
*/}}
{{- define "emberburn.publishersConfigMapName" -}}
{{- printf "%s-publishers" (include "emberburn.fullname" .) }}
{{- end }}

{{/*
Generate JSON config for tags
*/}}
{{- define "emberburn.tagsConfig" -}}
{{- toJson .Values.config.tags }}
{{- end }}

{{/*
Generate JSON config for publishers
*/}}
{{- define "emberburn.publishersConfig" -}}
{{- toJson .Values.config.publishers }}
{{- end }}
