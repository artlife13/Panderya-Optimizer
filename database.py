import sqlite3
import os
from typing import List, Dict, Any, Optional
from schema import IngredientCost, ProductMasterRecipe, RecipeIngredient, BakeryOverheadConfig

DB_FILE = "panaderya.db"


def get_connection() -> sqlite3.Connection:
    """Establishes and returns a database connection with row factory enabled."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initializes SQLite schema and seeds baseline commodity costs and recipes."""
    conn = get_connection()
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. Ingredients Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ingredients (
        ingredient_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        unit_cost_php REAL NOT NULL,
        unit_type TEXT NOT NULL
    );
    """)

    # 2. Products Master Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        product_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT UNIQUE NOT NULL,
        units_per_batch INTEGER NOT NULL,
        tray_capacity INTEGER NOT NULL,
        bake_time_minutes REAL NOT NULL,
        packaging_cost_per_unit REAL NOT NULL,
        default_retail_price REAL NOT NULL
    );
    """)

    # 3. Product Recipe Mapping Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS recipe_items (
        recipe_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        ingredient_id INTEGER NOT NULL,
        quantity_required REAL NOT NULL,
        FOREIGN KEY (product_id) REFERENCES products (product_id) ON DELETE CASCADE,
        FOREIGN KEY (ingredient_id) REFERENCES ingredients (ingredient_id) ON DELETE CASCADE
    );
    """)

    # 4. Overhead Configuration Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS overhead_config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        lpg_hourly_rate_php REAL NOT NULL,
        baker_hourly_wage_php REAL NOT NULL,
        fixed_daily_overhead_php REAL NOT NULL,
        max_deck_tray_capacity INTEGER NOT NULL
    );
    """)

    conn.commit()

    # Seed initial baseline data if tables are empty
    cursor.execute("SELECT COUNT(*) FROM ingredients;")
    if cursor.fetchone()[0] == 0:
        _seed_baseline_data(conn)

    conn.close()


def _seed_baseline_data(conn: sqlite3.Connection) -> None:
    """Seeds default wet-market commodity prices and master bread recipes."""
    cursor = conn.cursor()

    # Seed Baseline Commodities (Philippine Wet Market Rates per gram)
    # ₱45/kg = ₱0.045/g, ₱80/kg = ₱0.08/g, etc.
    ingredients_data = [
        ("Bread Flour", 0.045, "gram"),   # ~₱45/kg
        ("Refined Sugar", 0.08, "gram"),   # ~₱80/kg
        ("Margarine", 0.12, "gram"),       # ~₱120/kg
        ("Yeast", 0.35, "gram"),           # ~₱350/kg
        ("Cheese Bar", 0.25, "gram"),      # ~₱250/kg
        ("Breadcrumbs", 0.06, "gram")      # ~₱60/kg
    ]
    cursor.executemany(
        "INSERT INTO ingredients (name, unit_cost_php, unit_type) VALUES (?, ?, ?);",
        ingredients_data
    )

    # Seed Default Overhead Config
    cursor.execute("""
    INSERT INTO overhead_config (id, lpg_hourly_rate_php, baker_hourly_wage_php, fixed_daily_overhead_php, max_deck_tray_capacity)
    VALUES (1, 45.0, 75.0, 300.0, 12);
    """)

    # Helper map for ingredient IDs
    cursor.execute("SELECT name, ingredient_id FROM ingredients;")
    ing_map = {row["name"]: row["ingredient_id"] for row in cursor.fetchall()}

    # Seed Master Product Recipes
    products = [
        ("Pan de Sal", 30, 30, 15.0, 0.10, 3.00),
        ("Spanish Bread", 24, 24, 18.0, 0.15, 7.00),
        ("Ensaymada", 20, 20, 20.0, 0.25, 12.00)
    ]

    for item_name, units_per_batch, tray_cap, bake_time, pkg_cost, price in products:
        cursor.execute("""
        INSERT INTO products (item_name, units_per_batch, tray_capacity, bake_time_minutes, packaging_cost_per_unit, default_retail_price)
        VALUES (?, ?, ?, ?, ?, ?);
        """, (item_name, units_per_batch, tray_cap, bake_time, pkg_cost, price))

        prod_id = cursor.lastrowid

        # Recipe Ingredients per Batch
        if item_name == "Pan de Sal":
            recipe = [
                (ing_map["Bread Flour"], 500.0),
                (ing_map["Refined Sugar"], 80.0),
                (ing_map["Margarine"], 40.0),
                (ing_map["Yeast"], 10.0),
                (ing_map["Breadcrumbs"], 50.0)
            ]
        elif item_name == "Spanish Bread":
            recipe = [
                (ing_map["Bread Flour"], 450.0),
                (ing_map["Refined Sugar"], 120.0),
                (ing_map["Margarine"], 80.0),
                (ing_map["Yeast"], 10.0),
                (ing_map["Breadcrumbs"], 40.0)
            ]
        elif item_name == "Ensaymada":
            recipe = [
                (ing_map["Bread Flour"], 400.0),
                (ing_map["Refined Sugar"], 150.0),
                (ing_map["Margarine"], 100.0),
                (ing_map["Yeast"], 12.0),
                (ing_map["Cheese Bar"], 100.0)
            ]

        for ing_id, qty in recipe:
            cursor.execute("""
            INSERT INTO recipe_items (product_id, ingredient_id, quantity_required)
            VALUES (?, ?, ?);
            """, (prod_id, ing_id, qty))

    conn.commit()


