# Methodology

Each section states what the method does, what it assumes and where it stops being reliable.

## Returns and the signed ledger

A return is a reversal line with negative quantity. Revenue, discount and goods cost carry the same sign, so a sale and its return net to zero. Money already spent on the sale (shipping, payment, marketing) stays spent, and only return handling is added. Any `SUM` over valid lines therefore gives the result after returns, at any grain.

A cancelled order with no separate return line, such as an Olist `canceled` order, is recorded as a sale plus its reversal. It nets to zero but still counts toward the return rate.

`INSIGHTFLOW_RETURN_RECOVERY_RATE` sets the share of returned goods that re-enter sellable stock. The default of 1.0 assumes every return can be resold at cost. Lower it when returns are damaged or written off.

Only negative quantity marks a return. An order number starting with `C` means nothing on its own, because plenty of real order numbers do.

## Data contract

The contract runs on the values the source sent, before any rule fills or clips them. An out-of-range discount or a negative cost is therefore reported instead of being silently corrected.

A real ledger always has a few bad rows, and refusing a whole file for them helps nobody. A line that breaks a P1 rule is set aside instead: it stays in the warehouse with its `reject_reason` and leaves every metric. Data Hub lists the reasons, offers the rows as a download and asks before importing. A file is refused outright only for a P0 issue, such as a currency with no exchange rate, or when more than 30% of its lines fail, which points to a wrong mapping rather than messy data. `INSIGHTFLOW_STRICT_IMPORT=true` restores all-or-nothing.

## Non-merchandise lines

Sales ledgers mix goods with postage, bank charges, marketplace fees, manual adjustments and vouchers. None of these are sales of goods, so they would distort product rankings, returns and demand. They are set aside like rejected rows, but reported separately because nothing is wrong with them.

They are matched by name (`POSTAGE`, `AMAZON FEE`), and by code only where the code cannot mean anything else. A short code such as `M` or `C2` could be a real product in another business.

## Reconciliation

Net revenue plus the value of the lines set aside equals quantity × price across the file after exact duplicates are removed. A test enforces this to the penny, and the UCI run in the [validation record](validation.md) reconciles to £0.00.

## What is estimated and what stays empty

Costs can be estimated by documented rules, and every profit figure built on them says so. Revenue is never estimated: with no discount column the price is what was paid. Stock levels and suppliers are left empty, and pages that need them say the data is missing.

Estimated costs also limit what the diagnosis will claim. Without real costs the gross margin only restates the rule, so margin alarms stay silent, and a fall in contribution profit is reported at P2 with a caveat.

## Product names and families

A stock code can carry warehouse notes such as `damaged` or `website fixed`, usually on zero-price lines. A product's name is therefore the description it most often sold under.

When the source has no category column, products are grouped into families by the last common noun in their names, so `JUMBO BAG RED RETROSPOT` and `LUNCH BAG SPACEBOY` both join Bag. Words for colour, size, material and pattern are ignored. This needs at least 100 products and at least 35% of them landing in a family. Names without Latin words stay Uncategorized, and Data Hub says when families were derived. A later batch derives its families separately, so a warehouse built by appending can place a product in two families.

## Provenance

Each line records separate transaction, discount, economic and inventory statuses. A metric's status is its weakest input, and its confidence is weighted by how many rows carry each status. A warehouse holding several sources reads as Mixed. Quality tables accumulate across batches, with scores weighted by rows, so a small clean file cannot relabel a large warehouse.

When the warehouse still holds demo data, an import replaces it by default, so real and simulated rows do not blend into one total.

## Comparison basis

Every change is measured against a base period: the window just before, or the same dates last year. Retail is seasonal, so the first flatters a run into December and punishes January. The choice carries through bridges, diagnosis, the assistant and shared links.

## Price elasticity

For each category, a Poisson regression relates weekly order counts to log net price, with an effect for every product in every sales stream, and for every week. A stream is a channel, split by whether the buyer is known.

Streams exist because of what a real ledger showed. In UCI Online Retail II, anonymous web orders pay about twice the account price for the same product (£5.91 against £2.95 for the best seller). Pooling them makes a week with more web orders look like a week of higher prices and more orders, which flattens the slope:

| Panel | Revenue-weighted elasticity |
|---|---|
| All streams pooled | −0.16 |
| Per stream, unsold weeks at the stream's usual price | −1.21 |
| Per stream, unsold weeks from the product's weekly price index | −0.96 |

A stream with no sale in a week shows no price. Filling it with the stream's usual price records every quiet promotion week as full price with no orders, which steepens the slope. The product's price index that week, read from the streams that did sell, avoids this. On a controlled test where the truth is −1.5, the index recovers −1.37 to −1.59 across three seeds, and the usual price gives −2.67 to −2.90. On UCI, fitting account customers alone, where almost no week needs filling, gives −0.97, in line with the last row.

The other choices follow from measurement on the demo ledger, where the true elasticities are known:

| Estimator | Mean bias | Correlation with truth |
|---|---|---|
| Units on quantity-weighted net price | −0.87 | 0.63 |
| Log units on line-average list price | +0.35 | 0.70 |
| Poisson orders on line-average net price | +0.39 | 0.88 |
| Per sales stream, unsold weeks at the stream's usual price | −0.94 | 0.47 |
| Per sales stream, unsold weeks from the product's price index (in use) | +0.46 | 0.89 |

