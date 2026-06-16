# Adding Grafana Dashboards to the grafana using prometheus-operator

1. Download Dashboard.json:

```bash
curl -o argocd.json -L https://raw.githubusercontent.com/argoproj/argo-cd/master/examples/dashboard.json 
```

2. Add Dashboard.json as configmap:

```bash
kubectl -n monitoring create cm grafana-argocd --from-file=argocd.json
```

3. Add Label, so the sidecar will pick it up:

```bash
kubectl -n monitoring label cm grafana-argocd grafana_dashboard=ArgoCD
```

4. Dump it back out to yaml:

```bash
kubectl -n monitoring get cm grafana-argocd -oyaml > argocd-dashboard.yaml
```

5. Delete the dashboard.json and edit the yaml file, so you can apply it with `kubectl apply -f` with no fuzz
