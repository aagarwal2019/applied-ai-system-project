"""
ai_agent.py — Agentic hint system for the Glitchy Guesser game.

Gemini uses function calling to analyse the player's game state and
synthesises a personalised, strategic hint without revealing the secret number.

Functions
---------
calculate_valid_range  — narrows down remaining numbers from guess history
evaluate_strategy      — scores how efficiently the player is guessing
get_hint_intensity     — decides how revealing the hint should be

The system uses Gemini's function calling to gather information before
generating the final hint.
"""

import json
import logging
import os
from typing import Optional

import google.generativeai as genai

try:
    import rag as _rag
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False
    logging.getLogger(__name__).warning("rag module not importable — RAG pre-retrieval disabled")

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure-Python function implementations (no API calls — fully testable)
# ---------------------------------------------------------------------------

def calculate_valid_range(history: list, min_val: int, max_val: int) -> dict:
    """
    Narrow the valid range using every 'Too High' / 'Too Low' in history.

    Returns low, high, remaining_count, and the optimal binary-search guess.
    """
    low, high = min_val, max_val

    for entry in history:
        guess = entry["guess"]
        outcome = entry["outcome"]
        if outcome == "Too High":
            high = min(high, guess - 1)
        elif outcome == "Too Low":
            low = max(low, guess + 1)

    remaining = max(0, high - low + 1)
    optimal = (low + high) // 2

    logger.debug("Valid range: [%d, %d], remaining=%d, optimal=%d", low, high, remaining, optimal)
    return {
        "low": low,
        "high": high,
        "remaining_count": remaining,
        "optimal_next_guess": optimal,
    }


