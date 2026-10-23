import math
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
from typing import Dict, Any, List
from schema import (
    BakeryOperationalTarget,
    BakeryOptimizationSummary,
    ItemBatchYieldMetrics,
    BakeryOverheadConfig
)
from database import fetch_overhead_config, fetch_master_recipes


def calculate_true_unit_cost(
    batch_raw_ingredient_cost: float,
    units_per_batch: int,
    packaging_cost_per_unit: float,
    bake_time_minutes: float,
    overhead_config: BakeryOverheadConfig
) -> float:
    """
    Calculates true baseline cost floor per piece ($C_{i}$) aggregating:
    - Raw ingredient mix cost per batch
    - Direct packaging cost per piece
    - Continuous LPG fuel burn during baking time
    - Allocated baker labor time
    """
    if units_per_batch <= 0:
        return 0.0

    bake_time_hours = bake_time_minutes / 60.0
    lpg_cost_per_batch = bake_time_hours * overhead_config.lpg_hourly_rate_php
    labor_cost_per_batch = bake_time_hours * overhead_config.baker_hourly_wage_php

    total_batch_cost = (
        batch_raw_ingredient_cost + lpg_cost_per_batch + labor_cost_per_batch
    )
    base_unit_cost = total_batch_cost / units_per_batch
    true_unit_cost = base_unit_cost + packaging_cost_per_unit

    return round(true_unit_cost, 2)


def calculate_discrete_tray_ceiling(demand_units: int, tray_capacity: int) -> int:
    """
    Computes discrete sheet-pan (*plancha*) tray allocation:
    $\\text{Trays Required}_i = \\lceil \\text{Demand}_i / \\text{Tray Capacity}_i \\rceil$
    """
    if tray_capacity <= 0 or demand_units <= 0:
        return 0
    return math.ceil(demand_units / tray_capacity)


def calculate_clearance_price(true_unit_cost: float, retail_price: float) -> float:
    """
    Calculates dynamic afternoon markdown discount price ($P_{clearance,i}$).
    Ensures liquidation price stays strictly above variable cost $C_{i}$ to recover capital.
    """
    # 20% margin recovery above variable cost, capped at 60% of retail price
    recovery_price = round(true_unit_cost * 1.20, 2)
    discounted_retail = round(retail_price * 0.60, 2)

    clearance_price = max(recovery_price, discounted_retail)
    # Ensure clearance price never exceeds original retail price
    return min(clearance_price, retail_price)


