# Deploying NetOps

Verified on Docker Desktop's Kubernetes (context `docker-desktop`) on 30 October 2026, with images built from this repository.

 1. Images

The images on Docker Hub (`sriya13/log-service:1.0`, `sriya13/anomaly-service:1.0`, `sriya13/frontend:1.0`) predate the
real-log version: rebuild and push them (below) before deploying. Postgres uses the stock `postgres:16-alpine`, no
build needed. 

To rebuild and push:


docker build -t sriya13/log-service:1.0 Containers/log-service
docker build -t sriya13/anomaly-service:1.0 Containers/anomaly-service
docker build -t sriya13/frontend:1.0 Containers/frontend
docker push sriya13/log-service:1.0
docker push sriya13/anomaly-service:1.0
docker push sriya13/frontend:1.0


All three Deployments have `imagePullPolicy: Always`, so a
`kubectl rollout restart` after pushing is enough to pick up a new image
under the same `:1.0` tag, no version bump needed.

 2. Namespace and secret

```
kubectl apply -f kubernetes-config/00-namespace.yaml

kubectl -n netops create secret generic postgres-credentials \
  --from-literal=POSTGRES_USER=netops_user \
  --from-literal=POSTGRES_PASSWORD=<pick-your-own-password> \
  --from-literal=POSTGRES_DB=netops

kubectl -n netops create secret generic netops-api-key   --from-literal=API_KEY=$(openssl rand -hex 24)
```

The secrets aren't in git, create them once before the next step. `netops-api-key` is the shared secret every service checks in the
`X-API-Key` header; nginx adds it for the browser, so it never reaches the page.

## 3. Everything else

```
kubectl apply -f kubernetes-config/02-postgres-pvc.yaml
kubectl apply -f kubernetes-config/03-postgres-deployment.yaml
kubectl apply -f kubernetes-config/04-postgres-service.yaml
kubectl apply -f kubernetes-config/05-log-service-deployment.yaml
kubectl apply -f kubernetes-config/06-log-service-service.yaml
kubectl apply -f kubernetes-config/07-anomaly-service-deployment.yaml
kubectl apply -f kubernetes-config/08-anomaly-service-service.yaml
kubectl apply -f kubernetes-config/09-frontend-deployment.yaml
kubectl apply -f kubernetes-config/10-frontend-service.yaml
kubectl apply -f kubernetes-config/11-hpa.yaml

kubectl -n netops get pods
```

Wait for all four pods to reach `1/1 Running`.

## 4. Access it

The frontend Service is `type: LoadBalancer`. Docker Desktop auto-publishes
LoadBalancer Services straight to localhost, no port-forward needed:

```
kubectl -n netops get svc frontend
```

Once `EXTERNAL-IP` is populated (a few seconds), open `http://localhost/`.
On a real cloud cluster this is also how you'd expose it, the cloud
provider assigns a real external IP the same way.

## 5. Verify

```
curl http://localhost/api/logs?limit=1
curl -X POST http://localhost/api/analyze
curl http://localhost/api/anomalies
```

Load the real sample first (the web page's first button does this), then pick a detector with
`curl -X POST "http://localhost/api/analyze?detector=error_count"` (or `isolation_forest`, `boosting`). The reply names
the detector that ran. A request without the `X-API-Key` header sent straight to a service (not through the frontend)
returns 401.

Persistence: `kubectl -n netops delete pod -l app=postgres`, wait for the
new pod, confirm row counts are unchanged.

Scaling: `kubectl -n netops scale deployment log-service --replicas=3`,
confirm the extra pods come up independently of everything else.

## 6. On AWS (EC2 with k3s)

`deploy/aws/user-data.sh` sets up Ubuntu 24.04 with k3s on one EC2 instance, builds the three images from this repository at a pinned commit, creates the two secrets with random values and applies the manifests. Paste it into the User data box when launching the instance (t3.medium or larger, 20 GiB disk, a security group that allows HTTP only from your own IP). When `/var/log/netops-setup.log` ends with `NETOPS SETUP DONE`, run `sudo bash /opt/netops-verify.sh` on the instance for the checks. Terminate the instance when you are finished, to stop the charges.
