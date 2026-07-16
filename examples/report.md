# Kubernetes P0 Analysis — full-stack-fastapi

- Profile: `kubernetes-p0`
- Git ref: `4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8`
- Detected files: 10
- Schema version: 1.0

## 1. Components

### db

- Build: postgres:18
- Image: `postgres:18`
- Runtime: PostgreSQL
- Container port: 5432
- Environment: PGDATA, POSTGRES_PASSWORD, POSTGRES_USER, POSTGRES_DB
- Secret candidates: POSTGRES_PASSWORD
- Volumes: app-db-data -> /var/lib/postgresql/data/pgdata
- Health check: exec: CMD-SHELL pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}
- Kubernetes mapping: StatefulSet + headless Service (or external managed database)
- Unresolved: PVC size

### adminer

- Build: adminer
- Image: `adminer`
- Runtime: Adminer (DB admin UI)
- Container port: 8080
- Environment: ADMINER_DESIGN
- Kubernetes mapping: Deployment + ClusterIP Service (optional admin tool)

### prestart

- Build: backend/Dockerfile (context `.`)
- Image: `${DOCKER_IMAGE_BACKEND?Variable not set}:${TAG-latest}`
- Runtime: FastAPI
- Command: `bash scripts/prestart.sh`
- Environment: DOMAIN, FRONTEND_HOST, ENVIRONMENT, BACKEND_CORS_ORIGINS, SECRET_KEY, FIRST_SUPERUSER, FIRST_SUPERUSER_PASSWORD, SMTP_HOST, SMTP_USER, SMTP_PASSWORD, EMAILS_FROM_EMAIL, POSTGRES_SERVER, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, SENTRY_DSN
- Secret candidates: SECRET_KEY, FIRST_SUPERUSER_PASSWORD, SMTP_PASSWORD, POSTGRES_PASSWORD, SENTRY_DSN
- Kubernetes mapping: Job (pre-deploy / init hook)

### backend

- Build: backend/Dockerfile (context `.`)
- Image: `${DOCKER_IMAGE_BACKEND?Variable not set}:${TAG-latest}`
- Runtime: FastAPI
- Command: `fastapi run --workers 4` (workers=4)
- Container port: 8000
- Environment: DOMAIN, FRONTEND_HOST, ENVIRONMENT, BACKEND_CORS_ORIGINS, SECRET_KEY, FIRST_SUPERUSER, FIRST_SUPERUSER_PASSWORD, SMTP_HOST, SMTP_USER, SMTP_PASSWORD, EMAILS_FROM_EMAIL, POSTGRES_SERVER, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, SENTRY_DSN
- Secret candidates: SECRET_KEY, FIRST_SUPERUSER_PASSWORD, SMTP_PASSWORD, POSTGRES_PASSWORD, SENTRY_DSN
- Health check: HTTP GET /api/v1/utils/health-check/
- Kubernetes mapping: Deployment + ClusterIP Service

### frontend

- Build: frontend/Dockerfile (context `.`)
- Image: `${DOCKER_IMAGE_FRONTEND?Variable not set}:${TAG-latest}`
- Runtime: Nginx (static assets)
- Container port: 80
- Kubernetes mapping: Deployment + ClusterIP Service (static assets via Nginx)

## 2. Kubernetes workload mappings

| Component | Workload candidate | Rationale |
| --- | --- | --- |
| db | StatefulSet + headless Service (or external managed database) | Stateful component with persistent data; not a stateless Deployment. |
| adminer | Deployment + ClusterIP Service (optional admin tool) | Optional developer/admin UI; deploy only if needed, keep internal. |
| prestart | Job (pre-deploy / init hook) | Runs migrations and seeding then exits; a run-once workload, not long-running. |
| backend | Deployment + ClusterIP Service | Stateless HTTP application; horizontally scalable behind a Service. |
| frontend | Deployment + ClusterIP Service (static assets via Nginx) | Stateless static-asset server; horizontally scalable. |

## 3. Networking (ports & services)