def optimize_bakery_production(
    target: BakeryOperationalTarget
) -> BakeryOptimizationSummary:
    """
    Deterministic optimization engine that balances tray allocation,
    deck capacity bounds, true unit costs, and perishable clearance revenue.
    """
    overhead_config = fetch_overhead_config()
    master_recipes = fetch_master_recipes()

    # Override deck capacity if user explicitly specified it in target
    max_deck_capacity = (
        target.max_oven_capacity_trays
        if target.max_oven_capacity_trays is not None
        else overhead_config.max_deck_tray_capacity
    )

    # Convert user item constraints into an easily searchable map
    user_constraints = {
        item.item_name.lower(): item for item in target.item_constraints
    }

    # Default demand baselines if not specified by user prompt
    default_demands = {
        "pan de sal": 180,
        "spanish bread": 90,
        "ensaymada": 60
    }

    item_metrics_list: List[ItemBatchYieldMetrics] = []
    total_trays_required = 0

    # 1. First Pass: Compute raw demands, true unit costs, and tray allocations
    raw_item_data = []
    for item_name, data in master_recipes.items():
        recipe = data["recipe"]
        batch_raw_cost = data["batch_raw_ingredient_cost"]
        retail_price = data["default_retail_price"]

        # Parse user demand or fall back to default baseline
        item_key = item_name.lower()
        constraint = user_constraints.get(item_key)

        if constraint and constraint.target_demand_units is not None:
            projected_demand = constraint.target_demand_units
        else:
            projected_demand = default_demands.get(item_key, 60)

        # Compute True Unit Cost (C_i)
        true_cost = calculate_true_unit_cost(
            batch_raw_ingredient_cost=batch_raw_cost,
            units_per_batch=recipe.units_per_batch,
            packaging_cost_per_unit=recipe.packaging_cost_per_unit,
            bake_time_minutes=recipe.bake_time_minutes,
            overhead_config=overhead_config
        )

        # Compute Clearance Price (P_clearance)
        clearance_price = calculate_clearance_price(true_cost, retail_price)

        # Discrete Tray Ceiling Math
        trays_req = calculate_discrete_tray_ceiling(projected_demand, recipe.tray_capacity)

        raw_item_data.append({
            "item_name": item_name,
            "recipe": recipe,
            "projected_demand": projected_demand,
            "true_cost": true_cost,
            "retail_price": retail_price,
            "clearance_price": clearance_price,
            "trays_req": trays_req,
            "unit_profit_margin": retail_price - true_cost
        })
        total_trays_required += trays_req

    # 2. Second Pass: Deck Capacity Scaling (If total trays exceeds oven limits)
    if total_trays_required > max_deck_capacity:
        # Sort items by unit profit margin descending (prioritize high-margin trays)
        raw_item_data.sort(key=lambda x: x["unit_profit_margin"], reverse=True)
        allocated_trays = 0

        for item in raw_item_data:
            if allocated_trays + item["trays_req"] <= max_deck_capacity:
                allocated_trays += item["trays_req"]
            else:
                # Scale down trays to fit remaining capacity
                remaining_capacity = max(0, max_deck_capacity - allocated_trays)
                item["trays_req"] = remaining_capacity
                allocated_trays += remaining_capacity

    # 3. Third Pass: Final Yield, Cost & Margin Aggregation
    gross_revenue = 0.0
    total_variable_costs = 0.0
    final_trays_allocated = 0

    for item in raw_item_data:
        recipe = item["recipe"]
        trays = item["trays_req"]
        demand = item["projected_demand"]
        true_cost = item["true_cost"]
        retail_p = item["retail_price"]
        clearance_p = item["clearance_price"]

        total_supply = trays * recipe.tray_capacity
        morning_sales = min(total_supply, demand)
        surplus_clearance = max(0, total_supply - demand)

        # Revenue = Full Price Sales + Afternoon Clearance Sales
        item_revenue = (morning_sales * retail_p) + (surplus_clearance * clearance_p)
        item_var_cost = total_supply * true_cost
        net_margin_contrib = item_revenue - item_var_cost

        gross_revenue += item_revenue
        total_variable_costs += item_var_cost
        final_trays_allocated += trays

        item_metrics_list.append(
            ItemBatchYieldMetrics(
                item_name=item["item_name"],
                true_unit_cost=true_cost,
                retail_price=retail_p,
                clearance_price=clearance_p,
                projected_demand_units=demand,
                trays_required=trays,
                total_supply_units=total_supply,
                morning_expected_sales_units=morning_sales,
                surplus_clearance_units=surplus_clearance,
                expected_revenue=round(item_revenue, 2),
                total_variable_cost=round(item_var_cost, 2),
                net_margin_contribution=round(net_margin_contrib, 2)
            )
        )

    # Net Profit = Gross Revenue - Total Variable Costs - Fixed Overhead
    fixed_overhead = overhead_config.fixed_daily_overhead_php
    net_profit = round(gross_revenue - total_variable_costs - fixed_overhead, 2)

    target_profit_met = False
    if target.target_net_profit is not None:
        target_profit_met = net_profit >= target.target_net_profit

    capacity_utilized_pct = round(
        (final_trays_allocated / max_deck_capacity) * 100.0, 1
    ) if max_deck_capacity > 0 else 0.0

    return BakeryOptimizationSummary(
        total_trays_allocated=final_trays_allocated,
        deck_capacity_utilized_pct=capacity_utilized_pct,
        gross_revenue=round(gross_revenue, 2),
        total_variable_costs=round(total_variable_costs, 2),
        fixed_overhead=fixed_overhead,
        net_profit=net_profit,
        target_profit_met=target_profit_met,
        items=item_metrics_list
    )


if __name__ == "__main__":
    # Internal validation execution using dummy sample target
    test_target = BakeryOperationalTarget(
        target_net_profit=1200.0,
        max_oven_capacity_trays=12
    )
    summary = optimize_bakery_production(test_target)
    print("--- LOGIC ENGINE VALIDATION RESULT ---")
    print(f"Total Trays Allocated: {summary.total_trays_allocated}")
    print(f"Capacity Utilized: {summary.deck_capacity_utilized_pct}%")
    print(f"Gross Revenue: ₱{summary.gross_revenue}")
    print(f"Total Variable Cost: ₱{summary.total_variable_costs}")
    print(f"Net Profit: ₱{summary.net_profit}")
    print("---------------------------------------")
