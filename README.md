# lab-devops — ipecho

Web app mínima que devuelve la **IP de origen del cliente**, con un pipeline CI/CD de punta a punta: lint → tests → build → scan → push → helm lint → deploy → smoke test.

Pensado como lab de práctica DevOps para entrevistas.

## Documentation

Detailed technical write-ups (PDF, English):

- [CI/CD Pipeline](docs/01-cicd-pipeline.pdf) — every pipeline stage, secrets, and the real troubleshooting story
- [The Python Application](docs/02-python-application.pdf) — endpoints, client-IP resolution, geolocation, metrics
- [The Helm Chart](docs/03-helm-chart.pdf) — values, security hardening, and the GeoLite2 init container

## App

FastAPI con tres endpoints:

| Endpoint  | Descripción |
|-----------|-------------|
| `GET /`       | JSON: IP de origen + país + ciudad + lat/lon + pod. Texto plano con `Accept: text/plain`. |
| `GET /myip`   | **IP cruda en texto plano** (`curl devops-lab.pereyra.ar/myip`). |
| `GET /version`| Build info: versión + commit SHA + build time (horneados en la imagen). |
| `GET /health` | Liveness. |
| `GET /ready`  | Readiness. |
| `GET /stats`  | Puntos geolocalizados agregados (alimenta el mapa de Grafana). |
| `GET /log`    | Últimas 100 IPs vistas (IP, país, ciudad, lat/lon, timestamp). |
| `GET /metrics`| Métricas Prometheus (`ipecho_requests_total{country}`). |

**Resolución de la IP** (orden): `CF-Connecting-IP` → `True-Client-IP` → `X-Forwarded-For` → `X-Real-IP` → conexión TCP.

> Detrás de Traefik el `X-Forwarded-For` que mande un cliente no confiable **se descarta** (Traefik lo pisa con el hop interno), por eso `CF-Connecting-IP` va primero: es el header que Cloudflare setea con la IP real del cliente y que el proxy deja pasar. Es el punto fino de "conseguir la IP real detrás de un balanceador".

**Geolocalización**: si hay una base **GeoLite2-City** (`GEOIP_DB`), la app resuelve país + ciudad + lat/lon. Si no, cae al país por `CF-IPCountry`. La base no se commitea ni se hornea en la imagen: en el cluster la baja un **initContainer** con la license key de MaxMind desde un Secret; en local, `make geoip-local`.

## Correr local

```bash
make install          # deps de runtime + dev
make run              # uvicorn en :8080
curl localhost:8080/
curl -H 'Accept: text/plain' localhost:8080/
```

Con Docker:

```bash
make docker-build TAG=dev
docker run -p 8080:8080 ipecho:dev
```

## Tests y lint

```bash
make test             # pytest
make lint             # ruff (reemplazo moderno de flake8)
```

## Docker

`Dockerfile` multi-stage:
- **builder**: instala deps en un venv aislado.
- **runtime**: `python:3.12-slim`, usuario no-root (uid 1000), `HEALTHCHECK`, sin toolchain de build.

`.dockerignore` excluye tests, charts, docs y artefactos.

## Helm

Chart en `charts/ipecho`:
- Deployment + Service (+ Ingress opcional).
- Probes liveness/readiness/startup **configurables** por `values.yaml`.
- Resource requests/limits con defaults sensatos.
- `securityContext` endurecido: no-root, `readOnlyRootFilesystem`, drop de capabilities, seccomp.

```bash
make helm-lint
helm template ipecho charts/ipecho              # render local
make deploy TAG=<sha>                           # a namespace staging
```

### Secrets (sin hardcodear)

El chart **no** trae secrets. Para inyectar config sensible, opciones documentadas:
- **env plano** vía `values.yaml` (`env:`) — solo no-sensible.
- **k8s Secret** referenciado con `envFrom`/`valueFrom` (ampliar template).
- **sealed-secrets** (Bitnami) para versionar el secret cifrado en git.
- **External Secrets Operator** apuntando a un backend (Vault, AWS SM).

