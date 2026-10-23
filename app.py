import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
import gradio as gr
import pandas as pd
from dotenv import load_dotenv

from database import init_db
from ai_compiler import compile_taglish_intent
from logic import optimize_bakery_production
from charts import generate_revenue_breakdown_chart, generate_tray_allocation_pie_chart

# Ensure environment variables are loaded and DB is initialized
load_dotenv()
init_db()


def run_pipeline(user_prompt: str):
    """
    Orchestrates the end-to-end execution flow:
    1. Taglish Prompt -> AI Compiler (Gemini + Pydantic)
    2. Operational Targets -> Deterministic Math Engine (logic.py)
    3. Outputs -> Pandas DataFrames & Matplotlib Visualizations
    """
    if not user_prompt.strip():
        return (
            "⚠️ Please enter an operational instruction or target in Taglish.",
            None,
            None,
            None,
            None
        )

    try:
        # Step 1: Parse intent using Gemini API compiler
        parsed_target = compile_taglish_intent(user_prompt)

        # Step 2: Execute deterministic optimization logic
        summary = optimize_bakery_production(parsed_target)

        # Step 3: Format high-level KPI cards text
        kpi_text = f"""
### 📊 Operational Summary
* **Target Net Profit Met:** {'✅ YES' if summary.target_profit_met else '❌ NO'}
* **Net Profit:** ₱{summary.net_profit:,.2f}
* **Gross Revenue:** ₱{summary.gross_revenue:,.2f}
* **Total Variable Cost:** ₱{summary.total_variable_costs:,.2f}
* **Fixed Daily Overhead:** ₱{summary.fixed_overhead:,.2f}
* **Oven Capacity Utilized:** {summary.deck_capacity_utilized_pct}% ({summary.total_trays_allocated} trays)
"""

        # Step 4: Build Pandas DataFrame for tabular display
        table_data = []
        for item in summary.items:
            table_data.append({
                "Product": item.item_name,
                "True Unit Cost (₱)": f"₱{item.true_unit_cost:.2f}",
                "Retail Price (₱)": f"₱{item.retail_price:.2f}",
                "Clearance Price (₱)": f"₱{item.clearance_price:.2f}",
                "Demand (Pcs)": item.projected_demand_units,
                "Trays (Planchas)": item.trays_required,
                "Total Supply": item.total_supply_units,
                "Morning Sales": item.morning_expected_sales_units,
                "Afternoon Surplus": item.surplus_clearance_units,
                "Exp. Revenue (₱)": f"₱{item.expected_revenue:.2f}",
                "Net Margin (₱)": f"₱{item.net_margin_contribution:.2f}"
            })

        df_results = pd.DataFrame(table_data)

        # Step 5: Render Matplotlib analytical charts
        fig_revenue = generate_revenue_breakdown_chart(summary)
        fig_trays = generate_tray_allocation_pie_chart(summary)

        # Step 6: Format extracted JSON for transparency/debugging
        extracted_json = parsed_target.model_dump_json(indent=2)

        return kpi_text, df_results, fig_revenue, fig_trays, extracted_json

    except Exception as e:
        error_msg = f"❌ Execution Error: {str(e)}"
        return error_msg, None, None, None, None


# Build Gradio Blocks Dashboard Interface
with gr.Blocks(title="PanaderyaOptimizer Dashboard") as demo:
    gr.Markdown("""
# 🥖 PanaderyaOptimizer
### Intelligent Batch-Yield, Perishable Decay & Margin Sentinel for Filipino Bakeries
*Rooted in Innovation — CSSprint 2026*
""")

    with gr.Row():
        with gr.Column(scale=2):
            user_input = gr.Textbox(
                label="🗣️ Express Operational Target (Taglish)",
                placeholder="e.g., Gusto ko maubos ang Spanish bread bago mag-4 PM kahit breakeven lang, pero dapat umabot sa ₱1,200 ang net profit gamit ang Ensaymada at Cheese Bread.",
                lines=3
            )
            submit_btn = gr.Button("🚀 Calculate Optimal Yield & Margins", variant="primary")

            # Presets for quick evaluation
            gr.Examples(
                examples=[
                    ["Gusto ko maubos ang Spanish bread bago mag-4 PM kahit breakeven lang, pero dapat umabot sa ₱1,200 ang net profit gamit ang Ensaymada."],
                    ["Max 8 trays lang ang kasya sa oven ko ngayon. Paano ko ma-maximize ang profit gamit ang Pan de Sal at Ensaymada?"],
                    ["Target net profit ₱1,500 para sa buong araw. Bawasan ang Pan de Sal yield to 120 pieces."]
                ],
                inputs=user_input
            )

        with gr.Column(scale=1):
            kpi_output = gr.Markdown("### 📊 Operational Summary\n*Submit a prompt to view real-time yield analysis.*")

    gr.Markdown("---")

    with gr.Row():
        table_output = gr.Dataframe(
            label="📦 Product Batch Yield & Pricing Allocation Matrix",
            interactive=False
        )

    gr.Markdown("---")

    with gr.Row():
        with gr.Column():
            chart_revenue_output = gr.Plot(label="Revenue vs. Cost Breakdown")
        with gr.Column():
            chart_trays_output = gr.Plot(label="Deck Oven Tray Distribution")

    with gr.Accordion("🔍 View Extracted AI Structured Constraints (Rule C.4.c Verification)", open=False):
        json_output = gr.Code(language="json", label="Pydantic Validated JSON Output")

    # Bind execution event
    submit_btn.click(
        fn=run_pipeline,
        inputs=[user_input],
        outputs=[kpi_output, table_output, chart_revenue_output, chart_trays_output, json_output]
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", share=False, theme=gr.themes.Soft())
