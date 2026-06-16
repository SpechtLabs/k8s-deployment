# TKA Helm Chart

This Helm chart deploys [TKA (Tailscale Kubernetes Auth)](https://github.com/SpechtLabs/tka) on Kubernetes, providing secure, ephemeral authentication to Kubernetes clusters via Tailscale identity.

## Overview

TKA bridges **Tailscale identity** with **Kubernetes RBAC** using **ephemeral ServiceAccounts** and **short-lived tokens**. It provides secure access to Kubernetes clusters without long-lived credentials, using Tailscale's zero-trust network and identity system.

### Key Features

- **Network-gated access**: Only accessible via Tailscale network (no public ingress)
- **Ephemeral credentials**: Short-lived ServiceAccount tokens that auto-expire
- **Capability-based authorization**: Uses Tailscale ACL capability grants
- **Kubernetes-native RBAC**: Standard ClusterRole and ClusterRoleBinding resources
- **Automatic cleanup**: Expired credentials are automatically removed

### Security Note

> [!IMPORTANT]
> TKA is designed to be accessible **only via Tailscale network**.
>
> This chart does not include ingress configuration by design. The API should never be exposed to the public internet.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.8+
- A Tailscale account with admin access
- Tailscale ACLs configured with capability grants for TKA

## Installation

### 1. Add the Helm Repository

```bash
helm repo add spechtlabs https://charts.specht-labs.de
helm repo update
```

### 2. Create a Namespace

```bash
kubectl create namespace tka-system
```

> [!NOTE]
> The chart includes the TkaSignin CustomResourceDefinition in the `crds/` directory. Helm will automatically install it during chart installation and preserve it during upgrades.

### 3. Configure Tailscale ACLs

Before deploying TKA, configure your Tailscale ACLs with capability grants. Example:

```jsonc
{
  "tagOwners": {
    "tag:tka": ["group:admins"]
  },
  "grants": [
    {
      "src": ["group:admins"],
      "dst": ["tag:tka"],
      "ip": ["443"],
      "app": {
        "specht-labs.de/cap/tka": [
          {
            "role": "cluster-admin",
            "period": "8h",
            "priority": 100,
          }
        ]
      }
    }
  ]
}
```

### 4. Create Tailscale Auth Key Secret

Create a secret containing your Tailscale auth key:

```bash
kubectl create secret generic tka-tailscale \
  --from-literal=TS_AUTHKEY=tskey-auth-your-key-here \
  -n tka-system
```

Or use the chart's secret creation by setting `secrets.tailscale.authKey` in your values.

### 5. Install the Chart

```bash
helm install tka spechtlabs/tka -n tka-system -f values.yaml
```

## Configuration

### Required Configuration

| Parameter | Description | Required |
|-----------|-------------|----------|
| `secrets.tailscale.authKey` | Tailscale auth key for node registration | Yes |
| `tka.tailscale.tailnet` | Your Tailscale tailnet domain (e.g., `example.ts.net`) | Yes |
| `tka.operator.namespace` | Namespace where TKA will create user resources | Yes |

### Core Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of TKA server replicas | `1` |
| `image.repository` | TKA server image repository | `ghcr.io/spechtlabs/tka` |
| `image.tag` | TKA server image tag | `""` (uses appVersion) |
| `tka.tailscale.hostname` | Tailscale hostname for the TKA server | `tka` |
| `tka.tailscale.port` | Port for TKA API (443 for HTTPS, other for HTTP) | `443` |
| `tka.tailscale.stateDir` | Directory for Tailscale state files | `/var/lib/tka/tsnet-state` |
| `tka.tailscale.capName` | Capability name required in ACLs | `specht-labs.de/cap/tka` |

### Operator Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `tka.operator.namespace` | Namespace for user ServiceAccounts | `tka-system` |
| `tka.operator.clusterName` | Cluster name in kubeconfig | `tka-cluster` |
| `tka.operator.contextPrefix` | Prefix for kubeconfig contexts | `tka-context-` |
| `tka.operator.userPrefix` | Prefix for kubeconfig users | `tka-user-` |

### Server Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `tka.server.readTimeout` | HTTP read timeout | `10s` |
| `tka.server.readHeaderTimeout` | HTTP read header timeout | `5s` |
| `tka.server.writeTimeout` | HTTP write timeout | `20s` |
| `tka.server.idleTimeout` | HTTP idle timeout | `120s` |

### Observability Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `tka.otel.endpoint` | OpenTelemetry OTLP endpoint | `""` |
| `tka.otel.insecure` | Use insecure OTLP transport | `true` |
| `tka.otel.serviceVersion` | Value reported as `service.version` in telemetry (default: `Chart.appVersion`) | `""` |
| `serviceMonitor.enabled` | Create Prometheus ServiceMonitor | `false` |
| `serviceMonitor.interval` | Metrics scrape interval | `30s` |

### Alerting Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `prometheusRule.enabled` | Create PrometheusRule for alerting | `false` |
| `prometheusRule.privilegedRoleAlert.enabled` | Enable privileged role login alerts | `false` |
| `prometheusRule.privilegedRoleAlert.clusterRole` | Cluster role to monitor (configurable) | `cluster-admin` |
| `prometheusRule.privilegedRoleAlert.severity` | Alert severity level | `warning` |
| `prometheusRule.privilegedRoleAlert.maxActiveSessions` | Max allowed active sessions | `2` |
| `prometheusRule.serverDownAlert.enabled` | Enable server down alerts | `false` |
| `prometheusRule.errorRateAlert.enabled` | Enable error rate alerts | `false` |
| `prometheusRule.errorRateAlert.threshold` | Error rate threshold (0-1) | `0.1` |
| `prometheusRule.forbiddenRateAlert.enabled` | Enable auth failure alerts | `false` |
| `prometheusRule.forbiddenRateAlert.threshold` | Forbidden rate threshold (0-1) | `0.2` |

### Persistence Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `persistence.enabled` | Enable persistent storage for Tailscale state | `true` |
| `persistence.size` | Size of persistent volume | `1Gi` |
| `persistence.storageClass` | Storage class for persistent volume | `""` |
| `persistence.accessMode` | Access mode for persistent volume | `ReadWriteOnce` |

### Security Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `rbac.create` | Create RBAC resources | `true` |
| `serviceAccount.create` | Create service account | `true` |
| `podSecurityContext` | Pod security context | `{}` |
| `securityContext` | Container security context | `{}` |
| `networkPolicy.enabled` | Enable network policies | `false` |

> [!WARNING]
> **Security Note**: TKA requires cluster-admin level permissions to create ClusterRoleBindings for users. This is necessary because Kubernetes RBAC prevents granting permissions that the service account doesn't itself possess. TKA acts as a trusted authentication proxy, so this broad permission is required for its operation.

### High Availability Configuration

> [!IMPORTANT]
> **Scaling Limitations**: TKA cannot scale beyond 1 replica due to Tailscale node identity conflicts. Each Tailscale node requires a unique identity, so running multiple TKA instances would cause authentication failures.

## Example Values

### Basic Configuration

```yaml
# values.yaml
tka:
  tailscale:
    tailnet: "example.ts.net"
  operator:
    namespace: "tka-system"
    clusterName: "production-cluster"

secrets:
  tailscale:
    authKey: "tskey-auth-your-key-here"

resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

### Production Configuration

```yaml
tka:
  tailscale:
    tailnet: "example.ts.net"
    hostname: "k8s-auth"
  operator:
    namespace: "tka-system"
    clusterName: "production-cluster"
  otel:
    endpoint: "jaeger-collector.monitoring.svc.cluster.local:14250"
    insecure: false

secrets:
  tailscale:
    create: false
    secretName: "tka-tailscale-prod"

persistence:
  enabled: true
  size: "2Gi"
  storageClass: "fast-ssd"

serviceMonitor:
  enabled: true
  labels:
    release: prometheus

resources:
  requests:
    memory: "512Mi"
    cpu: "200m"
  limits:
    memory: "1Gi"
    cpu: "1000m"

nodeSelector:
  node-role.kubernetes.io/control-plane: ""

tolerations:
- key: "node-role.kubernetes.io/control-plane"
  operator: "Exists"
  effect: "NoSchedule"
```

## Usage

After installation, users can authenticate using the TKA CLI:

### Install TKA CLI

```bash
# Download from releases
curl -L https://github.com/SpechtLabs/tka/releases/latest/download/ts-k8s-auth-linux-amd64 -o ts-k8s-auth
chmod +x ts-k8s-auth
sudo mv ts-k8s-auth /usr/local/bin/
```

### Configure CLI

```bash
# Create config file
mkdir -p ~/.config/tka
cat > ~/.config/tka/config.yaml << EOF
tailscale:
  hostname: tka  # matches chart value
  tailnet: example.ts.net  # your tailnet
EOF

# Install shell integration for tka wrapper functions
eval "$(ts-k8s-auth generate integration bash)"  # or zsh/fish
```

### Authenticate

```bash
# For ephemeral access (auto-cleanup on exit)
tka shell
kubectl get nodes
exit

# Or for persistent session (KUBECONFIG auto-managed by shell integration)
tka login
kubectl get nodes
tka logout
```

## Monitoring

The chart includes optional Prometheus monitoring:

```yaml
serviceMonitor:
  enabled: true
  labels:
    release: prometheus  # match your Prometheus selector
```

Metrics are exposed on port 8080 at `/metrics` and include:

- TKA-specific metrics (sign-ins, active sessions, etc.)
- Standard Go runtime metrics
- HTTP request metrics

## Troubleshooting

### Common Issues

1. **Pod fails to start with Tailscale auth error**
   - Verify `TS_AUTHKEY` secret is correctly configured
   - Ensure auth key is valid and not expired
   - Check that the key has appropriate permissions

2. **Users cannot authenticate**
   - Verify Tailscale ACL configuration includes capability grants
   - Check that TKA server is tagged correctly (`tag:tka`)
   - Ensure capability name matches chart configuration

3. **ServiceAccount creation fails**
   - Verify RBAC permissions are correctly applied
   - Check that TKA operator has cluster-admin or equivalent permissions
   - Review operator logs for specific errors

### Debugging

```bash
# Check TKA server logs
kubectl logs -n tka-system deployment/tka -f

# Check CRD status
kubectl get tkasignins -A

# Check RBAC
kubectl auth can-i create serviceaccounts --as=system:serviceaccount:tka-system:tka

# Test Tailscale connectivity
kubectl exec -n tka-system deployment/tka -- tailscale status
```

## Security Considerations

1. **Network Isolation**: TKA should only be accessible via Tailscale network
2. **Auth Key Management**: Use ephemeral, reusable auth keys with appropriate scopes
3. **RBAC**: Review and limit the roles that can be granted via TKA
4. **Monitoring**: Enable audit logging and monitoring for authentication events
5. **Updates**: Keep TKA updated to the latest version for security patches

### **Important Security Model**

TKA requires **cluster-admin** level permissions to function. This is because:

- TKA creates ClusterRoleBindings for users with roles specified in Tailscale ACLs
- Kubernetes RBAC prevents granting permissions you don't already have
- Users could request `cluster-admin`, `system:*`, or any other broad role via ACLs

**Trust Model**: TKA acts as a trusted authentication proxy. Access control is enforced at the **Tailscale ACL level**, not at the Kubernetes RBAC level. Only users with proper Tailscale capability grants can authenticate, and the roles they receive are defined in your Tailscale ACL configuration.

**Mitigation Strategies**:

- Carefully control who has access to TKA via Tailscale ACLs
- Use specific, limited roles in your ACL capability grants when possible
- Monitor TKA authentication events and user activity
- Regularly audit the roles being granted via TKA

## Upgrading

```bash
# Update repository
helm repo update

# Upgrade release
helm upgrade tka spechtlabs/tka -n tka-system -f values.yaml

# Check status
helm status tka -n tka-system
```

## Uninstalling

```bash
# Uninstall the chart
helm uninstall tka -n tka-system

# Clean up CRDs (if desired)
kubectl delete crd tkasignins.tka.specht-labs.de

# Clean up namespace
kubectl delete namespace tka-system
```

## Support

- [GitHub Issues](https://github.com/SpechtLabs/tka/issues)
- [Documentation](https://tka.specht-labs.de)
- [Community Discussions](https://github.com/SpechtLabs/tka/discussions)
