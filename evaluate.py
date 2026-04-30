"""
evaluate.py — Reliability evaluation script for the Glitchy Guesser AI system.

Runs predefined test cases against every component and prints a structured
pass/fail report. The core evaluation requires no API key — all agent tool
functions are pure Python and tested directly.

An optional end-to-end hint test (--api flag) calls the live Google AI API
to verify that the full agentic loop returns a usable hint string.

Usage:
    python evaluate.py          # core evaluation only (no API key needed)
    python evaluate.py --api    # also runs live API round-trip test
"""

import os
import sys
from dataclasses import dataclass
from typing import Any, Callable

from dotenv import load_dotenv

from ai_agent import calculate_valid_range, evaluate_strategy, get_hint_intensity
from logic_utils import check_guess, get_range_for_difficulty, parse_guess, update_score
from rag import build_query, retrieve

load_dotenv(override=True)


# ─────────────────────────────────────────────────────────────────────────────
# Test infrastructure
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Case:
    name: str
    description: str
    fn: Callable
    args: tuple
    expect: Callable[[Any], bool]   # returns True if the result is acceptable


@dataclass
class Result:
    name: str
    description: str
    passed: bool
    actual: Any
    error: str | None = None


def run(cases: list[Case]) -> list[Result]:
    results = []
    for c in cases:
        try:
            actual = c.fn(*c.args)
            passed = c.expect(actual)
        except Exception as exc:
            actual = None
            passed = False
            results.append(Result(c.name, c.description, passed, actual, str(exc)))
            continue
        results.append(Result(c.name, c.description, passed, actual))
    return results


def bar(passed: int, total: int, width: int = 20) -> str:
    filled = int(width * passed / total) if total else 0
    return "█" * filled + "░" * (width - filled)


def print_section(title: str, results: list[Result]) -> tuple[int, int]:
    p = sum(r.passed for r in results)
    t = len(results)
    pct = int(100 * p / t) if t else 0
    print(f"\n  {title}")
    print(f"  {'─' * 56}")
    for r in results:
        icon = "✅" if r.passed else "❌"
        print(f"    {icon}  {r.name}")
        print(f"         {r.description}")
        if not r.passed:
            if r.error:
                print(f"         → ERROR: {r.error}")
            else:
                print(f"         → Got: {r.actual}")
    print(f"\n  Result: {p}/{t}  {bar(p, t)}  {pct}%")
    return p, t


# ─────────────────────────────────────────────────────────────────────────────
# Test cases
# ─────────────────────────────────────────────────────────────────────────────

INPUT_VALIDATION_CASES = [
    Case(
        name="Valid integer string",
        description="'42' → (True, 42, None)",
        fn=parse_guess,
        args=("42",),
        expect=lambda r: r == (True, 42, None),
    ),
    Case(
        name="Float string truncates to int",
        description="'7.9' → (True, 7, None)",
        fn=parse_guess,
        args=("7.9",),
        expect=lambda r: r[0] is True and r[1] == 7,
    ),
    Case(
        name="Empty string rejected",
        description="'' → (False, None, error message)",
        fn=parse_guess,
        args=("",),
        expect=lambda r: r[0] is False and r[1] is None,
    ),
    Case(
        name="Non-numeric string rejected",
        description="'hello' → (False, None, error message)",
        fn=parse_guess,
        args=("hello",),
        expect=lambda r: r[0] is False and r[1] is None,
    ),
    Case(
        name="None input rejected",
        description="None → (False, None, error message)",
        fn=parse_guess,
        args=(None,),
        expect=lambda r: r[0] is False and r[1] is None,
    ),
]

GAME_LOGIC_CASES = [
    Case(
        name="Exact guess → Win",
        description="check_guess(50, 50) == 'Win'",
        fn=check_guess,
        args=(50, 50),
        expect=lambda r: r == "Win",
    ),
    Case(
        name="Guess too high",
        description="check_guess(70, 50) == 'Too High'",
        fn=check_guess,
        args=(70, 50),
        expect=lambda r: r == "Too High",
    ),
    Case(
        name="Guess too low",
        description="check_guess(30, 50) == 'Too Low'",
        fn=check_guess,
        args=(30, 50),
        expect=lambda r: r == "Too Low",
    ),
    Case(
        name="Win awards positive points",
        description="update_score(0, 'Win', 1) > 0",
        fn=update_score,
        args=(0, "Win", 1),
        expect=lambda r: r > 0,
    ),
    Case(
        name="Wrong guess deducts 5 points",
        description="update_score(50, 'Too High', 3) == 45",
        fn=update_score,
        args=(50, "Too High", 3),
        expect=lambda r: r == 45,
    ),
    Case(
        name="Late win still awards minimum 10 pts",
        description="update_score(0, 'Win', 100) >= 10",
        fn=update_score,
        args=(0, "Win", 100),
        expect=lambda r: r >= 10,
    ),
    Case(
        name="Easy difficulty range",
        description="get_range_for_difficulty('Easy') == (1, 20)",
        fn=get_range_for_difficulty,
        args=("Easy",),
        expect=lambda r: r == (1, 20),
    ),
    Case(
        name="Hard difficulty range",
        description="get_range_for_difficulty('Hard') == (1, 200)",
        fn=get_range_for_difficulty,
        args=("Hard",),
        expect=lambda r: r == (1, 200),
    ),
]