| Subject | Value | Confidence | Kubernetes effect | Evidence |
| --- | --- | --- | --- | --- |
| db.container_port | 5432 | derived | db Service targetPort candidate | `compose.yml:4-4` ($.services.db.image) |
| adminer.container_port | 8080 | explicit | adminer Service targetPort candidate | `compose.yml:43-43` ($.services.adminer.labels[10]) |
| adminer.ingress_host | adminer.${DOMAIN?Variable not set} | derived | Ingress host rule candidate (currently routed by Traefik labels) | `compose.yml:36-36` ($.services.adminer.labels[3]) |
| backend.container_port | 8000 | derived | backend Service targetPort candidate | `compose.yml:113-113` ($.services.backend.healthcheck.test); `compose.yml:126-126` ($.services.backend.labels[3]) |
| backend.ingress_host | api.${DOMAIN?Variable not set} | derived | Ingress host rule candidate (currently routed by Traefik labels) | `compose.yml:128-128` ($.services.backend.labels[4]) |
| frontend.container_port | 80 | derived | frontend Service targetPort candidate | `frontend/nginx.conf:2-2` (listen); `compose.yml:156-156` ($.services.frontend.labels[3]) |
| frontend.ingress_host | dashboard.${DOMAIN?Variable not set} | derived | Ingress host rule candidate (currently routed by Traefik labels) | `compose.yml:158-158` ($.services.frontend.labels[4]) |

## 4. Persistent storage

- db.persistent_volume: `app-db-data` at `/var/lib/postgresql/data/pgdata` — PersistentVolumeClaim + volumeMount (StatefulSet volumeClaimTemplate candidate) (explicit); evidence `compose.yml:13-13` ($.services.db.volumes[0])

## 4b. Runtime dependencies (external services & datastores)

_No external runtime dependencies detected._

## 5. Configuration & Secrets

### ConfigMap candidates

| Key | Default | Evidence |
| --- | --- | --- |
| DOMAIN | localhost | `.env:4-4` (DOMAIN) |
| FRONTEND_HOST | http://localhost:5173 | `.env:9-9` (FRONTEND_HOST) |
| ENVIRONMENT | local | `.env:14-14` (ENVIRONMENT) |
| PROJECT_NAME | Full Stack FastAPI Project | `.env:16-16` (PROJECT_NAME) |
| STACK_NAME | full-stack-fastapi-project | `.env:17-17` (STACK_NAME) |
| BACKEND_CORS_ORIGINS | http://localhost,http://localhost:5173,https://localhost,https://localhost:5173,http://localhost.tiangolo.com | `.env:20-20` (BACKEND_CORS_ORIGINS) |
| FIRST_SUPERUSER | admin@example.com | `.env:22-22` (FIRST_SUPERUSER) |
| SMTP_HOST |  | `.env:26-26` (SMTP_HOST) |
| SMTP_USER |  | `.env:27-27` (SMTP_USER) |
| EMAILS_FROM_EMAIL | info@example.com | `.env:29-29` (EMAILS_FROM_EMAIL) |
| SMTP_TLS | True | `.env:30-30` (SMTP_TLS) |
| SMTP_SSL | False | `.env:31-31` (SMTP_SSL) |
| SMTP_PORT | 587 | `.env:32-32` (SMTP_PORT) |
| POSTGRES_SERVER | localhost | `.env:35-35` (POSTGRES_SERVER) |
| POSTGRES_PORT | 5432 | `.env:36-36` (POSTGRES_PORT) |
| POSTGRES_DB | app | `.env:37-37` (POSTGRES_DB) |
| POSTGRES_USER | postgres | `.env:38-38` (POSTGRES_USER) |
| DOCKER_IMAGE_BACKEND | backend | `.env:44-44` (DOCKER_IMAGE_BACKEND) |
| DOCKER_IMAGE_FRONTEND | frontend | `.env:45-45` (DOCKER_IMAGE_FRONTEND) |

### Secret candidates

| Key | Evidence |
| --- | --- |
| SECRET_KEY | `.env:21-21` (SECRET_KEY) |
| FIRST_SUPERUSER_PASSWORD | `.env:23-23` (FIRST_SUPERUSER_PASSWORD) |
| SMTP_PASSWORD | `.env:28-28` (SMTP_PASSWORD) |
| POSTGRES_PASSWORD | `.env:39-39` (POSTGRES_PASSWORD) |
| SENTRY_DSN | `.env:41-41` (SENTRY_DSN) |

## 6. Startup order & initialization

Overall order (derived):

1. database becomes ready
2. run DB migrations
3. create initial data
4. backend starts

