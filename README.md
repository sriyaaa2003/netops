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

Unit: one node card (or midplane) in one time window, described only by its severity counts. A unit is positive when BGL's alert tag
appears on any of its lines. 300 random windows per setting, each scored on its own batch (the Isolation Forest is refit per window).

| unit, window | positives | method | AUROC (pooled) | AUROC (mean per window) |
|---|---:|---|---:|---:|
| node card, 60 min | 56% | random | 0.495 | 0.481 |
| | | Isolation Forest | 0.606 | 0.620 |
| | | error-class count | **0.843** | **0.960** |
| midplane, 10 min | 40% | random | 0.499 | 0.503 |
| | | Isolation Forest | 0.540 | 0.719 |
| | | error-class count | **0.929** | **0.969** |

All four settings and a max-z-score baseline are in [`eval/results/bgl_eval.md`](eval/results/bgl_eval.md). **The unsupervised Isolation
Forest on severity counts is barely better than random on pooled units; counting ERROR, SEVERE, FATAL and FAILURE lines is far better**,
because BGL's alert tags are largely attached to those lines. Alerts are also common (40% to 58% of units), so this is not rare-event
detection. The service therefore defaults to the error-class rule (`DETECTOR=error_count`) and keeps the Isolation Forest selectable. The
original idea, that the forest would find degrading components without labels, did not hold on this data.

## Run and test

```bash
# unit tests
cd Containers/log-service && npm test                     # 4 tests: the BGL line parser
cd Containers/anomaly-service && pip install -r requirements.txt pytest && pytest   # 11 tests: detector and HTTP layer with fakes
# reproduce the table (needs BGL.log from https://zenodo.org/records/8196385)
python eval/bgl_eval.py path/to/BGL.log --cache bgl.parquet
# deploy: Documentation/DEPLOY.md
```

The UI replays a 4,000-line real excerpt (`Containers/frontend/bgl_sample.log`: the first window in the log with 8% to 20% alert lines)
and shows each flagged node card with whether it carried an alert label. Not verified on a cluster: the services were tested with fakes
for Postgres and each other, and the images in `DEPLOY.md` need rebuilding. Still missing: TLS between services and per-user authentication.

Data: Oliner and Stearley, "What Supercomputers Say", DSN 2007; Loghub (Zhu et al., ISSRE 2023), free for research use.
