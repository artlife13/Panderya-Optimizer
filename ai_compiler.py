import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
from dotenv import load_dotenv
from google import genai
from google.genai import types
from schema import BakeryOperationalTarget, ItemConstraint

# Load environment variables from .env file
load_dotenv()

SYSTEM_INSTRUCTION = """
You are an expert operational intent compiler for PanaderyaOptimizer, a system designed for Filipino community bakeries.
Your sole job is to translate conversational Taglish (Tagalog-English code-switched) user prompts into a structured JSON representation of operational goals and constraints.

CRITICAL RULES:
1. Do NOT perform any mathematical calculations, profit estimates, or tray allocations. Focus strictly on extracting user intentions, stated targets, and explicit constraints.
2. Parse product names accurately (e.g., "Pan de Sal", "Spanish Bread", "Ensaymada", "Cheese Bread").
3. Identify target demands, clearance deadlines, minimum acceptable margin goals, and operational roles when mentioned.
4. Extract explicit monetary targets (e.g., target net profit in PHP) or oven capacity constraints if provided by the baker.
5. You must return structured output adhering strictly to the provided JSON schema.
"""


def get_genai_client() -> genai.Client:
    """Instantiates and returns the Google GenAI SDK client."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing in .env file.")
    return genai.Client(api_key=api_key)


def fallback_heuristic_parse(user_prompt: str) -> BakeryOperationalTarget:
    """
    Offline fallback parser (Rule C.4.c / Section 7 Offline Resilience).
    Extracts constraints using regex heuristics when offline or if GEMINI_API_KEY is not configured.
    """
    import re
    # 1. Target profit extraction
    profit_match = re.search(r'(?:₱|php|net profit|profit\s*(?:ng|na|of)?\s*(?:₱|php)?)\s*([\d,]+)', user_prompt, re.IGNORECASE)
    target_net_profit = float(profit_match.group(1).replace(',', '')) if profit_match else None

    # 2. Oven capacity extraction
    trays_match = re.search(r'(\d+)\s*(?:trays|planchas|plancha|tray)', user_prompt, re.IGNORECASE)
    max_trays = int(trays_match.group(1)) if trays_match else None

    # 3. Item constraints detection
    item_constraints = []
    known_items = ["Spanish Bread", "Pan de Sal", "Ensaymada", "Cheese Bread"]
    prompt_lower = user_prompt.lower()

    for item in known_items:
        if item.lower() in prompt_lower:
            role = "standard"
            min_margin = "standard"
            deadline = None
            demand = None

            # Check for breakeven
            if "breakeven" in prompt_lower and item.lower() in prompt_lower:
                min_margin = "breakeven"
                role = "salvage_only"

            # Check for profit driver
            if any(term in prompt_lower for term in ["profit", "kumita", "maximize"]) and item.lower() in prompt_lower:
                role = "profit_driver"

            # Check for time deadline (e.g. 4 PM, 16:00)
            time_match = re.search(r'(?:bago mag-|before\s*)(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)', prompt_lower)
            if time_match:
                deadline = time_match.group(1).strip()

            # Check for specific demand numbers
            demand_match = re.search(rf'{re.escape(item.lower())}\s*(?:yield|demand|na)?\s*(?:to|ng)?\s*(\d+)', prompt_lower)
            if demand_match:
                demand = int(demand_match.group(1))

            item_constraints.append(
                ItemConstraint(
                    item_name=item,
                    target_demand_units=demand,
                    clearance_deadline=deadline,
                    min_acceptable_margin=min_margin,
                    role=role
                )
            )

    return BakeryOperationalTarget(
        target_net_profit=target_net_profit,
        max_oven_capacity_trays=max_trays,
        shift_duration_hours=8.0,
        item_constraints=item_constraints
    )


def compile_taglish_intent(user_prompt: str) -> BakeryOperationalTarget:
    """
    Ingests a Taglish conversational prompt from a baker, calls Gemini API
    with Pydantic schema enforcement, and returns a validated BakeryOperationalTarget object.
    Falls back gracefully to offline heuristic parsing if key is missing or offline.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_actual_api_key_here":
        print("Notice: No valid GEMINI_API_KEY found in .env. Using offline heuristic compiler.")
        return fallback_heuristic_parse(user_prompt)

    try:
        client = get_genai_client()
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=BakeryOperationalTarget,
                temperature=0.1,  # Low temperature for deterministic, reliable parsing
            ),
        )
        parsed_target: BakeryOperationalTarget = response.parsed
        return parsed_target
    except Exception as e:
        print(f"Notice: Gemini API call failed ({e}). Falling back to offline heuristic compiler.")
        return fallback_heuristic_parse(user_prompt)


if __name__ == "__main__":
    # Test execution with example Taglish prompt
    test_prompt = (
        "Gusto ko maubos ang Spanish bread bago mag-4 PM kahit breakeven lang, "
        "pero dapat umabot sa ₱1,200 ang net profit gamit ang Ensaymada at Cheese Bread. "
        "Max 10 trays lang kasya sa oven ko."
    )
    print("Parsing sample Taglish prompt:")
    print(f"'{test_prompt}'\n")

    try:
        compiled_target = compile_taglish_intent(test_prompt)
        print("--- AI COMPILER EXTRACTED STRUCTURED TARGET ---")
        print(compiled_target.model_dump_json(indent=2))
        print("-----------------------------------------------")
    except Exception as e:
        print(f"Error compiling prompt: {e}")
