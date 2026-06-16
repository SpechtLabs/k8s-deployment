# hcloud-exporter

![Version: 4.17.0](https://img.shields.io/badge/Version-4.17.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 3.17.0](https://img.shields.io/badge/AppVersion-3.17.0-informational?style=flat-square)

A Helm chart for hcloud-exporter

**Homepage:** <https://promhippie.github.io/hcloud_exporter/>

## Installing the Chart

### OCI (Recommended)

```console
helm install hcloud-exporter oci://ghcr.io/promhippie/charts/hcloud-exporter
```

### Traditional

```console
helm repo add promhippie https://promhippie.github.io/charts
helm repo update
helm install hcloud-exporter promhippie/hcloud-exporter
```

## Maintainers

| Name | Email | Url |
| ---- | ------ | --- |
| tboerger | <thomas@webhippie.de> | <https://github.com/tboerger> |

## Source Code

* <https://github.com/promhippie/hcloud_exporter>

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| affinity | object | `{}` | Affinity for the deployment |
| annotations | object | `{}` | Define additional annotations |
| collector.floatingIps | bool | `true` | Enable collector for floating IPs |
| collector.images | bool | `true` | Enable collector for images |
| collector.loadBalancers | bool | `true` | Enable collector for load balancers |
| collector.pricing | bool | `true` | Enable collector for pricing |
| collector.serverMetrics | bool | `false` | Enable collector for server metrics |
| collector.servers | bool | `true` | Enable collector for servers |
| collector.sshKeys | bool | `true` | Enable collector for SSH keys |
| collector.volumes | bool | `false` | Enable collector for volumes |
| config.existingSecret | string | `nil` | Existing secret to use for credentials |
| config.token | string | `nil` | Access token for Hetzner Cloud |
| config.tokenKey | string | `"token"` | Key used within secret for token |
| envFromConfigMap | string | `""` | Environment variables from existing configmap |
| envFromSecret | string | `""` | environment variables from existing secret |
| extraEnvSecrets | object | `{}` | Extra environment variables from secrets |
| extraEnvVariables | object | `{}` | Extra environment variables from mapping |
| extraInitContainers | list | `[]` | List of extra init containers |
| extraVolumeMounts | list | `[]` | List of extra volume mounts |
| extraVolumes | list | `[]` | List of extra volumes |
| files | object | `{}` | List of files written to a configmap and mounted to /etc/hcloud-exporter-files |
| fullnameOverride | string | `""` | Override the fullname |
| image.pullPolicy | string | `"IfNotPresent"` | Image pull policy |
| image.pullSecrets | list | `[]` | Optional name of pull secret if using a private registry |
| image.repository | string | `"quay.io/promhippie/hcloud-exporter"` | Image repository used by deployment |
| image.tag | string | `""` | Optional tag for the repository, defaults to app version |
| ingress.annotations | object | `{}` | Additional annotations for the ingress |
| ingress.className | string | `nil` | Class name for the ingress resource |
| ingress.enabled | bool | `false` | Enable ingress |
| ingress.hosts | list | `[{"host":"example.local","paths":[{"path":"/","pathType":"Prefix"}]}]` | Host definition for ingress |
| ingress.labels | object | `{}` | Additional labels for the ingress |
| ingress.tls | list | `[]` | Optional TLS configuration for ingress |
| labels | object | `{}` | Define additional labels |
| nameOverride | string | `""` | Override the name |
| nodeSelector | object | `{}` | Node selector for the deployment |
| podSecurityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["all"]},"readOnlyRootFilesystem":true,"runAsGroup":10000,"runAsNonRoot":true,"runAsUser":10000}` | Security context for the pod |
| prometheusRule.additionalLabels | object | `{}` | Additional labels for prometheus rules |
| prometheusRule.enabled | bool | `false` | Enable custom prometheus rules |
| prometheusRule.namespace | string | `""` | Namespace used by prometheus rules |
| prometheusRule.rules | list | `[]` | Rules definition |
| replicaCount | int | `1` | Replicas for the deployment |
| resources | object | `{}` | Resources for the deployment |
| securityContext | object | `{}` | Security context for the deployment |
| service.annotations | object | `{}` | Additional annotations for the service |
| service.internalPort | int | `9501` | Internal port of the service |
| service.labels | object | `{}` | Additional labels for the service |
| service.port | int | `9501` | Port of the service |
| service.type | string | `"ClusterIP"` | Type of the service |
| serviceAccount.create | bool | `true` | Create a new service account |
| serviceAccount.name | string | `""` | Optional name for an existing service account |
| serviceMonitor.enabled | bool | `false` | Enable service monitor integration |
| serviceMonitor.interval | string | `"30s"` | Scrape interval |
| serviceMonitor.jobLabel | string | `nil` | Optionally override the job label |
| serviceMonitor.labels | object | `{}` | Additional labels for the service monitor |
| serviceMonitor.metricRelabelings | list | `[]` | Metric relabeling configuration |
| serviceMonitor.namespace | string | `""` | Namespace used by service monitor |
| serviceMonitor.relabelings | list | `[]` | Relabeling configuration |
| serviceMonitor.targetLabels | list | `[]` | Target labels |
| serviceMonitor.telemetryPath | string | `"/metrics"` | Scrape path |
| serviceMonitor.timeout | string | `"30s"` | Scrape timeout |
| tolerations | list | `[]` | Tolerations for the deployment |
| updateStrategy | object | `{"type":"RollingUpdate"}` | Update strategy for the deployment |
