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
ConfigMap name for the application config
*/}}
{{- define "emberburn.configMapName" -}}
{{- printf "%s-config" (include "emberburn.fullname" .) }}
{{- end }}

{{/*
Path the application config is mounted at, and read from by the `-c` argument.
*/}}
{{- define "emberburn.configPath" -}}
/app/config/emberburn.json
{{- end }}

{{/*
Generate the application config.

ONE document, not two. opcua_server.py takes a single `-c` path and reads
`tags` and `publishers` as sections of it (load_tag_config does
`config.get('tags', config)`, and PublisherManager is handed the same parsed
config). Rendering tags.json and publishers.json as separate ConfigMaps gave
the app no way to load either: it fell through to the config baked into the
image and every value set here was silently ignored, including
`publishers.sparkplug_b.enabled`.
*/}}
{{- define "emberburn.appConfig" -}}
{{- toJson (dict "tags" .Values.config.tags "publishers" .Values.config.publishers) }}
{{- end }}

{{/*
Container and Service ports of the simulated OT protocols that are enabled under
config.publishers. A JSON list of {name, port, protocol}. One stanza per
protocol: the port follows config.publishers.<key>.port so the chart cannot
declare a port the application is not listening on.

Port names are at most 15 characters (IANA service name rule), unique in the pod.
*/}}
{{- define "emberburn.otPorts" -}}
{{- $ports := list -}}
{{- $p := .Values.config.publishers -}}
{{- with $p.ethernet_ip }}
{{- if .enabled }}
{{- $ports = append $ports (dict "name" "enip-tcp" "port" (int (.port | default 44818)) "protocol" "TCP") -}}
{{- $ports = append $ports (dict "name" "enip-udp" "port" (int (.port | default 44818)) "protocol" "UDP") -}}
{{- $ports = append $ports (dict "name" "enip-io" "port" (int (.io_port | default 2222)) "protocol" "UDP") -}}
{{- end }}
{{- end }}
{{- with $p.s7comm }}
{{- if .enabled }}
{{- $ports = append $ports (dict "name" "s7comm" "port" (int (.port | default 102)) "protocol" "TCP") -}}
{{- end }}
{{- end }}
{{- with $p.bacnet }}
{{- if .enabled }}
{{- $ports = append $ports (dict "name" "bacnet" "port" (int (.port | default 47808)) "protocol" "UDP") -}}
{{- end }}
{{- end }}
{{- with $p.dnp3 }}
{{- if .enabled }}
{{- $ports = append $ports (dict "name" "dnp3" "port" (int (.port | default 20000)) "protocol" "TCP") -}}
{{- end }}
{{- end }}
{{- with $p.iec104 }}
{{- if .enabled }}
{{- $ports = append $ports (dict "name" "iec104" "port" (int (.port | default 2404)) "protocol" "TCP") -}}
{{- end }}
{{- end }}
{{- toJson $ports -}}
{{- end -}}

{{/*
True (the string "true") when an enabled simulated protocol listens below port
1024. The container runs non-root with every capability dropped, and a
Kubernetes non-root process gets no ambient capability, so NET_BIND_SERVICE
would not help. The pod sets the net.ipv4.ip_unprivileged_port_start sysctl
instead, a namespaced safe sysctl, which keeps the container context unchanged.
*/}}
{{- define "emberburn.needsLowPorts" -}}
{{- $low := false -}}
{{- range (include "emberburn.otPorts" . | fromJsonArray) }}
{{- if lt (int .port) 1024 }}{{- $low = true -}}{{- end }}
{{- end }}
{{- if $low }}true{{- end -}}
{{- end -}}

{{/*
True (the string "true") when an enabled protocol needs a raw Ethernet socket
(GOOSE, PROFINET, EtherCAT). AF_PACKET needs CAP_NET_RAW in the process's effective
set, and Kubernetes gives a non-root process no ambient capability, so a capability
added to a non-root container never reaches it. The container therefore runs as
root with every capability dropped except NET_RAW and privilege escalation off,
only while one of these is enabled. See docs/OT_PROTOCOLS.md.
*/}}
{{- define "emberburn.needsRawSockets" -}}
{{- $p := .Values.config.publishers -}}
{{- $raw := false -}}
{{- range $k := list "goose" "goose_subscriber" "profinet" "ethercat" "ethercat_master" }}
{{- $v := index $p $k }}
{{- if and $v $v.enabled }}{{- $raw = true -}}{{- end }}
{{- end }}
{{- if $raw }}true{{- end -}}
{{- end -}}

{{/*
EmberCORE sign-in (embernet_signin.py in the image). On only when the store hands
over the dashboard's public key. The web UI is then handed the write token only
for a person the dashboard's signed assertion says may write; without the key
the pod is exactly what it was.
*/}}
{{- define "emberburn.signinOn" -}}
{{- if and .Values.embernetSignin .Values.embernetSignin.publicKey -}}true{{- end -}}
{{- end }}

{{/*
The audience a token has to carry: <tenant>/<Service name>, the string the
dashboard signs (the tenant comes from the tenant-<id> namespace; the Service is
named for the release). A token made for one app opens no other. No audience is
a render error: a check quietly off is worse than a chart that will not render.
*/}}
{{- define "emberburn.signinAudience" -}}
{{- $s := .Values.embernetSignin -}}
{{- if $s.audience -}}
{{- $s.audience -}}
{{- else if hasPrefix "tenant-" .Release.Namespace -}}
{{- printf "%s/%s" (trimPrefix "tenant-" .Release.Namespace) .Release.Name -}}
{{- else if (index (.Values.tenantLabels | default dict) "embernet.ai/tenant") -}}
{{- printf "%s/%s" (index .Values.tenantLabels "embernet.ai/tenant" | toString | lower) .Release.Name -}}
{{- else -}}
{{- fail "embernetSignin.publicKey is set but the audience can't be worked out: the release is not in a tenant-<id> namespace and has no embernet.ai/tenant label; set embernetSignin.audience to <tenant>/<service>" -}}
{{- end -}}
{{- end }}