def fetch_overhead_config() -> BakeryOverheadConfig:
    """Retrieves current bakery operational expenses and deck limits."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM overhead_config WHERE id = 1;")
    row = cursor.fetchone()
    conn.close()

    return BakeryOverheadConfig(
        lpg_hourly_rate_php=row["lpg_hourly_rate_php"],
        baker_hourly_wage_php=row["baker_hourly_wage_php"],
        fixed_daily_overhead_php=row["fixed_daily_overhead_php"],
        max_deck_tray_capacity=row["max_deck_tray_capacity"]
    )


def fetch_master_recipes() -> Dict[str, Dict[str, Any]]:
    """
    Fetches all master product recipes along with ingredient cost breakdowns
    and standard retail prices for deterministic calculations.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products;")
    products = cursor.fetchall()

    master_recipes = {}

    for prod in products:
        prod_id = prod["product_id"]
        item_name = prod["item_name"]

        cursor.execute("""
        SELECT i.name, i.unit_cost_php, r.quantity_required
        FROM recipe_items r
        JOIN ingredients i ON r.ingredient_id = i.ingredient_id
        WHERE r.product_id = ?;
        """, (prod_id,))

        ingredients_rows = cursor.fetchall()
        recipe_ingredients = []
        batch_raw_ingredient_cost = 0.0

        for ing in ingredients_rows:
            qty = ing["quantity_required"]
            unit_cost = ing["unit_cost_php"]
            batch_raw_ingredient_cost += qty * unit_cost
            recipe_ingredients.append(
                RecipeIngredient(
                    ingredient_name=ing["name"],
                    quantity_required=qty
                )
            )

        master_recipes[item_name] = {
            "recipe": ProductMasterRecipe(
                item_name=item_name,
                units_per_batch=prod["units_per_batch"],
                tray_capacity=prod["tray_capacity"],
                bake_time_minutes=prod["bake_time_minutes"],
                packaging_cost_per_unit=prod["packaging_cost_per_unit"],
                ingredients=recipe_ingredients
            ),
            "batch_raw_ingredient_cost": batch_raw_ingredient_cost,
            "default_retail_price": prod["default_retail_price"]
        }

    conn.close()
    return master_recipes


if __name__ == "__main__":
    init_db()
    print("Database initialized and baseline data seeded successfully.")
