# k8s-deployment

[![Lint](https://github.com/SpechtLabs/k8s-deployment/actions/workflows/lint.yaml/badge.svg)](https://github.com/SpechtLabs/k8s-deployment/actions/workflows/lint.yaml)
[![CodeQL](https://github.com/SpechtLabs/k8s-deployment/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/SpechtLabs/k8s-deployment/actions/workflows/github-code-scanning/codeql)

This is the configuration of my playground Kubernetes Cluster.

## Repository Structure

- **.devcontainer/**: Contains the development container configuration.
  - `devcontainer.json`: Configuration for the development container.
  - `Dockerfile`: Dockerfile for the development container.

- **.github/**: GitHub-specific configurations and workflows.
  - `auto_assign.yml`: Configuration for auto-assigning issues and pull requests.
  - `workflows/`: Contains GitHub Actions workflows.

- **.vscode/**: Visual Studio Code settings.
  - `settings.json`: Settings for Visual Studio Code.

- **argo-apps/**: Contains Argo CD application configurations.
  - `specht-labs/`: Configuration for the `specht-labs` environment.
  - `labk3s/`: Configuration for the `labk3s` environment.

- **charts/**: Helm charts for various applications.
  - `cert-checker/`: Helm chart for cert-checker.
  - `chaos-mesh/`: Helm chart for chaos-mesh.
  - `cilium/`: Helm chart for cilium.
  - `grafana-agent-operator/`: Helm chart for grafana-agent-operator.
  - `grafana-promtail/`: Helm chart for grafana-promtail.
  - `grafana-vulture/`: Helm chart for grafana-vulture.
  - `hcloud-ccm/`: Helm chart for hcloud-ccm.
  - `ingress-nginx/`: Helm chart for ingress-nginx.
  - `node-exporter/`: Helm chart for node-exporter.

- **docs/**: Documentation for the repository.
  - `age-secrets.md`: Documentation for managing age secrets.
  - `chart-deployments.md`: Documentation for deploying Helm charts.
  - `first-deployment.md`: Guide for the first deployment.
  - `working-with-argocd.md`: Guide for working with Argo CD.

- **hack/**: Scripts and utilities for development and maintenance.

- **kustomize/**: Kustomize configurations.
  - `bases/`: Base configurations for Kustomize.

- **manifests/**: Kubernetes manifests.

## Getting Started

To get started with this repository, clone it and follow the instructions in the documentation files located in the `docs/` directory.

## Contributing

Contributions are welcome! Please see the `CODEOWNERS` file for information on who to contact for specific areas of the repository.
