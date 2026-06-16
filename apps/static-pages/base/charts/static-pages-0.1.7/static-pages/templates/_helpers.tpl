{{/*
Expand the name of the staticpages.
*/}}
{{- define "staticpages.name" -}}
{{- default .Chart.Name .Values.staticpages.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app for the staticpages name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "staticpages.fullname" -}}
{{- $name := default .Chart.Name .Values.staticpages.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "staticpages.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "staticpages.labels" -}}
helm.sh/chart: {{ include "staticpages.chart" . }}
{{ include "staticpages.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "staticpages.selectorLabels" -}}
app.kubernetes.io/name: {{ include "staticpages.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "staticpages.serviceAccountName" -}}
{{- if .Values.staticpages.serviceAccount.create }}
{{- default (include "staticpages.fullname" .) .Values.staticpages.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.staticpages.serviceAccount.name }}
{{- end }}
{{- end }}


{{/*
Expand the name of the staticpages-api.
*/}}
{{- define "apiServer.name" -}}
{{- default .Chart.Name "api" .Values.apiServer.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app for the staticpages name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "apiServer.fullname" -}}
{{- $name := default .Chart.Name "api" .Values.apiServer.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "apiServer.labels" -}}
helm.sh/chart: {{ include "staticpages.chart" . }}
{{ include "apiServer.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "apiServer.selectorLabels" -}}
app.kubernetes.io/name: {{ include "apiServer.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "apiServer.serviceAccountName" -}}
{{- if .Values.apiServer.serviceAccount.create }}
{{- default (include "apiServer.fullname" .) .Values.apiServer.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.apiServer.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Configuration Preset Values (Influenced by Values configuration)
*/}}
{{- define "staticpages.config.cm.presets" -}}
{{- $presets := dict -}}
{{- /* Server settings from service values */ -}}
{{- $server := dict
    "proxyPort" (toString .Values.staticpages.service.proxyPort)
    "apiPort" (toString .Values.staticpages.service.apiPort)
-}}
{{- $_ := set $presets "server" $server -}}
{{- toYaml $presets }}
{{- end -}}

{{/*
Merge Configuration with Preset Configuration
*/}}
{{- define "staticpages.config.cm" -}}
{{- $config := omit .Values.configs "create" "annotations" -}}
{{- $preset := include "staticpages.config.cm.presets" . | fromYaml | default dict -}}
{{- $merged := mergeOverwrite $preset $config -}}
{{- toYaml $merged }}
{{- end -}}
