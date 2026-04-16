"""
ai_agent.py — Agentic hint system for the Glitchy Guesser game.

Claude uses three tools in a reasoning loop to analyse the player's game
state, then synthesises a personalised, strategic hint without revealing
the secret number.

Tools
-----
calculate_valid_range  — narrows down remaining numbers from guess history
evaluate_strategy      — scores how efficiently the player is guessing
get_hint_intensity     — decides how revealing the hint should be

The system prompt is marked for prompt caching so repeated hint requests
in the same Streamlit session reuse the cached prefix.
"""

import json
import logging
import os
from typing import Optional

import anthropic

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure-Python tool implementations (no API calls — fully testable)
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
# Tool schema definitions (sent to Claude)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "calculate_valid_range",
        "description": (
            "Calculate the remaining valid range of numbers based on the player's "
            "guess history. Uses every 'Too High' and 'Too Low' result to narrow "
            "down the bounds. Returns low, high, remaining_count, and the optimal "
            "next guess (midpoint of remaining range)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "history": {
                    "type": "array",
                    "description": "List of guesses. Each item has 'guess' (int) and 'outcome' (str).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "guess": {"type": "integer"},
                            "outcome": {"type": "string"},
                        },
                    },
                },
                "min_val": {"type": "integer", "description": "Game range minimum (inclusive)."},
                "max_val": {"type": "integer", "description": "Game range maximum (inclusive)."},
            },
            "required": ["history", "min_val", "max_val"],
        },
    },
    {
        "name": "evaluate_strategy",
        "description": (
            "Evaluate how efficiently the player is guessing. Compares each guess "
            "against the theoretically optimal binary-search midpoint and returns "
            "an efficiency score (0–1) and tailored strategic advice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "history": {
                    "type": "array",
                    "description": "List of guesses with outcomes.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "guess": {"type": "integer"},
                            "outcome": {"type": "string"},
                        },
                    },
                },
                "min_val": {"type": "integer", "description": "Game range minimum."},
                "max_val": {"type": "integer", "description": "Game range maximum."},
            },
            "required": ["history", "min_val", "max_val"],
        },
    },
    {
        "name": "get_hint_intensity",
        "description": (
            "Determine how strong or revealing the hint should be based on how many "
            "attempts the player has already used. Returns gentle / moderate / strong "
            "and describes what kind of hint to give."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "attempt_number": {
                    "type": "integer",
                    "description": "Number of guesses made so far.",
                },
                "max_attempts": {
                    "type": "integer",
                    "description": "Maximum attempts allowed in this game.",
                },
            },
            "required": ["attempt_number", "max_attempts"],
        },
    },
]

# ---------------------------------------------------------------------------
# System prompts — one baseline, one coaching (few-shot specialisation)
# ---------------------------------------------------------------------------

# Baseline: conversational, encouraging, never reveals the exact optimal guess.
SYSTEM_PROMPT = """\
You are a friendly, encouraging hint assistant for a number guessing game.

When asked for a hint you MUST use all three tools in this order:
1. `calculate_valid_range`  — find what numbers are still possible
2. `evaluate_strategy`      — judge how efficiently the player is guessing
3. `get_hint_intensity`     — decide how direct to be

After calling all three tools, write a short hint (2–4 sentences) that:
- Warms the player up with encouragement
- Gives strategic guidance matching the intensity level
- For moderate/strong intensity, mentions the narrowed number range
- If the player's strategy is poor, briefly suggests the midpoint approach
- Never states the secret number directly (even if you could calculate it)

Keep it concise, fun, and game-appropriate."""

