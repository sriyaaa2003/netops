# Deploying NetOps

Tested against Docker Desktop's Kubernetes (context `docker-desktop`).

 1. Images

Already on Docker Hub: `sriya13/log-service:1.0`, `sriya13/anomaly-service:1.0`,
`sriya13/frontend:1.0`. Postgres uses the stock `postgres:16-alpine`, no
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
```

The secret isn't in git, create it once before the next step.

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

Persistence: `kubectl -n netops delete pod -l app=postgres`, wait for the
new pod, confirm row counts are unchanged.

Scaling: `kubectl -n netops scale deployment log-service --replicas=3`,
confirm the extra pods come up independently of everything else.