AGENT_TOOL_CASES = [
    Case(
        name="No history → full range returned",
        description="calculate_valid_range([], 1, 100) → low=1, high=100, remaining=100",
        fn=calculate_valid_range,
        args=([], 1, 100),
        expect=lambda r: r["low"] == 1 and r["high"] == 100 and r["remaining_count"] == 100,
    ),
    Case(
        name="Too High narrows upper bound",
        description="Guess 80 Too High → high becomes 79",
        fn=calculate_valid_range,
        args=([{"guess": 80, "outcome": "Too High"}], 1, 100),
        expect=lambda r: r["high"] == 79 and r["low"] == 1,
    ),
    Case(
        name="Too Low narrows lower bound",
        description="Guess 30 Too Low → low becomes 31",
        fn=calculate_valid_range,
        args=([{"guess": 30, "outcome": "Too Low"}], 1, 100),
        expect=lambda r: r["low"] == 31 and r["high"] == 100,
    ),
    Case(
        name="Multiple guesses narrow correctly",
        description="Guess 50 Too Low, 75 Too High → range [51,74]",
        fn=calculate_valid_range,
        args=(
            [{"guess": 50, "outcome": "Too Low"}, {"guess": 75, "outcome": "Too High"}],
            1, 100,
        ),
        expect=lambda r: r["low"] == 51 and r["high"] == 74 and r["remaining_count"] == 24,
    ),
    Case(
        name="Win entries ignored in range calculation",
        description="Win entries do not shift bounds",
        fn=calculate_valid_range,
        args=([{"guess": 50, "outcome": "Too Low"}, {"guess": 75, "outcome": "Win"}], 1, 100),
        expect=lambda r: r["low"] == 51 and r["high"] == 100,
    ),
    Case(
        name="Binary search player scores highly",
        description="Player targeting midpoints → efficiency >= 0.7",
        fn=evaluate_strategy,
        args=(
            [
                {"guess": 50, "outcome": "Too Low"},   # optimal ~50 ✓
                {"guess": 75, "outcome": "Too High"},  # optimal 75  ✓
                {"guess": 62, "outcome": "Too High"},  # optimal 62  ✓
            ],
            1, 100,
        ),
        expect=lambda r: r["efficiency_score"] >= 0.7 and r["strategy"] == "binary_search",
    ),
    Case(
        name="Random player scores poorly",
        description="Player always picking edge values → efficiency < 0.4",
        fn=evaluate_strategy,
        args=(
            [
                {"guess": 2, "outcome": "Too Low"},
                {"guess": 3, "outcome": "Too Low"},
                {"guess": 4, "outcome": "Too Low"},
            ],
            1, 100,
        ),
        expect=lambda r: r["efficiency_score"] < 0.4 and r["strategy"] == "random",
    ),
    Case(
        name="Early game → gentle hint",
        description="1/8 attempts used → intensity='gentle'",
        fn=get_hint_intensity,
        args=(1, 8),
        expect=lambda r: r["intensity"] == "gentle",
    ),
    Case(
        name="Mid game → moderate hint",
        description="4/8 attempts used → intensity='moderate'",
        fn=get_hint_intensity,
        args=(4, 8),
        expect=lambda r: r["intensity"] == "moderate",
    ),
    Case(
        name="Late game → strong hint",
        description="7/8 attempts used → intensity='strong'",
        fn=get_hint_intensity,
        args=(7, 8),
        expect=lambda r: r["intensity"] == "strong",
    ),
    Case(
        name="Attempts remaining calculated correctly",
        description="get_hint_intensity(3, 8) → attempts_remaining=5",
        fn=get_hint_intensity,
        args=(3, 8),
        expect=lambda r: r["attempts_remaining"] == 5,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Optional: end-to-end API test
# ─────────────────────────────────────────────────────────────────────────────

RAG_RETRIEVAL_CASES = [
    Case(
        name="build_query returns non-empty string",
        description="build_query('random', 'strong', 45) → a non-empty string",
        fn=build_query,
        args=("random", "strong", 45),
        expect=lambda r: isinstance(r, str) and len(r) > 0,
    ),
    Case(
        name="retrieve returns list with required keys",
        description="retrieve('binary search midpoint', top_k=2) → 2 dicts each with id, topic, content, score",
        fn=retrieve,
        args=("binary search midpoint",),
        expect=lambda r: (
            isinstance(r, list)
            and len(r) == 2
            and all("id" in d and "topic" in d and "content" in d and "score" in d for d in r)
        ),
    ),
    Case(
        name="random strategy query surfaces pitfall document",
        description="Query for random+strong should retrieve random_guessing or edge_guessing or strong_hint topic",
        fn=lambda: retrieve(build_query("random", "strong", 45), top_k=2),
        args=(),
        expect=lambda r: any(
            "random" in d["topic"] or "pitfall" in d["topic"] or "strong" in d["topic"] or "edge" in d["topic"]
            for d in r
        ),
    ),
    Case(
        name="binary_search query surfaces binary_search or range document",
        description="Query for binary_search+gentle should retrieve a binary_search or range-related tip",
        fn=lambda: retrieve(build_query("binary_search", "gentle", 50), top_k=2),
        expect=lambda r: any(
            "binary_search" in d["topic"] or "range" in d["topic"] or "gentle" in d["topic"]
            for d in r
        ),
        args=(),
    ),
    Case(
        name="cosine similarity scores are in [0.0, 1.0]",
        description="All retrieved scores must be valid cosine similarities",
        fn=retrieve,
        args=("midpoint range narrowing optimal",),
        expect=lambda r: len(r) > 0 and all(0.0 <= d["score"] <= 1.0 for d in r),
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Optional: end-to-end API tests
# ─────────────────────────────────────────────────────────────────────────────

def run_api_test() -> Result:
    """
    Calls the live Google AI API (standard mode) with a realistic mid-game state
    and checks that a usable hint string comes back along with a non-empty trace.
    """
    from ai_agent import get_ai_hint

    sample_history = [
        {"guess": 50, "outcome": "Too Low", "hot_cold": "🌡️ Warm"},
        {"guess": 75, "outcome": "Too High", "hot_cold": "♨️ Hot"},
    ]

    hint, trace = get_ai_hint(
        history=sample_history,
        min_val=1,
        max_val=100,
        attempt_number=2,
        max_attempts=8,
    )

    error_prefixes = (
        "Could not", "Invalid API", "Network error",
        "Rate limit", "AI hint service", "Hint generation",
    )
    is_real_hint = (
        isinstance(hint, str)
        and len(hint) > 20
        and not any(hint.startswith(p) for p in error_prefixes)
        and len(trace) == 3  # All three tools must have been called
    )

    detail = f'hint="{hint[:80]}…" | tools_called={len(trace)}'
    return Result(
        name="End-to-end API round-trip (standard mode)",
        description="Verifies a non-error hint and 3-tool trace are returned",
        passed=is_real_hint,
        actual=detail,
    )


def run_specialisation_test() -> tuple[Result, Result, Result]:
    """
    Calls the API twice — once in standard mode, once in coaching mode — then
    checks that the outputs are measurably different.

    Coaching mode MUST end with 'Your optimal next guess is [N].'
    Standard mode must NOT contain that phrase.

    Returns three Results: standard hint check, coaching hint check, difference check.
    """
    from ai_agent import get_ai_hint

    sample_history = [
        {"guess": 50, "outcome": "Too Low", "hot_cold": "🌡️ Warm"},
        {"guess": 75, "outcome": "Too High", "hot_cold": "♨️ Hot"},
        {"guess": 62, "outcome": "Too High", "hot_cold": "♨️ Hot"},
    ]
    kwargs = dict(history=sample_history, min_val=1, max_val=100, attempt_number=3, max_attempts=8)

    standard_hint, _ = get_ai_hint(**kwargs, coaching_mode=False)
    coached_hint,  _ = get_ai_hint(**kwargs, coaching_mode=True)

    error_prefixes = ("Could not", "Invalid API", "Network error", "Rate limit")

    standard_ok = Result(
        name="Standard mode produces conversational hint",
        description="Non-error string that does NOT contain 'optimal next guess is'",
        passed=(
            len(standard_hint) > 20
            and not any(standard_hint.startswith(p) for p in error_prefixes)
            and "optimal next guess is" not in standard_hint.lower()
        ),
        actual=f'"{standard_hint[:100]}…"',
    )

    coached_ok = Result(
        name="Coaching mode produces structured hint",
        description="Non-error string that DOES contain 'optimal next guess is [N]'",
        passed=(
            len(coached_hint) > 20
            and not any(coached_hint.startswith(p) for p in error_prefixes)
            and "optimal next guess is" in coached_hint.lower()
        ),
        actual=f'"{coached_hint[:100]}…"',
    )

    outputs_differ = Result(
        name="Standard and coaching outputs are measurably different",
        description="One contains 'optimal next guess is', the other does not",
        passed=standard_ok.passed and coached_ok.passed,
        actual="See individual hint checks above",
    )

    return standard_ok, coached_ok, outputs_differ


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    run_api = "--api" in sys.argv
    width = 60

    print()
    print("═" * width)
    print("  GLITCHY GUESSER — RELIABILITY EVALUATION")
    print("═" * width)

    all_passed = all_total = 0

    iv_results = run(INPUT_VALIDATION_CASES)
    p, t = print_section("INPUT VALIDATION  (parse_guess)", iv_results)
    all_passed += p; all_total += t

    gl_results = run(GAME_LOGIC_CASES)
    p, t = print_section("GAME LOGIC  (check_guess · update_score · difficulty range)", gl_results)
    all_passed += p; all_total += t

    at_results = run(AGENT_TOOL_CASES)
    p, t = print_section("AGENT TOOLS  (calculate_valid_range · evaluate_strategy · get_hint_intensity)", at_results)
    all_passed += p; all_total += t

    rag_results = run(RAG_RETRIEVAL_CASES)
    p, t = print_section("RAG RETRIEVAL  (build_query · retrieve · TF-IDF cosine similarity)", rag_results)
    all_passed += p; all_total += t

    # ── Optional API tests ───────────────────────────────────────────────────
    api_result = None
    spec_results = []

    if run_api:
        key = os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            print("\n  END-TO-END & SPECIALISATION TESTS")
            print(f"  {'─' * 56}")
            print("    ⚠️  Skipped — GOOGLE_API_KEY not set.")
            print("       Set the key in .env or your environment and re-run with --api.")
        else:
            print("\n  END-TO-END API TEST  (live Google AI API — standard mode)")
            print(f"  {'─' * 56}")
            print("    Calling Claude Haiku with a sample game state…")
            api_result = run_api_test()
            icon = "✅" if api_result.passed else "❌"
            print(f"    {icon}  {api_result.name}")
            print(f"         {api_result.description}")
            print(f"         → {api_result.actual}")

            print(f"\n  SPECIALISATION TEST  (standard vs coaching mode — {'+2 stretch'})")
            print(f"  {'─' * 56}")
            print("    Calling Claude Haiku twice — once per mode. Comparing outputs…")
            s_result, c_result, d_result = run_specialisation_test()
            spec_results = [s_result, c_result, d_result]
            for r in spec_results:
                icon = "✅" if r.passed else "❌"
                print(f"    {icon}  {r.name}")
                print(f"         {r.description}")
                print(f"         → {r.actual}")
    else:
        print("\n  END-TO-END & SPECIALISATION TESTS")
        print(f"  {'─' * 56}")
        print("    Skipped (run with --api to include live API tests).")

    # ── Summary ──────────────────────────────────────────────────────────────
    pct = int(100 * all_passed / all_total) if all_total else 0
    print()
    print("═" * width)
    print("  SUMMARY")
    print("═" * width)
    print(f"  Core tests:    {all_passed}/{all_total}  {bar(all_passed, all_total)}  {pct}%")

    if api_result is not None:
        api_icon = "PASS" if api_result.passed else "FAIL"
        print(f"  API round-trip:      {api_icon}")
    if spec_results:
        spec_pass = sum(r.passed for r in spec_results)
        spec_icon = "PASS" if spec_pass == len(spec_results) else f"{spec_pass}/{len(spec_results)}"
        print(f"  Specialisation:      {spec_icon}")

    print()

    # Observations
    failed = [r for r in iv_results + gl_results + at_results if not r.passed]
    if not failed:
        print("  Observations:")
        print("  • All input guardrails correctly reject invalid user input.")
        print("  • Game logic handles win, loss, and scoring edge cases accurately.")
        print("  • Agent tools narrow ranges, score strategies, and calibrate")
        print("    hint intensity correctly across all tested scenarios.")
        if api_result and api_result.passed:
            print("  • Full agentic loop returned a usable hint + 4-step trace from the live API.")
        elif api_result and not api_result.passed:
            print("  • ⚠️  API round-trip failed — check your API key and network.")
        if spec_results and all(r.passed for r in spec_results):
            print("  • Coaching mode measurably differs from standard: structured 3-sentence")
            print("    format with explicit optimal guess vs conversational hint without one.")
    else:
        print("  Failures:")
        for r in failed:
            print(f"  • {r.name}: {r.description}")

    print()
    print("  Limitations not covered by this script:")
    print("  • The agentic loop synthesis step (requires a live API call).")
    print("  • Hint quality and RAG impact on output (requires human evaluation).")
    print("  • UI rendering and Streamlit session state behaviour.")
    print("═" * width)
    print()

    sys.exit(0 if all_passed == all_total else 1)


if __name__ == "__main__":
    main()