# Coaching mode: structured 3-part format with few-shot examples.
# Always ends with the exact optimal guess from calculate_valid_range.
# This is the "specialised" prompt used to demonstrate measurable output differences.
COACHING_PROMPT = """\
You are a precise game coach for a number guessing game. Your hints follow a strict
three-sentence structure that is analytical, actionable, and always specific.

When asked for a hint you MUST use all three tools in this order:
1. `calculate_valid_range`  — find remaining bounds and the optimal_next_guess value
2. `evaluate_strategy`      — assess how efficiently the player is guessing
3. `get_hint_intensity`     — calibrate how direct to be

After calling all three tools, write a coaching hint in EXACTLY this three-part format:
- Sentence 1: State the player's current situation using the tool data (range, attempts).
- Sentence 2: Explain binary search strategy and why it minimises guesses.
- Sentence 3: Always end with: "Your optimal next guess is [optimal_next_guess from calculate_valid_range]."

Here are two example coaching hints:

Example 1
Game state: 1-100, guesses [50 Too Low, 75 Too High], 2/8 attempts used
Tools: low=51, high=74, remaining=24, optimal=62 | strategy=binary_search, efficiency=0.85 | intensity=gentle
Coaching hint: "You've narrowed the range to 51–74 in just two guesses. Targeting the
midpoint each time cuts the remaining possibilities in half — the fastest possible path
to the answer. Your optimal next guess is 62."

Example 2
Game state: 1-100, guesses [90 Too High, 10 Too Low, 70 Too High], 3/8 attempts, poor efficiency
Tools: low=11, high=69, remaining=59, optimal=40 | strategy=random, efficiency=0.20 | intensity=gentle
Coaching hint: "You've used 3 attempts but the valid range is still wide at 11–69 because
your guesses have been near the edges rather than the midpoint. Always pick the exact
middle of the remaining range to eliminate the most possibilities at once. Your optimal
next guess is 40."

Follow this format precisely for every hint you produce."""


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def _run_tool(name: str, inputs: dict, trace: list) -> str:
    """
    Call the matching Python function, append a trace record, and return JSON.

    trace is mutated in place so the caller can collect all tool call records
    and surface them to the user as observable intermediate steps.
    """
    logger.info("Tool call: %s(%s)", name, json.dumps(inputs))

    if name == "calculate_valid_range":
        result = calculate_valid_range(inputs["history"], inputs["min_val"], inputs["max_val"])
    elif name == "evaluate_strategy":
        result = evaluate_strategy(inputs["history"], inputs["min_val"], inputs["max_val"])
    elif name == "get_hint_intensity":
        result = get_hint_intensity(inputs["attempt_number"], inputs["max_attempts"])
    else:
        result = {"error": f"Unknown tool: {name}"}

    logger.info("Tool result: %s", json.dumps(result))
    trace.append({"tool": name, "result": result})
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
    Run the agentic hint loop and return (hint_text, trace).

    Claude calls tools iteratively until it has gathered enough information
    to write a personalised hint.  Both system prompts are sent with
    `cache_control` so repeated calls within a session reuse the cached prefix.

    Parameters
    ----------
    coaching_mode : bool
        When True, uses COACHING_PROMPT — a few-shot specialised prompt that
        constrains Claude to a 3-sentence structured format always ending with
        "Your optimal next guess is [X]."  When False (default), uses the
        conversational SYSTEM_PROMPT that never reveals a specific number.

    Returns
    -------
    hint_text : str
        The generated hint, or a safe error message.
    trace : list[dict]
        One record per tool call: {"tool": name, "result": {...}}.
        Empty if the call fails before any tools run.
    """
    mode_label = "coaching" if coaching_mode else "standard"
    logger.info(
        "Hint requested | mode=%s | attempts=%d/%d | history_len=%d | range=[%d,%d]",
        mode_label, attempt_number, max_attempts, len(history), min_val, max_val,
    )

    trace: list = []

    # Build client — prefer explicit key, then env var (loaded by dotenv in app.py)
    try:
        client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    except Exception as exc:
        logger.error("Failed to initialise Anthropic client: %s", exc)
        return "Could not connect to the AI service. Check your API key.", trace

    prompt_text = COACHING_PROMPT if coaching_mode else SYSTEM_PROMPT

    user_content = (
        f"Please give me a hint for this game:\n"
        f"- Number range: {min_val} to {max_val}\n"
        f"- Attempts used: {attempt_number} of {max_attempts}\n"
        f"- Guess history: {json.dumps(history)}\n\n"
        "Use your tools to analyse my situation, then provide a strategic hint."
    )

    messages = [{"role": "user", "content": user_content}]

    for iteration in range(1, 11):  # Safety cap: max 10 tool-call rounds
        logger.info("Agent iteration %d", iteration)

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                system=[
                    {
                        "type": "text",
                        "text": prompt_text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.AuthenticationError:
            logger.error("Invalid Anthropic API key")
            return "Invalid API key — please check your ANTHROPIC_API_KEY.", trace
        except anthropic.RateLimitError:
            logger.warning("Rate limit hit")
            return "Rate limit reached — please wait a moment and try again.", trace
        except anthropic.APIConnectionError as exc:
            logger.error("Network error: %s", exc)
            return "Network error — check your connection and try again.", trace
        except anthropic.APIError as exc:
            logger.error("Claude API error: %s", exc)
            return "The AI hint service encountered an error. Please try again.", trace

        logger.info("stop_reason=%s | blocks=%d", response.stop_reason, len(response.content))

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    logger.info(
                        "Hint generated | mode=%s | iterations=%d | tools_called=%d",
                        mode_label, iteration, len(trace),
                    )
                    return block.text, trace
            logger.warning("end_turn reached with no text block")
            return "I couldn't formulate a hint — please try again.", trace

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = [
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _run_tool(block.name, block.input, trace),
                }
                for block in response.content
                if block.type == "tool_use"
            ]
            messages.append({"role": "user", "content": tool_results})
        else:
            logger.warning("Unexpected stop_reason: %s — aborting", response.stop_reason)
            break

    logger.error("Agent exceeded max iterations without completing")
    return "Hint generation timed out — please try again.", trace
