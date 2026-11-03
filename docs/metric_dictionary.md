# Metric Dictionary

| Metric | Definition | Trust dependency | Decision use | Main caveat |
|---|---|---|---|---|
| Gross sales | Quantity × list price on sale lines | Transaction status | Demand at list price | Before discounts and returns |
| Refunds | Value of reversal lines | Transaction status | Return cost | Recognised on the return date |
| Net revenue | Gross sales minus discount minus refunds, on merchandise lines | Transaction status | Commercial scale | Excludes postage, fees and adjustments, which are listed separately |
| Gross profit | Net revenue minus product cost, with returned cost recovered | Economic status | Pricing and sourcing | Depends on the return recovery rate |
| Contribution profit | Gross profit minus shipping, payment, marketing and return handling | Economic status | Sustainable growth | Excludes fixed overhead and tax |
| Contribution margin | Contribution profit / net revenue | Economic status | Growth quality | Sensitive to allocation rules |
| Return rate | Return orders / sale orders | Transaction status | Fulfilment quality | Returns may belong to an earlier period's sales |
| Repeat rate | Customers with at least two orders / purchasing customers | Transaction status | Customer quality | Depends on the analysis window |
| Churn risk | One minus the modelled chance of buying in the next 90 days | Transaction status | Retention priority | Falls back to a rule score if validation fails |
| Predicted customer value | Monthly profit × expected remaining months, up to 12 | Economic status | Retention priority | A ranking aid, not a financial forecast |
| Price elasticity | % change in orders for a 1% price change | Observed price variation | Pricing | Observational, so confirm with an experiment |
| Safety stock | Service factor × demand and lead-time uncertainty | Inventory status | Replenishment | Assumes lead times vary by 20% |
| Daily demand | Net units over the last 90 days / 90 | Transaction status | Replenishment | Net of returns, so a cancelled order leaves no demand |
| Target attainment | Actual versus target in the intended direction | Target status | Operating cadence | Default targets are rule-based, not budgets, and amounts are prorated in an unfinished month |
| Experiment profit lift | Treatment mean profit minus control mean profit | Experiment status | Rollout decision | Sample experiments are simulated |
| Probability profit improves | Share of simulations with a positive profit change | Assumption status | Risk-adjusted planning | Depends on visible assumptions |