Para este lab no hay secrets de app; el único secreto es el token de Docker Hub, que vive en los **GitHub Secrets** (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`).

## CI (GitHub Actions)

`.github/workflows/ci.yaml`, corre en push a `main` y en PR:

1. **test** — `ruff check` + `pytest`.
2. **build** — build de la imagen taggeada con el **commit SHA**, scan de vulnerabilidades con **Trivy** (falla en `CRITICAL`), genera **SBOM** (CycloneDX) como artefacto, push a **Docker Hub** (`sauay/ipecho`) solo en push a `main`.
3. **helm-lint** — `helm lint`.
4. **deploy-smoke** — levanta un cluster **kind** efímero, carga la imagen, `helm upgrade --install` al namespace `staging`, y corre el **smoke test** (`curl -f /health` + `/ready`).
5. **notify** — reporta resultado; notificación opcional a Slack si `vars.SLACK_ENABLED == 'true'`.

El smoke test corre en kind (efímero y portable en el runner cloud). El deploy al **K3s real** se hace aparte (ver Roadmap).

### Secrets requeridos en GitHub

| Nombre | Uso |
|--------|-----|
| `DOCKERHUB_USERNAME` | login Docker Hub |
| `DOCKERHUB_TOKEN`    | token de acceso Docker Hub |
| `SLACK_WEBHOOK_URL`  | (opcional) notificación |

## Imagen publicada

`docker.io/sauay/ipecho` — tag por commit SHA + `latest` en `main`.

## Deploy a K3s + mapa (fase 2)

### App al cluster

```bash
export MAXMIND_LICENSE_KEY=<tu-license-key>     # cuenta gratis en maxmind.com
make docker-build TAG=<sha> && docker tag ipecho:<sha> sauay/ipecho:<sha> && docker push sauay/ipecho:<sha>
make k3s-deploy TAG=<sha>       # crea ns + secret geoip, ingress traefik, initContainer baja GeoLite2
```

### Grafana propio del lab (mapa de IPs)

Grafana dedicado, provisionado como código (`grafana/`): datasource **Infinity** apuntando a los endpoints JSON de la app + dashboard con panel **Geomap** (markers por país vía gazetteer) y tabla de log. Acceso anónimo (Viewer) para dejarlo público.

```bash
make grafana-deploy             # crea secret admin + configmaps + deploy
# NodePort :30897  → dashboard "ipecho — mapa de IPs"
```

El dashboard vive versionado en `grafana/dashboards/ipecho.json`, así que es reproducible y publicable (como el lab de artesanías).

### Acceso público (Cloudflare Tunnel)

Expuesto vía Cloudflare Tunnel `cf-infra` (proxied, HTTPS):

| URL | Destino |
|-----|---------|
| `https://devops-lab.pereyra.ar` | app ipecho (Traefik `:80` → Ingress) |
| `https://devops-lab.pereyra.ar/myip` | tu IP pública en texto plano |
| `https://devops-lab-grafana.pereyra.ar` | dashboard Grafana (mapa de IPs) |

Al pasar por Cloudflare, la app recibe la IP real en `CF-Connecting-IP` y el país en `CF-IPCountry`, así que cualquier request entra al mapa con su ubicación real. `cloudflared` preserva el `Host` original → Traefik enruta al Ingress sin config extra. Grafana usa un subdominio de un solo nivel (`devops-lab-grafana`) porque el Universal SSL gratis no cubre sub-subdominios.

## Limitaciones conocidas

- **Estado en memoria**: `/stats` y `/log` viven en memoria del pod, así que en K3s corre con `replicaCount: 1` para que el mapa sea consistente. Escalar horizontal requiere un store compartido (Redis/Postgres) — es el próximo paso natural y un buen tema de entrevista ("tu app tiene estado, ¿cómo la escalás?").
- **GeoLite2 en anycast**: IPs anycast (ej. `1.1.1.1`) no tienen ubicación en la base → caen a `ZZ`/`null` (esperado).

## Roadmap (fase 3, ideas)

- [ ] Store compartido (Redis) para volver la app stateless y escalar réplicas.
- [ ] Self-hosted GitHub runner para que el CI despliegue directo al K3s (CD real end-to-end).
- [ ] Migrar el push-Helm a **GitOps con ArgoCD**.
