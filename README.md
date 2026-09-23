# NetOps: ML-Based Network Log Anomaly Detection

Cloud Provisioning and Deployment / The Business Case for Cloud Computing, course assignment.

 1. Description of the software

Network test rigs produce large volumes of severity tagged log lines, INFO, WARN, ERROR, CRITICAL. Most of it is normal chatter, and the few components that are actually degrading get buried in it. Fixed rules like alert after N errors do not work well since different components have different normal behavior.

This project uses an Isolation Forest instead. It refits on each batch of logs across all components severity counts, and flags the components that look different from the rest of that batch, with no hand labeled normal data needed.

Components:
- log-service, Node.js and Express, parses raw log lines into structured records, stores them in Postgres, REST API.
- anomaly-service, Python and Flask, pulls recent logs from log-service over REST, builds severity counts per component, runs the Isolation Forest, stores flagged components, REST API.
- frontend, static HTML served by nginx, the only part a browser talks to directly, generates sample logs, submits them, triggers analysis, shows flagged anomalies.
- Postgres, stores both services data, logs and anomalies, persistent storage.

Log data is generated synthetically by the frontend instead of a real dataset, so the demo can be repeated on demand for the video walkthrough.

 2. Software architecture design


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


Architecture principles applied:
- Reverse proxy, nginx is the single public entry point, the browser never contacts the backend services directly.
- Service discovery via Kubernetes DNS, services call each other by name, such as http log-service:4000.
- Each service writes only its own table in Postgres.
- Externalized configuration, database credentials come from a Kubernetes Secret and environment variables

Communication pattern:
- The browser only talks to the frontend, which proxies api calls to the backend services by name.
- anomaly-service calls log-service REST API directly to fetch recent logs before fitting the model, this is the required microservice to microservice call.
- Both backend services connect to Postgres, each on its own table.
- log-service, anomaly-service, and Postgres have no external Service, none of them are reachable from outside the cluster.

3. Benefits, challenges, and security

Benefits:
- Isolation Forest needs no labeled training data.
- It refits per batch, so normal adapts to whichever components are currently reporting.
- Each service scales and fails independently, verified by load testing log-service 

Challenges and mitigations:
- Small batches give noisy component counts, it mitigated by anomaly-service refusing to analyze batches under a minimum size.
- One repeated error looks the same as many distinct ones.
- Kubernetes does not guarantee Postgres is ready before the other two services start, mitigated by both retrying their database connection on a delay loop, with readiness probes keeping them out of service until connected.
- nginx used to resolve backend hostnames once at startup, so a DNS hiccup during pod boot could crash loop the frontend, fixed with a templated nginx config that resolves again on every request.

Security:
- Database credentials are a Kubernetes Secret via secretKeyRef
- Limitation, Kubernetes Secrets are only base64 encoded..
- Not implemented, no authentication on any REST API, and traffic between services is plain HTTP

