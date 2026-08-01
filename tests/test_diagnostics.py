import math

from insightflow.diagnostics import revenue_driver_decomposition


def test_shapley_decomposition_reconciles_revenue_change():
    previous = {"active_customers": 100, "purchase_frequency": 2, "average_order_value": 40}
    current = {"active_customers": 90, "purchase_frequency": 2.2, "average_order_value": 38}
    drivers = revenue_driver_decomposition(current, previous)
    expected = 90 * 2.2 * 38 - 100 * 2 * 40
    assert math.isclose(drivers["revenue_contribution"].sum(), expected, rel_tol=1e-9, abs_tol=1e-9)
