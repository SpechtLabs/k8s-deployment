# Grafana Mimir

## Alertmanager
Deploy AlertManager config:

```bash
sops -d -i alertmanager.yaml
kubectl port-forward -n observability service/mimir-nginx 8080:80
mimirtool alertmanager load alertmanager.yaml --address=http://localhost:8080 --id "anonymous"
git restore . alertmanager.yaml
```