- prestart.waits_for.db: `service_healthy` — ordering: gate via initContainer/readiness on the dependency (explicit); evidence `compose.yml:54-56` ($.services.prestart.depends_on.db)
- backend.waits_for.db: `service_healthy` — ordering: gate via initContainer/readiness on the dependency (explicit); evidence `compose.yml:86-88` ($.services.backend.depends_on.db)
- startup.migration: `alembic upgrade head` — run as a pre-deploy Job / initContainer before app starts (explicit); evidence `backend/scripts/prestart.sh:10-10` (alembic upgrade)
- startup.initial_data: `python app/initial_data.py` — run once after migrations (same Job), before serving traffic (explicit); evidence `backend/scripts/prestart.sh:13-13` (initial data)
- backend.waits_for.prestart: `service_completed_successfully` — app Deployment must start only after the init Job completes (explicit); evidence `compose.yml:89-90` ($.services.backend.depends_on.prestart)

## 7. Health checks

- db.health_exec: `CMD-SHELL pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}` — readiness probe exec.command candidate (explicit); evidence `compose.yml:6-11` ($.services.db.healthcheck)
- backend.health_path: `/api/v1/utils/health-check/` — readiness/liveness probe httpGet.path candidate (explicit); evidence `compose.yml:112-116` ($.services.backend.healthcheck)

## 8. Build-time constraints

- frontend.vite_api_url_binding: **build-time** — VITE_API_URL is baked into the image at build time; it cannot be changed via runtime env/ConfigMap. Rebuild per environment or introduce runtime config. (derived)
  - evidence: `compose.yml:149-149` ($.services.frontend.build.args[0]); `frontend/Dockerfile:15-15` (ARG); `frontend/src/main.tsx:16-16` (VITE_API_URL)

## 8b. Container image build & runtime

_No container image facts detected._

## 9. Unresolved operational inputs

_These are NOT decided from the repository. No default values were invented._

| Subject | Why unresolved | Input needed | Kubernetes effect |
| --- | --- | --- | --- |
| replica_count | desired availability/throughput is an operational decision, not in the repo | target replicas per Deployment (SLO / load expectations) | Deployment.spec.replicas |
| resource_requests_limits | repo contains no CPU/memory sizing information | measured or estimated CPU/memory per component | container resources.requests / resources.limits |
| ingress_class | cluster ingress controller is environment-specific and not declared in the repo | target IngressClass in the destination cluster | Ingress.spec.ingressClassName |
| horizontal_pod_autoscaler | no scaling policy is expressed in the repo | scaling metric and min/max replicas | HorizontalPodAutoscaler |
| pod_disruption_budget | availability tolerance during disruptions is an operational decision | minAvailable/maxUnavailable policy | PodDisruptionBudget |
| pvc_size | database volume size is not declared in the repo | expected data volume / growth for the database PVC | PersistentVolumeClaim.spec.resources.requests.storage |
| storage_class | storage backend is cluster-specific | target StorageClass in the destination cluster | PersistentVolumeClaim.spec.storageClassName |
| database_ha_and_backup | repo runs a single-container DB; HA and backup are operational policy | managed DB vs in-cluster HA, and backup/restore policy | operator/StatefulSet topology, backup CronJobs |

## 10. Warnings & unsupported constructs

Warnings:

- [compose_override_not_merged] additional compose file detected but NOT merged in kubernetes-p0; analysis is based on the primary compose file (`compose.override.yml`)
- [placeholder_secret] SECRET_KEY uses a placeholder value; must be overridden before deploy (`.env`)
- [placeholder_secret] FIRST_SUPERUSER_PASSWORD uses a placeholder value; must be overridden before deploy (`.env`)
- [placeholder_secret] POSTGRES_PASSWORD uses a placeholder value; must be overridden before deploy (`.env`)

_No unsupported constructs._

## Quick answers

1. **Components?** db, adminer, prestart, backend, frontend
2. **Which workloads?** db → StatefulSet + headless Service (or external managed database); adminer → Deployment + ClusterIP Service (optional admin tool); prestart → Job (pre-deploy / init hook); backend → Deployment + ClusterIP Service; frontend → Deployment + ClusterIP Service (static assets via Nginx)
3. **Ports/Services?** db:5432; adminer:8080; backend:8000; frontend:80
4. **What must persist?** app-db-data→/var/lib/postgresql/data/pgdata
5. **ConfigMap/Secret?** 19 ConfigMap keys, 5 secret keys
6. **Init first?** alembic upgrade head; python app/initial_data.py
7. **External runtime dependencies?** none
8. **HTTP context path?** / (root)
9. **Undecidable from repo?** 8 operational inputs (see section 9)

