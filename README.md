# NetOps: ML-Based Network Log Anomaly Detection

Cloud Provisioning and Deployment / The Business Case for Cloud Computing, course assignment.

## 1. Description of the software

Network test rigs produce large volumes of severity tagged log lines, INFO, WARN, ERROR, CRITICAL. Most of it is normal chatter, and the few components that are actually degrading get buried in it. Fixed rules like alert after N errors do not work well since different components have different normal behavior.

This project uses an Isolation Forest instead. It refits on each batch of logs across all components severity counts, and flags the components that look different from the rest of that batch, with no hand labeled normal data needed.

Components:
- log-service, Node.js and Express, parses raw log lines into structured records, stores them in Postgres, REST API.
- anomaly-service, Python and Flask, pulls recent logs from log-service over REST, builds severity counts per component, runs the Isolation Forest, stores flagged components, REST API.
- frontend, static HTML served by nginx, the only part a browser talks to directly, generates sample logs, submits them, triggers analysis, shows flagged anomalies.
- Postgres, stores both services data, logs and anomalies, persistent storage.

Log data is generated synthetically by the frontend instead of a real dataset, so the demo can be repeated on demand for the video walkthrough.

## 2. Software architecture design

```
                       +---------------------------+
   Browser  ---------->|   frontend (nginx)         |  LoadBalancer - the ONLY
                       |   static HTML/JS + reverse |  externally reachable
                       |   proxy at /api/*          |  Service in the cluster
                       +-----------+---------------+
                                   |  ClusterIP-only from here on
                    +--------------+---------------+
                    v                               v
        +------------------------+        +---------------------------+
        |  log-service (Node)     |<------|  anomaly-service (Flask)   |
        |  POST/GET /logs         |  GET   |  POST /analyze            |
        |  GET /logs/:id          |  /logs |  GET /anomalies           |
        |  GET /health            |        |  GET /health              |
        +-----------+-------------+        +-------------+-------------+
                    |                                    |
                    +-----------------+------------------+
                                     v
                          +-----------------------+
                          |  Postgres (1 replica)  |
                          |  logs, anomalies tables|
                          +-----------------------+
```

Component to Kubernetes object mapping:

| Component | Deployment | Service (type) | Other objects |
|---|---|---|---|
| Postgres | postgres, 1 replica, Recreate strategy | postgres, ClusterIP | postgres-pvc, postgres-credentials Secret |
| log-service | log-service | log-service, ClusterIP | log-service-hpa |
| anomaly-service | anomaly-service | anomaly-service, ClusterIP | anomaly-service-hpa |
| frontend | frontend | frontend, LoadBalancer | frontend-hpa |

All objects live in the netops namespace.

Architecture principles applied:
- Single responsibility, ingestion, ML analysis, and presentation are three separate services, each deployed and scaled on its own.
- Reverse proxy, nginx is the single public entry point, the browser never contacts the backend services directly.
- Service discovery via Kubernetes DNS, services call each other by name, such as http log-service colon 4000, instead of pod IPs or a custom registry.
- Database per owner, each service writes only its own table in Postgres.
- Externalized configuration, database credentials come from a Kubernetes Secret and environment variables, not hardcoded.

Communication pattern:
- The browser only talks to the frontend, which proxies api calls to the backend services by name.
- anomaly-service calls log-service REST API directly to fetch recent logs before fitting the model, this is the required microservice to microservice call.
- Both backend services connect to Postgres, each on its own table.
- log-service, anomaly-service, and Postgres have no external Service, none of them are reachable from outside the cluster.

## 3. Benefits, challenges, and security

Benefits:
- Isolation Forest needs no labeled training data.
- It refits per batch, so normal adapts to whichever components are currently reporting.
- Each service scales and fails independently, verified by load testing log-service until it autoscaled from one to five replicas, without affecting anomaly-service or postgres.

Challenges and mitigations:
- Small batches give noisy per component counts, mitigated by anomaly-service refusing to analyze batches under a minimum size.
- Severity counts alone miss message content drift, one repeated error looks the same as many distinct ones, not solved here, noted as future work.
- Kubernetes does not guarantee Postgres is ready before the other two services start, mitigated by both retrying their database connection on a delay loop, with readiness probes keeping them out of service until connected.
- nginx used to resolve backend hostnames once at startup, so a DNS hiccup during pod boot could crash loop the frontend, fixed with a templated nginx config that resolves again on every request.

Security:
- Database credentials are a Kubernetes Secret via secretKeyRef, not hardcoded, created directly in the cluster rather than committed to git.
- Limitation, Kubernetes Secrets are only base64 encoded, not encrypted, a production deployment would need encryption at rest and a real secrets manager, most of which run outside the cluster entirely.
- log-service and anomaly-service are ClusterIP only, not reachable from outside the cluster, though nothing stops pod to pod traffic inside the cluster since there is no network policy defined.
- log-service reports malformed input lines instead of silently storing them, but it does not check that severity is one of the four expected values, so an unexpected value gets stored and silently dropped during analysis.
- Not implemented, no authentication on any REST API, and traffic between services is plain HTTP, not TLS, both needed before any real deployment.

## Compliance checklist

1. Deployable on Kubernetes, yes, see kubernetes-config.
2. At least two microservice types plus a database, yes, log-service, anomaly-service, frontend, plus Postgres.
3. Each microservice implements a REST API, log-service and anomaly-service do. Frontend is the browser facing entry point, static files and reverse proxy, not a REST API itself.
4. Accessible from outside Kubernetes via a browser, yes, frontend is LoadBalancer, see Documentation DEPLOY.md.
5. All microservices horizontally scalable independently, yes, each has its own Deployment and HorizontalPodAutoscaler, verified live by load testing log-service to a real autoscale event, one to five replicas.
6. Images pushed to Docker Hub, done, see Documentation DEPLOY.md.
7. Database running as a separate microservice, yes, Postgres.
8. Persistent storage across restarts, yes, PersistentVolumeClaim, verified by deleting the postgres pod and confirming row counts survived.
9. Database not required to scale, correct, Postgres runs as a single replica by design.
