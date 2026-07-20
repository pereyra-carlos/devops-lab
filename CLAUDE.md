# CLAUDE.md — lab-devops

Lab de práctica DevOps punta a punta para prep de entrevistas (Carlos). Basado en un take-home real.

## Qué es

App `ipecho` (FastAPI) que devuelve la IP de origen del cliente + `/health` + `/ready`, con pipeline CI/CD completo: lint → test → build → Trivy scan → push Docker Hub → helm lint → deploy → smoke test.

## Stack

- **App**: Python 3.12 + FastAPI + uvicorn. Código en `app/`. Sin comentarios (convención Carlos).
- **Container**: Dockerfile multi-stage, `python:3.12-slim`, usuario no-root uid 1000.
- **Helm**: chart en `charts/ipecho` (Deployment, Service, Ingress opcional). Probes + resources + securityContext configurables por `values.yaml`.
- **CI**: GitHub Actions (`.github/workflows/ci.yaml`). Deploy CD = push con Helm (no GitOps).
- **Registry**: Docker Hub `sauay/ipecho`, tag por commit SHA.
- **Deploy target**: K3s local (.51/.52). CI smoke test corre en kind efímero.

## Decisiones tomadas

- CI: GitHub Actions (lo más pedido en entrevistas).
- CD: push `helm upgrade` (simple y directo). GitOps/ArgoCD queda como posible fase futura.
- App stack: Python/FastAPI.
- Dominio objetivo: `devops-lab.pereyra.ar` (Cloudflare Tunnel).

## Fase 2 (pendiente)

- Deploy real a K3s (self-hosted runner o manual `make deploy`) + Cloudflare Tunnel → `devops-lab.pereyra.ar`.
- Geolocalización IP (Cloudflare `CF-IPCountry`/`CF-Connecting-IP` o GeoLite2) + `/metrics` Prometheus.
- Dashboard Grafana Geomap (mapa de IPs) + log de IPs, sobre el Grafana local de K3s. Publicar dashboard/repo público (como `artesanias-demo-sim`).

## Comandos

```bash
make install        # deps runtime + dev
make test           # pytest
make lint           # ruff
make run            # uvicorn :8080
make docker-build TAG=x
make helm-lint
make deploy TAG=x   # namespace staging
make smoke
```

## Convenciones

- Repo git propio (init local); pensado para publicar en GitHub (Actions).
- Sin secrets hardcodeados: Docker Hub token en GitHub Secrets; secrets de app documentados en README.