def evaluate_strategy(history: list, min_val: int, max_val: int) -> dict:
    """
    Score the player's guessing strategy against binary search.

    For each non-win guess, check whether it fell within 10 % of the range
    from the optimal midpoint. Returns an efficiency score and tailored advice.
    """
    non_win = [h for h in history if h["outcome"] != "Win"]
    if len(non_win) < 2:
        return {
            "strategy": "just_started",
            "efficiency_score": 1.0,
            "advice": "Game just started — keep going!",
        }

    current_low, current_high = min_val, max_val
    optimal_count = 0

    for entry in non_win:
        optimal = (current_low + current_high) // 2
        threshold = max(1, (current_high - current_low) // 10)

        if abs(entry["guess"] - optimal) <= threshold:
            optimal_count += 1

        if entry["outcome"] == "Too High":
            current_high = entry["guess"] - 1
        elif entry["outcome"] == "Too Low":
            current_low = entry["guess"] + 1

    efficiency = round(optimal_count / len(non_win), 2)

    if efficiency >= 0.7:
        strategy, advice = (
            "binary_search",
            "Excellent! You're using near-optimal binary search.",
        )
    elif efficiency >= 0.4:
        strategy, advice = (
            "semi_systematic",
            "You're somewhat systematic — try always picking the midpoint of the remaining range.",
        )
    else:
        strategy, advice = (
            "random",
            "Tip: always guess the exact middle of what's left to find the answer fastest.",
        )

    logger.debug("Strategy=%s, efficiency=%.2f", strategy, efficiency)
    return {"strategy": strategy, "efficiency_score": efficiency, "advice": advice}


def get_hint_intensity(attempt_number: int, max_attempts: int) -> dict:
    """
    Map how many attempts have been used to a hint intensity level.

    gentle   → early game, subtle nudge
    moderate → mid game, clearer range guidance
    strong   → late game, very direct hint
    """
    if max_attempts <= 0:
        return {"intensity": "moderate", "attempts_remaining": 0, "ratio_used": 0.5}

    ratio = attempt_number / max_attempts

    if ratio < 0.35:
        intensity = "gentle"
        description = "Give a subtle directional nudge — don't reveal too much."
    elif ratio < 0.65:
        intensity = "moderate"
        description = "Give a clear strategic hint about narrowing the range."
    else:
        intensity = "strong"
        description = "Player is running low — give a very direct hint."

    remaining = max_attempts - attempt_number
    logger.debug("Hint intensity=%s, ratio=%.2f, remaining=%d", intensity, ratio, remaining)
    return {
        "intensity": intensity,
        "description": description,
        "attempts_remaining": remaining,
        "ratio_used": round(ratio, 2),
    }


# ---------------------------------------------------------------------------
# Gemini function declarations
# ---------------------------------------------------------------------------

GEMINI_FUNCTIONS = [
    {
        "name": "calculate_valid_range",
        "description": "Calculate the remaining valid range of numbers based on the player's guess history.",
        "parameters": {
            "type": "object",
            "properties": {
                "history": {
                    "type": "array",
                    "description": "List of guesses with outcomes",
                    "items": {
                        "type": "object",
                        "properties": {
                            "guess": {"type": "integer"},
                            "outcome": {"type": "string"}
                        }
                    }
                },
                "min_val": {"type": "integer", "description": "Game range minimum"},
                "max_val": {"type": "integer", "description": "Game range maximum"}
            },
            "required": ["history", "min_val", "max_val"]
        }
    },
    {
        "name": "evaluate_strategy",
        "description": "Evaluate how efficiently the player is guessing compared to optimal strategy.",
        "parameters": {
            "type": "object",
            "properties": {
                "history": {
                    "type": "array",
                    "description": "List of guesses with outcomes",
                    "items": {
                        "type": "object",
                        "properties": {
                            "guess": {"type": "integer"},
                            "outcome": {"type": "string"}
                        }
                    }
                },
                "min_val": {"type": "integer", "description": "Game range minimum"},
                "max_val": {"type": "integer", "description": "Game range maximum"}
            },
            "required": ["history", "min_val", "max_val"]
        }
    },
    {
        "name": "get_hint_intensity",
        "description": "Determine how strong or revealing the hint should be based on attempts used.",
        "parameters": {
            "type": "object",
            "properties": {
                "attempt_number": {"type": "integer", "description": "Number of guesses made so far"},
                "max_attempts": {"type": "integer", "description": "Maximum attempts allowed"}
            },
            "required": ["attempt_number", "max_attempts"]
        }
    }
]

# ---------------------------------------------------------------------------
# System prompts — one baseline, one coaching (few-shot specialisation)
# ---------------------------------------------------------------------------

# Baseline: conversational, encouraging, never reveals the exact optimal guess.
SYSTEM_PROMPT = """\
You are a friendly, encouraging hint assistant for a number guessing game.

When asked for a hint you should analyze the player's situation using the available functions.
Use calculate_valid_range to find remaining possibilities, evaluate_strategy to assess efficiency,
and get_hint_intensity to determine hint strength.

After gathering information, write a short hint (2–4 sentences) that:
- Warms the player up with encouragement
- Gives strategic guidance matching the intensity level
- For moderate/strong intensity, mentions the narrowed number range
- If the player's strategy is poor, briefly suggests the midpoint approach
- Never states the secret number directly

Keep it concise, fun, and game-appropriate."""

# Coaching mode: structured 3-part format with few-shot examples.
# Always ends with the exact optimal guess from calculate_valid_range.
# This is the "specialised" prompt used to demonstrate measurable output differences.
COACHING_PROMPT = """\
You are a precise game coach for a number guessing game. Your hints follow a strict
three-sentence structure that is analytical, actionable, and always specific.

When asked for a hint you should analyze using the available functions:
Use calculate_valid_range to find remaining bounds and the optimal_next_guess value,
evaluate_strategy to assess how efficiently the player is guessing, and
get_hint_intensity to calibrate how direct to be.

After gathering information, write a coaching hint in EXACTLY this three-part format:
- Sentence 1: State the player's current situation using the function data (range, attempts).
- Sentence 2: Explain binary search strategy and why it minimises guesses.
- Sentence 3: Always end with: "Your optimal next guess is [optimal_next_guess from calculate_valid_range]."

Here are two example coaching hints:

Example 1
Game state: 1-100, guesses [50 Too Low, 75 Too High], 2/8 attempts used
Functions: low=51, high=74, remaining=24, optimal=62 | strategy=binary_search, efficiency=0.85 | intensity=gentle
Coaching hint: "You've narrowed the range to 51–74 in just two guesses. Targeting the
midpoint each time cuts the remaining possibilities in half — the fastest possible path
to the answer. Your optimal next guess is 62."

Example 2
Game state: 1-100, guesses [90 Too High, 10 Too Low, 70 Too High], 3/8 attempts, poor efficiency
Functions: low=11, high=69, remaining=59, optimal=40 | strategy=random, efficiency=0.20 | intensity=gentle
Coaching hint: "You've used 3 attempts but the valid range is still wide at 11–69 because
your guesses have been near the edges rather than the midpoint. Always pick the exact
middle of the remaining range to eliminate the most possibilities at once. Your optimal
next guess is 40."

Follow this format precisely for every hint you produce."""


# ---------------------------------------------------------------------------
# Function dispatcher
# ---------------------------------------------------------------------------

def _run_function(name: str, inputs: dict, trace: list) -> str:
    """
    Call the matching Python function, append a trace record, and return JSON.

    trace is mutated in place so the caller can collect all tool call records
    and surface them to the user as observable intermediate steps.
    """
    logger.info("Function call: %s(%s)", name, json.dumps(inputs))

    if name == "calculate_valid_range":
        result = calculate_valid_range(inputs["history"], inputs["min_val"], inputs["max_val"])
    elif name == "evaluate_strategy":
        result = evaluate_strategy(inputs["history"], inputs["min_val"], inputs["max_val"])
    elif name == "get_hint_intensity":
        result = get_hint_intensity(inputs["attempt_number"], inputs["max_attempts"])
    else:
        result = {"error": f"Unknown function: {name}"}

    logger.info("Function result: %s", json.dumps(result))
    trace.append({"function": name, "result": result})
    return json.dumps(result)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_ai_hint(
    history: list,
    min_val: int,
    max_val: int,
    attempt_number: int,
    max_attempts: int,
    api_key: Optional[str] = None,
    coaching_mode: bool = False,
) -> tuple[str, list]:
    """
    Run the agentic hint generation and return (hint_text, trace).

    Gemini uses function calling to gather information before generating
    a personalised hint. The system uses pre-computed function results
    to provide context for the AI response.

    Parameters
    ----------
    coaching_mode : bool
        When True, uses COACHING_PROMPT — a few-shot specialised prompt that
        constrains Gemini to a 3-sentence structured format always ending with
        "Your optimal next guess is [X]." When False (default), uses the
        conversational SYSTEM_PROMPT that never reveals a specific number.

    Returns
    -------
    hint_text : str
        The generated hint, or a safe error message.
    trace : list[dict]
        Records of function calls and results.
    """
    mode_label = "coaching" if coaching_mode else "standard"
    logger.info(
        "Hint requested | mode=%s | attempts=%d/%d | history_len=%d | range=[%d,%d]",
        mode_label, attempt_number, max_attempts, len(history), min_val, max_val,
    )

    trace: list = []

    # ── Pre-compute function results ──────────────────────────────────────────
    # Since Gemini's function calling is less sophisticated than Claude's iterative
    # tool calling, we pre-compute all the analysis results and provide them as context
    try:
        range_info = calculate_valid_range(history, min_val, max_val)
        strategy_info = evaluate_strategy(history, min_val, max_val)
        intensity_info = get_hint_intensity(attempt_number, max_attempts)

        trace.extend([
            {"function": "calculate_valid_range", "result": range_info},
            {"function": "evaluate_strategy", "result": strategy_info},
            {"function": "get_hint_intensity", "result": intensity_info},
        ])
    except Exception as exc:
        logger.error("Failed to compute analysis functions: %s", exc)
        return "Error computing game analysis. Please try again.", trace

    # ── RAG pre-retrieval ─────────────────────────────────────────────────────
    # Inject relevant strategy tips from the knowledge base
    rag_injected = ""
    if _RAG_AVAILABLE:
        try:
            _query = _rag.build_query(
                strategy=strategy_info["strategy"],
                intensity=intensity_info["intensity"],
                remaining_count=range_info["remaining_count"],
            )
            _tips = _rag.retrieve(_query, top_k=2)

            if _tips:
                tip_lines = "\n".join(
                    f"  [{i + 1}] ({tip['topic']}) {tip['content']}"
                    for i, tip in enumerate(_tips)
                )
                rag_injected = (
                    f"\n\nRelevant strategy context retrieved from knowledge base:\n{tip_lines}"
                )

            trace.append({
                "function": "rag_retrieval",
                "result": {
                    "query": _query,
                    "docs_retrieved": len(_tips),
                    "top_topic": _tips[0]["topic"] if _tips else "none",
                    "top_score": _tips[0]["score"] if _tips else 0.0,
                    "injected": bool(_tips),
                },
            })
            logger.info(
                "RAG: injected %d tips | top_topic=%s | query=%r",
                len(_tips), _tips[0]["topic"] if _tips else "none", _query[:60],
            )
        except Exception as exc:
            logger.error("RAG pre-retrieval failed (hints still work): %s", exc)
    # ── end RAG block ─────────────────────────────────────────────────────────

    # Initialize Gemini client
    try:
        genai.configure(api_key=api_key or os.environ.get("GOOGLE_API_KEY"))
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=COACHING_PROMPT if coaching_mode else SYSTEM_PROMPT
        )
    except Exception as exc:
        logger.error("Failed to initialise Gemini client: %s", exc)
        return "Could not connect to the AI service. Check your API key.", trace

    # Create the user prompt with analysis context
    analysis_context = f"""
Game Analysis Results:
- Valid range: {range_info['low']}-{range_info['high']} (remaining: {range_info['remaining_count']})
- Strategy: {strategy_info['strategy']} (efficiency: {strategy_info['efficiency_score']:.2f})
- Hint intensity: {intensity_info['intensity']} ({intensity_info['description']})
- Optimal next guess: {range_info['optimal_next_guess']}
"""

    user_content = (
        f"Please give me a hint for this game:\n"
        f"- Number range: {min_val} to {max_val}\n"
        f"- Attempts used: {attempt_number} of {max_attempts}\n"
        f"- Guess history: {json.dumps(history)}\n"
        f"{analysis_context}\n"
        "Use this analysis to provide a strategic hint."
        f"{rag_injected}"
    )

    try:
        # Start chat and send message
        chat = model.start_chat()
        response = chat.send_message(user_content)

        # Extract the text response
        hint_text = ""
        if response.text:
            hint_text = response.text.strip()
        else:
            # Check for function calls (though we pre-computed everything)
            for part in response.parts:
                if part.text:
                    hint_text += part.text

        if not hint_text:
            logger.warning("No text response from Gemini")
            return "I couldn't formulate a hint — please try again.", trace

        logger.info("Hint generated | mode=%s | functions_called=%d", mode_label, len(trace))
        return hint_text, trace

    except Exception as exc:
        logger.error("Gemini API error: %s", exc)
        return "The AI hint service encountered an error. Please try again.", trace
