# StaticPages Helm Chart

This Helm Chart simplifies deploying [Static Pages](https://github.com/SpechtLabs/StaticPages) on Kubernetes, offering secure hosting and preview environments for static websites with minimal operational effort.

## Features

- Seamless integration with any static site generator
- Secure, GitHub OIDC-based access control
- Fast, parallel file uploads with detailed summaries
- Support for production and preview builds on per-branch or per-commit basis
- Built-in Prometheus metrics (optional)
- Easy integration with [StaticPages GitHub Action](https://github.com/SpechtLabs/StaticPages-Upload)

---

## Quick Start

### 1. Install the Chart

```bash
helm repo add spechtlabs https://charts.specht-labs.de
helm install staticpages spechtlabs/staticpages -n static-pages --create-namespace -f my-values.yaml
```

### 2. Required Secrets

Create a secret containing your S3 credentials, typically managed via ksops and kustomize:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: s3-credentials
  namespace: static-pages
type: Opaque
stringData:
  app-id: <your-app-id>
  s3-secret: <your-base64-encoded-s3-secret>
```

Encrypt this secret with sops and deploy via ksops.

## Key Configuration

| Key                                  | Description                                                          |
|--------------------------------------|----------------------------------------------------------------------|
| `staticpages.nameOverride`           | Override the name used for all resources                             |
| `staticpages.replicaCount`           | Number of backend replicas                                           |
| `staticpages.image.repository`       | Image repository to use (default: `ghcr.io/spechtlabs/staticpages`)  |
| `staticpages.image.tag`              | Image tag to use (default: `Chart.appVersion`)                       |
| `staticpages.env`                    | List of environment variables to set in the container                |
| `staticpages.extraEnvFrom`           | List of sources (e.g., secrets) to import environment variables from |
| `staticpages.ingress.enabled`        | Enable ingress for the service                                       |
| `configs.pages[].domain`             | Domain name to serve                                                 |
| `configs.pages[].bucket`             | Configuration for the S3 bucket (region, URL, name, credentials)     |
| `configs.pages[].proxy`              | Configuration for the proxy (URL, path, fallback file, search path)  |
| `configs.pages[].git.repository`     | GitHub repository allowed to upload to the domain                    |
| `configs.pages[].git.mainBranch`     | Main branch used for production deployments                          |
| `configs.pages[].preview.enabled`    | Enable preview builds (subdomains for branches/commits)              |

### Example Domain Configuration

```yaml
configs:
  pages:
    - domain: example.com
      bucket:
        region: eu-central-003
        url: <https://s3.eu-central-003.backblazeb2.com>
        name: my-static-site
        applicationId: ENV(APPLICATION_ID)
        secret: ENV(S3_SECRET)
      proxy:
        url: <https://f003.backblazeb2.com>
        path: file/my-static-site
        notFound: 404.html
        searchPath:
          - /index.html
      git:
        provider: github
        repository: octocat/my-website
        mainBranch: main
      preview:
        enabled: true
        branch: true
```

### Ingress Example

```yaml
ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/proxy-body-size: "0"
  hosts:
    - host: staticpages.example.com
      paths:
        - path: /
          pathType: ImplementationSpecific
  tls:
    - secretName: staticpages-tls
      hosts:
        - staticpages.example.com
```
