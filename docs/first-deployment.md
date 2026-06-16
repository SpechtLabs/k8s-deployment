# Initial Setup (bootstrap)

## Base deployment

0. Obviously you have cloned the repository by this point and `cd`-ed into it.

1. install CRDs from the prometheus-operator project:

```bash
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/alertmanagerconfigs-crd.json
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/alertmanagers-crd.json
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/podmonitors-crd.json
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/probes-crd.json
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/prometheuses-crd.json
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/prometheusrules-crd.json
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/servicemonitors-crd.json
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/thanosrulers-crd.json
kubectl apply --server-side -f https://raw.githubusercontent.com/grafana/agent/main/operations/agent-static-operator/crds/monitoring.grafana.com_grafanaagents.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/grafana/agent/main/operations/agent-static-operator/crds/monitoring.grafana.com_integrations.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/grafana/agent/main/operations/agent-static-operator/crds/monitoring.grafana.com_logsinstances.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/grafana/agent/main/operations/agent-static-operator/crds/monitoring.grafana.com_metricsinstances.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/grafana/agent/main/operations/agent-static-operator/crds/monitoring.grafana.com_podlogs.yaml
```
to replace them (if you update the version of the prometheus-operator) use

```bash
kubectl replace -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/alertmanagerconfigs-crd.json
kubectl replace -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/alertmanagers-crd.json
kubectl replace -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/podmonitors-crd.json
kubectl replace -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/probes-crd.json
kubectl replace -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/prometheuses-crd.json
kubectl replace -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/prometheusrules-crd.json
kubectl replace -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/servicemonitors-crd.json
kubectl replace -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/jsonnet/prometheus-operator/thanosrulers-crd.json
```

2. Install ArgoCD

```bash
kubectl apply -f https://raw.githubusercontent.com/argoproj/argo-cd/master/manifests/crds/appproject-crd.yaml
kubectl apply -f https://raw.githubusercontent.com/argoproj/argo-cd/master/manifests/crds/applicationset-crd.yaml
kubectl apply -f https://raw.githubusercontent.com/argoproj/argo-cd/master/manifests/crds/application-crd.yaml
kubectl create namespace argocd
kustomize build --enable-alpha-plugins --enable-helm apps/argocd/cluster/<cluster> | kubectl apply -n argocd -f -
```

3. Install some important keys so the deployments work

```bash
./scripts/decrypt-secrets.sh
kubectl apply -f manifests/deploy-secrets/helm.secret.yaml -n argocd
./scripts/encrypt-secrets.sh
```

4. Apply the "meta" ArgoCD Application which will then do the rest

```bash
kubectl apply -f ./argo-apps/1-meta.yaml
```

## Initial contact with ArgoCD

By now, ArgoCD is deployed, but probably no Ingress yet. In order to access ArgoCD you

* have to obtain the auto generated default admin password
* port-forward the ArgoCD UI in order to access it

Lets do this:

1. Get the default password for ArgoCD

```bash
kubectl get secret -n argocd argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

2. Port-Forward

```bash
kubectl port-forward service/argocd-server -n argocd 8080:443
```

3. Access the webUI in your browser (and accept the insecure default certificate)

```
https://localhost:8080
```
