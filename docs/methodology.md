# Methodology

Each section states what the method does, what it assumes and where it stops being reliable.

## Returns and the signed ledger

A return is a reversal line with negative quantity. Revenue, discount and goods cost carry the same sign, so a sale and its return net to zero. Money already spent on the sale (shipping, payment, marketing) stays spent, and only return handling is added. Any `SUM` over valid lines therefore gives the result after returns, at any grain.

A cancelled order with no separate return line, such as an Olist `canceled` order, is recorded as a sale plus its reversal. It nets to zero but still counts toward the return rate.

`INSIGHTFLOW_RETURN_RECOVERY_RATE` sets the share of returned goods that re-enter sellable stock. The default of 1.0 assumes every return can be resold at cost. Lower it when returns are damaged or written off.

Only negative quantity marks a return. An order number starting with `C` means nothing on its own, because plenty of real order numbers do.

## Data contract

The contract runs on the values the source sent, before any rule fills or clips them. An out-of-range discount or a negative cost is therefore reported instead of being silently corrected. P0 and P1 issues block import; P2 issues are warnings.

## Provenance

Each line records separate transaction, discount, economic and inventory statuses. A metric's status is its weakest input, and its confidence is weighted by how many rows carry each status. A warehouse holding several sources reads as Mixed. Quality tables accumulate across batches, with scores weighted by rows, so a small clean file cannot relabel a large warehouse.

## Price elasticity

For each category, a Poisson regression relates weekly order counts to log net price, with an effect for every product and every week.

Two choices follow from measurement on the demo ledger, where the true elasticities are known:

| Estimator | Mean bias | Correlation with truth |
|---|---|---|
| Units on quantity-weighted net price | −0.87 | 0.63 |
| Log units on line-average list price | +0.35 | 0.70 |
| Poisson orders on line-average net price | +0.39 | 0.88 |

Quantity weighting manufactures a steep slope, because wholesale orders are both huge and heavily discounted. Taking logs drops weeks with no sale. The Poisson estimate is deliberately on the conservative side, partly because complementary items are bought regardless of their own price.

Standard errors use a sandwich form, because orders vary more than a pure Poisson process. The estimate is then shrunk toward the category prior (prior standard deviation 0.5) in proportion to its precision. With under 150 orders or almost no price movement, the prior is used and the page says so.

**Limits.** Prices are not randomised, so unmeasured promotions that coincide with price changes can still bias the slope. Treat the output as a prioritised list of experiments, not a decision.

## Price moves

For elasticity *e* below −1, the profit-maximising price is *c × e / (1 + e)*, where *c* is unit variable cost. Moves are capped (±10% by default) because constant elasticity is only trustworthy near prices the business has charged. When most categories hit the cap, the page says so and asks for an experiment first.

## Price-volume-mix bridge

For products sold in both periods, with *Q* units and unit margin *m*:

```text
Volume = Q0 × g × m0                g = total unit growth
Mix    = (Q1 − Q0 × (1 + g)) × m0
Price  = Q1 × (list1 − list0)
Discount = −Q1 × (discount1 − discount0)
Unit cost = −Q1 × (cost1 − cost0)
```

New and lost products, shipping, payment, marketing and returns complete the bridge. The steps add up to the actual change, and a test enforces that to within rounding.

## Scenario model

One function projects both point estimates and simulations, so a median can never disagree with a point estimate because of a different clipping rule. With no changes it reproduces the baseline exactly. The default elasticity comes from the estimates above.

Monte Carlo draws elasticity, marketing response, baseline demand, purchase cost and shipping cost from visible distributions. The result depends on those assumptions and describes a range of risk, not a prediction.

The plan search evaluates 245 combinations against the same simulated futures (common random numbers), so two plans differ only because of the plan. A recommendation on the edge of the search range is flagged, since the model wants to go further than it has evidence for.

## Forecasting

Candidates are naive, moving average, drift, linear trend, two exponential smoothers and a damped Holt trend. With enough history, seasonal naive, seasonal drift and Holt-Winters join, along with an ensemble of the top three. A rolling one-step backtest ranks them by WAPE.

An unfinished final month is excluded from training, because it would otherwise read as a collapse. Intervals are ±1.28 and ±1.96 times the backtest RMSE, widening with the square root of the horizon. They assume errors stay similar to those in the backtest and are not a guarantee of coverage.

## Churn model

A regularised logistic regression predicts whether a customer buys in the next 90 days, using recency, frequency, value, tenure and discount share. It trains at one cutoff and is graded at a later one, so the AUC is out of time. It replaces the rule score only with an AUC of at least 0.60. Otherwise the page says so and keeps the rule score.

The demo's high AUC reflects a simulated customer lifecycle. A real ledger will score lower.

## Experiments

Effects use a bootstrap with 1,200 resamples. The decision follows the evidence:

| Result | Condition |
|---|---|
| Stop | Profit clearly falls, or returns breach the guardrail |
| Ship | The whole 95% profit interval is above zero |
| Pilot | At least 90% chance of a lift, with the interval still crossing zero |
| Inconclusive | Anything else |

A sample ratio check flags broken assignment. The minimum detectable lift and required sample size show whether the test could have found a meaningful effect. Sample experiments are only created for simulated warehouses, never beside real customers.

## Inventory policy

Daily demand comes from the last 90 days. Safety stock is *z × √(L × σ² + d² × σL²)*, where *z* comes from the service level and lead time *L* is assumed to vary by 20%. ABC classes use 80% and 95% of revenue; XYZ classes use the coefficient of variation of weekly demand, split at 0.5 and 1.0.

## Basket analysis

Pairs need at least 8 joint orders. Lift is confidence divided by the second product's base rate, and above 1 means more often than chance. Lift does not show that one product causes the other to sell.