Quantity weighting manufactures a steep slope, because wholesale orders are both huge and heavily discounted. Taking logs drops weeks with no sale. The Poisson estimate is deliberately on the conservative side, partly because complementary items are bought regardless of their own price.

Standard errors use a sandwich form clustered by product, because orders vary more than a pure Poisson process and one product's weeks are not independent draws. On the real ledger, clustering widens them three to five times. The estimate is then shrunk toward the category prior (prior standard deviation 0.5) in proportion to its precision. With under 150 orders or almost no price movement, the prior is used and the page says so.

**Limits.** Prices are not randomised, so unmeasured promotions that coincide with price changes can still bias the slope. On the demo ledger the estimates lean toward zero, and only a third of the true values fall inside their 95% intervals: the intervals cover sampling noise, not that lean. A recommended price rise can therefore overstate its gain. Treat the output as a prioritised list of experiments, not a decision.

## Price moves

For elasticity *e* below −1, the profit-maximising price is *c × e / (1 + e)*, where *c* is unit variable cost. Moves are capped (±10% by default) because constant elasticity is only trustworthy near prices the business has charged. At or above −1 the formula has no finite answer, so the move rides the cap. When most categories hit the cap, the page says so and asks for an experiment first.

Every move carries its profit at both ends of the elasticity's 95% interval. A move counts as robust only when even the unfavourable end still gains, and the page leads with robust moves. When costs are estimated, the page says the amounts show direction only.

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

The plan search evaluates 245 combinations against the same simulated futures (common random numbers), so two plans differ only because of the plan. Discount cuts deeper than the discount actually running are left out, so a ledger with no discounts gets 140 plans. A recommendation on the edge of the search range is flagged, since the model wants to go further than it has evidence for.

## Forecasting

Candidates are naive, moving average, drift, linear trend, two exponential smoothers and a damped Holt trend. With enough history, seasonal naive, seasonal drift and Holt-Winters join, along with an ensemble of the top three. A rolling one-step backtest ranks them by WAPE.

An unfinished final month is excluded from training, because it would otherwise read as a collapse. The same month is left out of anomaly checks and drawn dashed on trend charts. A month with no sales inside the history counts as zero, not as a gap. Intervals are ±1.28 and ±1.96 times the backtest RMSE, widening with the square root of the horizon. They assume errors stay similar to those in the backtest and are not a guarantee of coverage.

Anomalies are judged against the median of the months before, never a window that contains the month being judged.

## Targets

Default targets follow the business: the mean of the last three months plus a small step (+5% revenue, +8% contribution profit, +1 point of gross margin, −5% return rate). They are not budgets, so a miss is reported at P2 and says so. In an unfinished month, amount targets are prorated by days elapsed.

## Churn model

A regularised logistic regression predicts whether a customer buys in the next 90 days, using recency, frequency, value net of returns, tenure and discount share. It trains at one cutoff and is graded at a later one, so the AUC is out of time. It replaces the rule score only with an AUC of at least 0.60. Otherwise the page says so and keeps the rule score. Once graded, the same recipe is refit on the newest labelled window before scoring customers.

The demo's high AUC reflects a simulated customer lifecycle. On UCI Online Retail II the out-of-time AUC is 0.79. Its calibration is weaker than its ranking: the graded window fell in the autumn peak, so actual return rates ran 10 to 20 points above the prediction. Rank customers with it, and read the probabilities as approximate.

Customer analysis covers only orders with a customer ID, and the page states what share of revenue that is.

## Experiments

Effects use a bootstrap with 1,200 resamples, or a normal approximation above 50,000 rows, where the two agree and resampling would exhaust memory. The decision follows the evidence:

| Result | Condition |
|---|---|
| Stop | Profit clearly falls, or returns breach the guardrail |
| Ship | The whole 95% profit interval is above zero |
| Pilot | At least 90% chance of a lift, with the interval still crossing zero |
| Inconclusive | Anything else |

A sample ratio check flags broken assignment. The minimum detectable lift and required sample size show whether the test could have found a meaningful effect. Sample experiments are only created for simulated warehouses, and replacing the demo with real data removes them, so they never sit beside real customers.

## Inventory policy

Daily demand comes from the last 90 days, net of returns, so an order placed and cancelled leaves no demand behind. On UCI that removes an 80,995-unit order cancelled the same day. Safety stock is *z × √(L × σ² + d² × σL²)*, where *z* comes from the service level and lead time *L* is assumed to vary by 20%. ABC classes use 80% and 95% of revenue; XYZ classes use the coefficient of variation of weekly demand, split at 0.5 and 1.0.

The stock level is the latest reading, not the highest. Without stock on hand the page shows demand and these classes, and makes no stockout or reorder claim.

## Basket analysis

Pairs need at least 8 joint orders. Lift is confidence divided by the second product's base rate, and above 1 means more often than chance. Lift does not show that one product causes the other to sell. Above 120,000 orders a stable random sample is used, which keeps memory bounded and barely moves lift.
