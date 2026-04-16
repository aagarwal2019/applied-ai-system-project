"""
tests/test_game_logic.py

Unit tests for game logic (logic_utils) and the agentic hint tool functions
(ai_agent).  All tests are pure-Python — no Streamlit, no API calls.
"""

from logic_utils import check_guess, parse_guess, update_score, get_range_for_difficulty
from ai_agent import calculate_valid_range, evaluate_strategy, get_hint_intensity


# ---------------------------------------------------------------------------
# logic_utils — check_guess
# ---------------------------------------------------------------------------

def test_winning_guess():
    assert check_guess(50, 50) == "Win"

def test_guess_too_high():
    assert check_guess(60, 50) == "Too High"

def test_guess_too_low():
    assert check_guess(40, 50) == "Too Low"


# ---------------------------------------------------------------------------
# logic_utils — parse_guess
# ---------------------------------------------------------------------------

def test_parse_guess_valid_int():
    ok, val, _ = parse_guess("42")
    assert ok is True
    assert val == 42

def test_parse_guess_valid_float():
    ok, val, _ = parse_guess("7.9")
    assert ok is True
    assert val == 7

def test_parse_guess_empty():
    ok, val, _ = parse_guess("")
    assert ok is False
    assert val is None

def test_parse_guess_non_numeric():
    ok, val, _ = parse_guess("abc")
    assert ok is False
    assert val is None


# ---------------------------------------------------------------------------
# logic_utils — update_score
# ---------------------------------------------------------------------------

def test_update_score_win():
    score = update_score(0, "Win", 1)
    assert score > 0

def test_update_score_loss():
    score = update_score(50, "Too High", 3)
    assert score == 45  # -5 for wrong guess

def test_update_score_minimum_win_points():
    # Very late win should still award at least 10 points
    score = update_score(0, "Win", 100)
    assert score >= 10


# ---------------------------------------------------------------------------
# logic_utils — get_range_for_difficulty
# ---------------------------------------------------------------------------

def test_range_easy():
    assert get_range_for_difficulty("Easy") == (1, 20)

def test_range_normal():
    assert get_range_for_difficulty("Normal") == (1, 100)

def test_range_hard():
    assert get_range_for_difficulty("Hard") == (1, 200)

def test_range_unknown_defaults_to_normal():
    assert get_range_for_difficulty("Extreme") == (1, 100)


# ---------------------------------------------------------------------------
# ai_agent — calculate_valid_range
# ---------------------------------------------------------------------------

def test_valid_range_no_history():
    result = calculate_valid_range([], 1, 100)
    assert result["low"] == 1
    assert result["high"] == 100
    assert result["remaining_count"] == 100
    assert result["optimal_next_guess"] == 50

def test_valid_range_narrows_high():
    history = [{"guess": 80, "outcome": "Too High"}]
    result = calculate_valid_range(history, 1, 100)
    assert result["high"] == 79
    assert result["low"] == 1

def test_valid_range_narrows_low():
    history = [{"guess": 30, "outcome": "Too Low"}]
    result = calculate_valid_range(history, 1, 100)
    assert result["low"] == 31
    assert result["high"] == 100

def test_valid_range_multiple_guesses():
    history = [
        {"guess": 50, "outcome": "Too Low"},
        {"guess": 75, "outcome": "Too High"},
    ]
    result = calculate_valid_range(history, 1, 100)
    assert result["low"] == 51
    assert result["high"] == 74
    assert result["remaining_count"] == 24

def test_valid_range_win_entry_ignored():
    history = [
        {"guess": 50, "outcome": "Too Low"},
        {"guess": 75, "outcome": "Win"},
    ]
    result = calculate_valid_range(history, 1, 100)
    # Only the "Too Low" at 50 should shift the lower bound
    assert result["low"] == 51
    assert result["high"] == 100

def test_valid_range_remaining_cannot_go_negative():
    history = [
        {"guess": 40, "outcome": "Too High"},
        {"guess": 60, "outcome": "Too Low"},  # Contradictory — impossible range
    ]
    result = calculate_valid_range(history, 1, 100)
    assert result["remaining_count"] == 0


# ---------------------------------------------------------------------------
# ai_agent — evaluate_strategy
# ---------------------------------------------------------------------------

def test_evaluate_strategy_just_started():
    history = [{"guess": 50, "outcome": "Too Low"}]
    result = evaluate_strategy(history, 1, 100)
    assert result["strategy"] == "just_started"

def test_evaluate_strategy_binary_search():
    # Player always picks near the midpoint — should score highly
    history = [
        {"guess": 50, "outcome": "Too Low"},   # optimal ~50
        {"guess": 75, "outcome": "Too High"},  # optimal 75
        {"guess": 62, "outcome": "Too High"},  # optimal 62
    ]
    result = evaluate_strategy(history, 1, 100)
    assert result["strategy"] == "binary_search"
    assert result["efficiency_score"] >= 0.7

def test_evaluate_strategy_random():
    # Player always picks poorly — far from the midpoint
    history = [
        {"guess": 2,  "outcome": "Too Low"},   # optimal ~50, far off
        {"guess": 3,  "outcome": "Too Low"},   # optimal ~76, far off
        {"guess": 4,  "outcome": "Too Low"},   # still far off
    ]
    result = evaluate_strategy(history, 1, 100)
    assert result["strategy"] == "random"
    assert result["efficiency_score"] < 0.4

def test_evaluate_strategy_returns_advice():
    history = [
        {"guess": 50, "outcome": "Too Low"},
        {"guess": 75, "outcome": "Too High"},
    ]
    result = evaluate_strategy(history, 1, 100)
    assert "advice" in result
    assert isinstance(result["advice"], str)


# ---------------------------------------------------------------------------
# ai_agent — get_hint_intensity
# ---------------------------------------------------------------------------

def test_hint_intensity_gentle():
    result = get_hint_intensity(1, 8)  # 12.5 % used
    assert result["intensity"] == "gentle"

def test_hint_intensity_moderate():
    result = get_hint_intensity(4, 8)  # 50 % used
    assert result["intensity"] == "moderate"

def test_hint_intensity_strong():
    result = get_hint_intensity(7, 8)  # 87.5 % used
    assert result["intensity"] == "strong"

def test_hint_intensity_attempts_remaining():
    result = get_hint_intensity(3, 8)
    assert result["attempts_remaining"] == 5

def test_hint_intensity_zero_max_attempts():
    result = get_hint_intensity(0, 0)
    assert result["intensity"] == "moderate"  # Safe default
