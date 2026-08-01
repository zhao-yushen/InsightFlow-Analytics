from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FaultPlan:
    duplicate_rate: float = 0.03
    missing_customer_rate: float = 0.02
    invalid_price_rate: float = 0.005
    future_date_rate: float = 0.003
    unknown_channel_rate: float = 0.01
    remove_month: bool = True
    seed: int = 20260801


def inject_faults(df: pd.DataFrame, plan: FaultPlan | None = None) -> pd.DataFrame:
    plan = plan or FaultPlan()
    rng = np.random.default_rng(plan.seed)
    out = df.copy()
    n = len(out)
    if n == 0:
        return out

    def sample(rate: float) -> np.ndarray:
        count = min(n, max(0, int(round(n * rate))))
        return (
            rng.choice(out.index.to_numpy(), size=count, replace=False)
            if count
            else np.array([], dtype=int)
        )

    missing = sample(plan.missing_customer_rate)
    if "customer_id" in out:
        out.loc[missing, "customer_id"] = pd.NA

    invalid_price = sample(plan.invalid_price_rate)
    if "unit_price" in out:
        out.loc[invalid_price, "unit_price"] = -out.loc[invalid_price, "unit_price"].abs().fillna(1)

    future = sample(plan.future_date_rate)
    if "invoice_date" in out:
        out.loc[future, "invoice_date"] = pd.Timestamp.now().normalize() + pd.Timedelta(days=45)

    unknown_channel = sample(plan.unknown_channel_rate)
    if "channel" in out:
        out.loc[unknown_channel, "channel"] = "SocialCommerce"

    if plan.remove_month and "invoice_date" in out:
        dates = pd.to_datetime(out["invoice_date"], errors="coerce")
        months = dates.dt.to_period("M")
        valid_months = sorted(months.dropna().unique())
        if len(valid_months) >= 4:
            remove = valid_months[len(valid_months) // 2]
            out = out.loc[months.ne(remove)].copy()

    duplicate_count = max(0, int(round(len(out) * plan.duplicate_rate)))
    if duplicate_count:
        duplicates = out.sample(n=min(duplicate_count, len(out)), random_state=plan.seed)
        out = pd.concat([out, duplicates], ignore_index=True)
    return out
