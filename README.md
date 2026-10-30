# NetOps: log anomaly detection on Kubernetes, tested on real supercomputer logs

Course project (Cloud Provisioning and Deployment, Blekinge Institute of Technology). Microservices on Kubernetes that ingest the real
**BlueGene/L** system log (Loghub BGL: 4.7 million lines over 215 days from a 131,072-processor machine at LLNL), flag anomalous
node cards from their severity counts, and score the flags against the dataset's own alert labels.

```
browser -> nginx frontend (only public Service; adds the API key)
              |-> log-service (Node.js): parses BGL lines, stores them in Postgres
              |-> anomaly-service (Flask): reads a time window from log-service, scores components, stores the flags
Postgres (one replica, credentials in a Kubernetes Secret); every service checks an X-API-Key shared secret
```

## What the real data showed

Unit: one node card (or midplane) in one time window. A unit is positive when BGL's alert tag appears on any of its lines. Windows are
ordered in time: the **first 60% train, the last 40% are the held-out future**. Features are the ones the service can see: counts per
severity, counts per subsystem, number of lines, number of distinct message openings, and the same for the previous window.

| node card, 1-hour window (97,470 test units, 20% positive) | AUROC | average precision |
|---|---:|---:|
| random | 0.501 | 0.205 |
| Isolation Forest (unsupervised, refit per window) | 0.598 | 0.255 |
| error-class count (rule) | 0.857 | 0.500 |
| logistic regression | 0.917 | 0.615 |
| **gradient boosting** | **0.927** | **0.719** |
| hierarchical: error-class gate, then boosting on the gated units | 0.923 | 0.658 |
| ensemble: rank average of rule, boosting, logistic, forest | 0.918 | 0.645 |

On midplanes in 10-minute windows the order is the same (boosting 0.973 AUROC and 0.81 AP, the hierarchical model 0.974 and 0.82, the
rule 0.914 and 0.49, the forest 0.78 and 0.26). **The unsupervised Isolation Forest is barely better than random; a supervised model
trained on the earlier part of the log clearly beats the simple rule on the later part**, and the hierarchical and ensemble variants add
nothing over plain boosting in pooled AP (the ensemble is best per window, 0.998). The service ships a boosting model that uses
current-window features only: on the held-out future it reaches AUROC **0.944** and AP **0.76**, and at the threshold chosen on a
validation slice flags with 62% precision and 89% recall (`eval/results/service_model.json`).

**Early warning is weak.** Predicting an alert in the *next* window for units with none yet reaches only AUROC 0.61 to 0.68 (positives
17% for node cards, 2% for midplanes); the models detect trouble that is already visible far better than they predict it. Full tables:
[`eval/results/bgl_models.md`](eval/results/bgl_models.md). The model is trained on BGL, so it applies to BlueGene/L-style logs; other
systems need retraining (`eval/train_service_model.py`). The earlier random-window comparison is in [`eval/results/bgl_eval.md`](eval/results/bgl_eval.md).

## Run and test

```bash
# unit tests
cd Containers/log-service && npm test                     # 4 tests: the BGL line parser
cd Containers/anomaly-service && pip install -r requirements.txt pytest && pytest   # 15 tests: detectors, features, table upgrade and HTTP layer with fakes
# reproduce the table (needs BGL.log from https://zenodo.org/records/8196385)
python eval/bgl_models.py path/to/BGL.log --cache bgl_full.parquet      # all models, time-ordered split
python eval/train_service_model.py path/to/BGL.log --cache bgl_full.parquet   # retrain the shipped model
# deploy: Documentation/DEPLOY.md
```

The UI replays a 4,000-line real excerpt (`Containers/frontend/bgl_sample.log`: the first window in the log with 8% to 20% alert lines)
and shows each flagged node card with whether it carried an alert label.

Checked on a Kubernetes cluster (Docker Desktop, 30 October 2026) with images built from this repository. All four pods ran with no restarts,
the services refused calls without the API key, and the page loaded the 4,000 lines (321 with an alert label, 268 node cards). On the
one-hour analysis window (165 node cards, 162 with an alert label), gradient boosting flagged 162 node cards, all 162 with an alert label,
Isolation Forest flagged 6 (3 with a label) and the error-count rule flagged none. Deleting the Postgres pod kept every row, and scaling
`log-service` to 3 replicas worked with the other services unchanged. The autoscalers report live CPU but have not been load-tested.
The images on Docker Hub (`sriya13/*:1.0`) still predate this version, so rebuild and push them before deploying (`DEPLOY.md`).
Still missing: TLS between services and per-user authentication.

Also checked on AWS (30 October 2026): one EC2 instance running Ubuntu with k3s, a small Kubernetes, with the three images built on the instance from this repository. `deploy/aws/user-data.sh` sets it up and writes `/opt/netops-verify.sh`, which runs the checks. All four pods ran, a call to a service without the API key got 401, the real 4,000-line sample loaded, and the three detectors gave the same results as on Docker Desktop (boosting flagged 162 node cards, all 162 with an alert label; Isolation Forest flagged 6, with 3 labelled; the error-count rule flagged none). The database kept all 4,000 rows after its pod was deleted, and the log service scaled to 3 copies; it restarted once when the database pod was deleted and recovered by itself. This is one machine, so there is no high availability, and the autoscalers were not load-tested.

Data: Oliner and Stearley, "What Supercomputers Say", DSN 2007; Loghub (Zhu et al., ISSRE 2023), free for research use.
