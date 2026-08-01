# Metric Dictionary

| Metric | Definition | Trust dependency | Decision use | Main caveat |
|---|---|---|---|---|
| Net revenue | Gross merchandise value minus discount | Transaction and discount status | Commercial scale | Does not measure profitability |
| Gross profit | Net revenue minus product cost | Product-cost status | Pricing and sourcing | Estimated when source lacks cost |
| Contribution profit | Gross profit minus logistics, payment, marketing and return-processing cost | Economic status | Sustainable growth | Excludes fixed overhead and tax |
| Contribution margin | Contribution profit / net revenue | Economic status | Growth quality | Sensitive to allocation rules |
| Repeat rate | Customers with at least two orders / purchasing customers | Transaction status | Customer quality | Depends on analysis window |
| Predicted CLV | Baseline monthly customer profit × expected remaining months | Economic and model status | Retention priority | v0.4 remains a transparent baseline, not a validated probability model |
| Inventory days | On-hand inventory / recent daily unit demand | Inventory status | Replenishment | Seasonal demand requires review |
| Target attainment | Actual versus target in the intended direction | Target status | Operating cadence | Demo targets are simulated |
| Experiment profit lift | Treatment mean profit minus control mean profit | Experiment status | Rollout decision | Included experiments are simulated |
| Probability profit improves | Monte Carlo share with positive profit change | Assumption status | Risk-adjusted planning | Depends on visible parameter distributions |
