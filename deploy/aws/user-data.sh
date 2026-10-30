#!/bin/bash
# NetOps on one AWS EC2 instance: Ubuntu 24.04 + k3s (a real, small Kubernetes).
# The three images are built on the instance from the GitHub repo at the exact commit that was tested.
# Paste this whole file into "User data" when you launch the instance.
# Log: /var/log/netops-setup.log     Re-run after a failure: sudo bash /opt/netops-setup.sh
# One-command checks afterwards: sudo bash /opt/netops-verify.sh

set -euxo pipefail
exec > >(tee -a /var/log/netops-setup.log) 2>&1
trap 'echo "NETOPS SETUP FAILED near line $LINENO"' ERR
export DEBIAN_FRONTEND=noninteractive
mkdir -p /opt
cp "$0" /opt/netops-setup.sh || true

REPO_URL="https://github.com/sriyaaa2003/netops.git"
COMMIT="0363da3"    # the commit that was tested on Docker Desktop on 2026-10-30

# 1. Swap file, so building the images cannot run the machine out of memory
if ! swapon --show | grep -q /swapfile; then
  [ -f /swapfile ] || fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
fi
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab

# 2. Tools
apt-get update -y
apt-get install -y docker.io git curl openssl python3
systemctl enable --now docker

# 3. Kubernetes (k3s). Traefik is switched off because it would take port 80 from the NetOps frontend.
if ! command -v k3s >/dev/null 2>&1; then
  curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik" sh -
fi
until k3s kubectl get nodes 2>/dev/null | grep -q " Ready"; do sleep 5; done

# 4. Get the code at the tested commit and build the three images
[ -d /opt/netops/.git ] || git clone "$REPO_URL" /opt/netops
cd /opt/netops
git fetch -q origin
git checkout -q "$COMMIT"
git log -1 --format='building commit %h: %s'
for svc in log-service anomaly-service frontend; do
  docker build -t "netops/${svc}:aws" "Containers/${svc}"
  docker save "netops/${svc}:aws" | k3s ctr images import -
done

# 5. Point the manifests at the local images (no Docker Hub needed)
mkdir -p /opt/netops-k8s
cp kubernetes-config/*.yaml /opt/netops-k8s/
sed -i -e 's#sriya13/\([a-z-]*\):1\.0#netops/\1:aws#' \
       -e 's#imagePullPolicy: Always#imagePullPolicy: IfNotPresent#' /opt/netops-k8s/*.yaml
grep -h "image:" /opt/netops-k8s/*.yaml

# 6. Create the two secrets with random values (xtrace is off so they never reach the log), then deploy
set +x
k3s kubectl apply -f /opt/netops-k8s/00-namespace.yaml
k3s kubectl -n netops get secret postgres-credentials >/dev/null 2>&1 || \
  k3s kubectl -n netops create secret generic postgres-credentials \
    --from-literal=POSTGRES_USER=netops_user \
    --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 16)" \
    --from-literal=POSTGRES_DB=netops
k3s kubectl -n netops get secret netops-api-key >/dev/null 2>&1 || \
  k3s kubectl -n netops create secret generic netops-api-key \
    --from-literal=API_KEY="$(openssl rand -hex 24)"
set -x
k3s kubectl apply -f /opt/netops-k8s/

# 7. The one-command checks (written here so there is nothing else to paste)
cat > /opt/netops-verify.sh <<'VERIFY'
#!/bin/bash
# NetOps checks on the AWS instance. Run:  sudo bash /opt/netops-verify.sh
K="k3s kubectl -n netops"
count() { $K exec deploy/postgres -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c "select count(*) from logs"'; }

echo "== 1. pods"; $K get pods
echo "== 2. front page"; curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost/
echo "== 3. a call straight to a service without the API key (expect 401)"
$K exec deploy/frontend -- sh -c 'wget -S -q -O- "http://log-service:4000/logs?limit=1" 2>&1 | head -1'

echo "== 4. load the real 4,000-line BlueGene/L sample through the page's own API"
curl -s http://localhost/bgl_sample.log -o /tmp/bgl_sample.log
python3 -c "import json;print(json.dumps({'raw':open('/tmp/bgl_sample.log',encoding='utf-8',errors='replace').read()}))" > /tmp/payload.json
curl -s -X POST -H 'Content-Type: application/json' --data-binary @/tmp/payload.json http://localhost/api/logs; echo

echo "== 5. the three detectors"
for d in boosting isolation_forest error_count; do
  curl -s -X POST "http://localhost/api/analyze?detector=$d" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('$d ->', d['detector'], '| node cards', d['components_considered'], '| flagged', len(d['flagged']), '| with alert label', d['flagged_with_alert'])"
done

echo "== 6. persistence: delete the database pod and compare row counts"
before=$(count); echo "rows before: $before"
$K delete pod -l app=postgres --wait=true
$K rollout status deploy/postgres --timeout=300s
sleep 15
after=$(count); echo "rows after:  $after"
[ "$before" = "$after" ] && echo "PERSISTENCE OK" || echo "ROW COUNT CHANGED"

echo "== 7. scaling: log-service to 3 copies, then back to 1"
$K scale deploy/log-service --replicas=3
$K rollout status deploy/log-service --timeout=300s
$K get pods -l app=log-service
$K scale deploy/log-service --replicas=1

echo "== 8. autoscalers (CPU figures mean metrics are flowing)"; $K get hpa
echo "NETOPS VERIFY DONE"
VERIFY

# 8. Wait until everything is up, then check the front page from the instance itself
for d in postgres log-service anomaly-service frontend; do
  k3s kubectl -n netops rollout status "deploy/${d}" --timeout=600s
done
k3s kubectl -n netops get pods,svc,hpa
sleep 5
curl -s -o /dev/null -w "front page on this instance: HTTP %{http_code}\n" http://localhost/
echo "NETOPS SETUP DONE"
