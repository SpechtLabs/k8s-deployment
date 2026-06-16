{{/*
Expand the name of the chart.
*/}}
{{- define "tka.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "tka.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "tka.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "tka.labels" -}}
helm.sh/chart: {{ include "tka.chart" . }}
{{ include "tka.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "tka.selectorLabels" -}}
app.kubernetes.io/name: {{ include "tka.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "tka.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "tka.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the secret containing the Tailscale auth token
*/}}
{{- define "tka.tailscaleSecretName" -}}
{{- if .Values.secrets.tailscale.create }}
{{- default (printf "%s-tailscale" (include "tka.fullname" .)) .Values.secrets.tailscale.secretName }}
{{- else }}
{{- .Values.secrets.tailscale.secretName }}
{{- end }}
{{- end }}

{{/*
Create the name of the persistent volume claim for Tailscale state
*/}}
{{- define "tka.pvcName" -}}
{{- printf "%s-tsnet-state" (include "tka.fullname" .) }}
{{- end }}

{{/*
Create the name of the config map
*/}}
{{- define "tka.configMapName" -}}
{{- printf "%s-config" (include "tka.fullname" .) }}
{{- end }}

{{/*
Image reference
*/}}
{{- define "tka.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" .Values.image.repository $tag }}
{{- end }}
