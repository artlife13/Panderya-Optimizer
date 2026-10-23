from typing import List, Optional
from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# 1. INPUT SCHEMAS: AI Conversational Compiler Targets
# -----------------------------------------------------------------------------

class ItemConstraint(BaseModel):
    """
    Extracted constraints and roles for individual baked goods parsed
    from the baker's natural Taglish prompt.
    """
    item_name: str = Field(
        ...,
        description="Name of the baked product (e.g., Pan de Sal, Ensaymada, Spanish Bread)."
    )
    target_demand_units: Optional[int] = Field(
        default=None,
        description="Explicit requested unit count if specified by the baker."
    )
    clearance_deadline: Optional[str] = Field(
        default=None,
        description="Target time by which surplus inventory must be cleared (e.g., '16:00')."
    )
    min_acceptable_margin: Optional[str] = Field(
        default="breakeven",
        description="Minimum acceptable margin goal ('breakeven', 'standard', 'high')."
    )
    role: Optional[str] = Field(
        default="standard",
        description="Operational strategy role ('volume_driver', 'profit_driver', 'salvage_only')."
    )


class BakeryOperationalTarget(BaseModel):
    """
    Top-level structured JSON schema enforced on Gemini API output when parsing
    Taglish operational goals (Rule C.4.c Compliance).
    """
    target_net_profit: Optional[float] = Field(
        default=None,
        description="Target daily net profit in PHP specified by the baker."
    )
    max_oven_capacity_trays: Optional[int] = Field(
        default=None,
        description="Overriding deck oven tray capacity limit if mentioned by the baker."
    )
    shift_duration_hours: Optional[float] = Field(
        default=8.0,
        description="Total duration of the baking shift in hours."
    )
    item_constraints: List[ItemConstraint] = Field(
        default_factory=list,
        description="List of product-specific target constraints parsed from the prompt."
    )


# -----------------------------------------------------------------------------
# 2. DATABASE & LOGIC SCHEMAS: Master Data & Calculation Models
# -----------------------------------------------------------------------------

class IngredientCost(BaseModel):
    """
    Baseline raw commodity cost structured inputs from SQLite database.
    """
    ingredient_name: str
    unit_cost_php: float
    unit_type: str  # e.g., 'gram', 'kg', 'liter', 'bag'


class RecipeIngredient(BaseModel):
    """
    Recipe breakdown mapping ingredients to specific quantities per batch.
    """
    ingredient_name: str
    quantity_required: float


class ProductMasterRecipe(BaseModel):
    """
    Master recipe definition for a single baked product.
    """
    item_name: str
    units_per_batch: int
    tray_capacity: int  # Plancha piece density per baking sheet
    bake_time_minutes: float
    packaging_cost_per_unit: float
    ingredients: List[RecipeIngredient]


class BakeryOverheadConfig(BaseModel):
    """
    Operational expenses required to compute true unit cost (C_i).
    """
    lpg_hourly_rate_php: float = Field(
        default=45.0,
        description="LPG fuel cost per hour of continuous deck oven operation."
    )
    baker_hourly_wage_php: float = Field(
        default=75.0,
        description="Direct labor allocation cost per hour."
    )
    fixed_daily_overhead_php: float = Field(
        default=300.0,
        description="Daily static expenses (rent, utilities, store permits)."
    )
    max_deck_tray_capacity: int = Field(
        default=12,
        description="Total available deck oven sheet capacity per shift."
    )


# -----------------------------------------------------------------------------
# 3. OUTPUT SCHEMAS: Deterministic Engine Execution Metrics
# -----------------------------------------------------------------------------

class ItemBatchYieldMetrics(BaseModel):
    """
    Computed production metrics for a single item output by logic.py.
    """
    item_name: str
    true_unit_cost: float = Field(..., description="C_i baseline unit cost in PHP.")
    retail_price: float = Field(..., description="Standard morning retail price P_i.")
    clearance_price: float = Field(..., description="Discounted afternoon markdown price P_clearance.")
    projected_demand_units: int
    trays_required: int = Field(..., description="Discrete plancha ceiling calculation result.")
    total_supply_units: int = Field(..., description="Trays Required * Tray Capacity.")
    morning_expected_sales_units: int = Field(..., description="min(Supply, Demand).")
    surplus_clearance_units: int = Field(..., description="max(0, Supply - Demand).")
    expected_revenue: float
    total_variable_cost: float
    net_margin_contribution: float


class BakeryOptimizationSummary(BaseModel):
    """
    Final deterministic optimization response payload passed to app.py and pandas.
    """
    total_trays_allocated: int
    deck_capacity_utilized_pct: float
    gross_revenue: float
    total_variable_costs: float
    fixed_overhead: float
    net_profit: float
    target_profit_met: bool
    items: List[ItemBatchYieldMetrics]
