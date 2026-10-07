{{/*
Expand the name of the chart.
*/}}
{{- define "taskboard-lite.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name (release name + chart name, deduplicated).
Kubernetes name fields are limited to 63 characters.
*/}}
{{- define "taskboard-lite.fullname" -}}
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
Chart name and version as used by the chart label.
*/}}
{{- define "taskboard-lite.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "taskboard-lite.labels" -}}
helm.sh/chart: {{ include "taskboard-lite.chart" . }}
{{ include "taskboard-lite.selectorLabels" . }}
app.kubernetes.io/version: {{ include "taskboard-lite.appVersion" . | quote }}
app.kubernetes.io/part-of: taskboard-lite
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (kept minimal and stable: changing them would orphan pods).
*/}}
{{- define "taskboard-lite.selectorLabels" -}}
app.kubernetes.io/name: {{ include "taskboard-lite.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Application version surfaced on /api/config and in labels.
*/}}
{{- define "taskboard-lite.appVersion" -}}
{{- default .Chart.AppVersion .Values.config.appVersion }}
{{- end }}

{{/*
Names of the dependent objects.
*/}}
{{- define "taskboard-lite.configMapName" -}}
{{- printf "%s-config" (include "taskboard-lite.fullname" .) }}
{{- end }}

{{- define "taskboard-lite.secretName" -}}
{{- if .Values.secret.existingSecret }}
{{- .Values.secret.existingSecret }}
{{- else }}
{{- printf "%s-secret" (include "taskboard-lite.fullname" .) }}
{{- end }}
{{- end }}

{{- define "taskboard-lite.pvcName" -}}
{{- if .Values.persistence.existingClaim }}
{{- .Values.persistence.existingClaim }}
{{- else }}
{{- printf "%s-data" (include "taskboard-lite.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Deployment strategy: Recreate when a ReadWriteOnce volume is in use.
*/}}
{{- define "taskboard-lite.strategyType" -}}
{{- if .Values.strategy.type }}
{{- .Values.strategy.type }}
{{- else if .Values.persistence.enabled }}
{{- "Recreate" }}
{{- else }}
{{- "RollingUpdate" }}
{{- end }}
{{- end }}
