| setting | method | AUROC | AP | AUROC per window |
|---|---|---|---|---|
| **node card, 60-min window, alert in this window** (test units 97470, positives 0.20) | | | | |
| | random | 0.501 | 0.205 | 0.5 |
| | Isolation Forest (unsupervised) | 0.598 | 0.255 | 0.735 |
| | error-class count (rule) | 0.857 | 0.500 | 0.97 |
| | logistic regression (supervised) | 0.917 | 0.615 | 0.994 |
| | gradient boosting (supervised) | 0.927 | 0.719 | 0.988 |
| | hierarchical: rule gate + boosting | 0.923 | 0.658 | 0.976 |
| | ensemble: rank average of rule, boosting, logistic, forest | 0.918 | 0.645 | 0.998 |
| **node card, 60-min window, alert in the NEXT window (early warning)** (test units 17423, positives 0.17) | | | | |
| | random | 0.504 | 0.181 | 0.554 |
| | Isolation Forest (unsupervised) | 0.423 | 0.171 | 0.402 |
| | error-class count (rule) | 0.514 | 0.174 | 0.585 |
| | logistic regression (supervised) | 0.610 | 0.222 | 0.647 |
| | gradient boosting (supervised) | 0.617 | 0.252 | 0.61 |
| | hierarchical: rule gate + boosting | 0.642 | 0.248 | 0.674 |
| | ensemble: rank average of rule, boosting, logistic, forest | 0.655 | 0.243 | 0.77 |
| **midplane, 10-min window, alert in this window** (test units 42508, positives 0.14) | | | | |
| | random | 0.506 | 0.145 | 0.508 |
| | Isolation Forest (unsupervised) | 0.776 | 0.256 | 0.793 |
| | error-class count (rule) | 0.914 | 0.492 | 0.965 |
| | logistic regression (supervised) | 0.957 | 0.709 | 0.986 |
| | gradient boosting (supervised) | 0.973 | 0.814 | 0.992 |
| | hierarchical: rule gate + boosting | 0.974 | 0.820 | 0.989 |
| | ensemble: rank average of rule, boosting, logistic, forest | 0.960 | 0.690 | 0.997 |
| **midplane, 10-min window, alert in the NEXT window (early warning)** (test units 7433, positives 0.02) | | | | |
| | random | 0.549 | 0.023 | 0.623 |
| | Isolation Forest (unsupervised) | 0.252 | 0.013 | 0.474 |
| | error-class count (rule) | 0.438 | 0.019 | 0.5 |
| | logistic regression (supervised) | 0.506 | 0.019 | 0.548 |
| | gradient boosting (supervised) | 0.680 | 0.031 | 0.521 |
| | hierarchical: rule gate + boosting | 0.588 | 0.023 | 0.409 |
| | ensemble: rank average of rule, boosting, logistic, forest | 0.521 | 0.020 | 0.523 |
