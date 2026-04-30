import logging
import os
import random

import streamlit as st
from dotenv import load_dotenv

from ai_agent import get_ai_hint
from logic_utils import check_guess, get_range_for_difficulty, parse_guess, update_score

# Load GOOGLE_API_KEY from a local .env file, overriding any existing shell value
load_dotenv(override=True)

# ---------------------------------------------------------------------------
# App-level logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hot/cold proximity label
# ---------------------------------------------------------------------------

def get_hot_cold(guess, secret, low, high):
    """Return a hot/cold emoji label based on how close the guess is to the secret."""
    distance = abs(guess - secret)
    span = high - low
    ratio = distance / span if span > 0 else 1
    if ratio <= 0.05:
        return "🔥 Burning Hot!"
    if ratio <= 0.15:
        return "♨️ Hot"
    if ratio <= 0.30:
        return "🌡️ Warm"
    if ratio <= 0.50:
        return "🧊 Cold"
    return "❄️ Freezing Cold!"


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Glitchy Guesser", page_icon="🎮")

st.title("🎮 Glitchy Guesser")
st.caption("An guessing game that is powered by AI.")

# ---------------------------------------------------------------------------
# Sidebar — settings
# ---------------------------------------------------------------------------

st.sidebar.header("Settings")

difficulty = st.sidebar.selectbox(
    "Difficulty",
    ["Easy", "Normal", "Hard"],
    index=1,
)

show_hint = st.sidebar.checkbox("Show hot/cold hints", value=True)

attempt_limit_map = {"Easy": 6, "Normal": 8, "Hard": 5}
attempt_limit = attempt_limit_map[difficulty]

low, high = get_range_for_difficulty(difficulty)

st.sidebar.caption(f"Range: {low} to {high}")
st.sidebar.caption(f"Attempts allowed: {attempt_limit}")

# AI hint API key — prefer env var, allow sidebar override
with st.sidebar.expander("AI Hint Settings"):
    sidebar_api_key = st.text_input(
        "Google AI API Key",
        type="password",
        placeholder="Uses GOOGLE_API_KEY env var if blank",
        help="Required for AI Hints. Leave blank if GOOGLE_API_KEY is set in your environment or .env file.",
    )
    coaching_mode = st.toggle(
        "Coaching Mode",
        value=False,
        help=(
            "Standard mode gives conversational hints and never reveals a specific guess. "
            "Coaching mode uses a few-shot specialised prompt that always ends with "
            "the exact optimal next guess."
        ),
    )

# Resolve the key: sidebar input wins; fall back to environment
api_key = sidebar_api_key.strip() or os.environ.get("GOOGLE_API_KEY", "")

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "secret" not in st.session_state:
    st.session_state.secret = random.randint(low, high)
if "attempts" not in st.session_state:
    st.session_state.attempts = 0
if "score" not in st.session_state:
    st.session_state.score = 0
if "status" not in st.session_state:
    st.session_state.status = "playing"
if "history" not in st.session_state:
    st.session_state.history = []
if "ai_hint_text" not in st.session_state:
    st.session_state.ai_hint_text = None
if "ai_hint_trace" not in st.session_state:
    st.session_state.ai_hint_trace = []
if "ai_hint_mode" not in st.session_state:
    st.session_state.ai_hint_mode = "standard"

# ---------------------------------------------------------------------------
# Metrics bar
# ---------------------------------------------------------------------------

attempts_left = attempt_limit - st.session_state.attempts
m1, m2, m3 = st.columns(3)
m1.metric("Score", st.session_state.score)
m2.metric("Attempts Left", attempts_left)
m3.metric("Difficulty", difficulty)

st.divider()

# ---------------------------------------------------------------------------
# Developer debug panel
# ---------------------------------------------------------------------------

with st.expander("Developer Debug Info"):
    st.write("Secret:", st.session_state.secret)
    st.write("Attempts:", st.session_state.attempts)
    st.write("Score:", st.session_state.score)
    st.write("Difficulty:", difficulty)
    st.write("History:", st.session_state.history)

# ---------------------------------------------------------------------------
# Guess input
# ---------------------------------------------------------------------------

st.subheader("Make a guess")
st.info(f"Guess a number between **{low}** and **{high}**.")

raw_guess = st.text_input("Enter your guess:", key=f"guess_input_{difficulty}")

col1, col2, col3 = st.columns(3)
with col1:
    submit = st.button("Submit Guess 🚀")
with col2:
    new_game = st.button("New Game 🔁")
with col3:
    ai_hint_disabled = (
        st.session_state.status != "playing"
        or not st.session_state.history
        or not api_key
    )
    ai_hint_btn = st.button(
        "AI Hint 🤖",
        disabled=ai_hint_disabled,
        help=(
            "Make at least one guess first, then click for a strategic AI hint."
            if api_key
            else "Add a Google AI API key in the sidebar to enable AI hints."
        ),
    )

# ---------------------------------------------------------------------------
# New game
# ---------------------------------------------------------------------------

if new_game:
    st.session_state.attempts = 0
    st.session_state.secret = random.randint(low, high)
    st.session_state.score = 0
    st.session_state.status = "playing"
    st.session_state.history = []
    st.session_state.ai_hint_text = None
    st.session_state.ai_hint_trace = []
    st.session_state.ai_hint_mode = "standard"
    logger.info("New game started | difficulty=%s | range=[%d,%d]", difficulty, low, high)
    st.success("New game started.")
    st.rerun()

# ---------------------------------------------------------------------------
# AI hint
# ---------------------------------------------------------------------------

if ai_hint_btn:
    mode_label = "coaching" if coaching_mode else "standard"
    logger.info("AI hint requested by player | mode=%s", mode_label)
    with st.spinner("Thinking…"):
        hint, trace = get_ai_hint(
            history=st.session_state.history,
            min_val=low,
            max_val=high,
            attempt_number=st.session_state.attempts,
            max_attempts=attempt_limit,
            api_key=api_key or None,
            coaching_mode=coaching_mode,
        )
    st.session_state.ai_hint_text = hint
    st.session_state.ai_hint_trace = trace
    st.session_state.ai_hint_mode = mode_label

if st.session_state.ai_hint_text:
    mode = st.session_state.ai_hint_mode
    label = "🎓 **Coaching Hint:**" if mode == "coaching" else "🤖 **AI Hint:**"
    st.info(f"{label} {st.session_state.ai_hint_text}")

    # ── Observable intermediate steps (Agentic Workflow stretch feature) ─────
    if st.session_state.ai_hint_trace:
        _TOOL_LABELS = {
            "rag_retrieval":         ("📚", "RAG Retrieval"),
            "calculate_valid_range": ("📐", "Valid Range"),
            "evaluate_strategy":     ("📊", "Strategy Score"),
            "get_hint_intensity":    ("🎚️",  "Hint Intensity"),
        }
        _KEY_FIELDS = {
            "rag_retrieval":         ["query", "docs_retrieved", "top_topic", "top_score"],
            "calculate_valid_range": ["low", "high", "remaining_count", "optimal_next_guess"],
            "evaluate_strategy":     ["strategy", "efficiency_score", "advice"],
            "get_hint_intensity":    ["intensity", "attempts_remaining"],
        }
        with st.expander(
            f"🔍 Agent reasoning — {len(st.session_state.ai_hint_trace)} steps",
            expanded=False,
        ):
            for step in st.session_state.ai_hint_trace:
                tool = step["function"]
                result = step["result"]
                icon, title = _TOOL_LABELS.get(tool, ("🔧", tool))
                st.markdown(f"**{icon} {title}** (`{tool}`)")
                fields = _KEY_FIELDS.get(tool, list(result.keys()))
                for key in fields:
                    if key in result:
                        st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;`{key}` → **{result[key]}**")

# ---------------------------------------------------------------------------
# Guard: stop rendering if game is already over
# ---------------------------------------------------------------------------

if st.session_state.status != "playing":
    if st.session_state.status == "won":
        st.success("You already won. Start a new game to play again.")
    else:
        st.error("Game over. Start a new game to try again.")
    st.stop()

# ---------------------------------------------------------------------------
# Guess submission
# ---------------------------------------------------------------------------

if submit:
    st.session_state.attempts += 1
    st.session_state.ai_hint_text = None   # Clear stale hint after each guess
    st.session_state.ai_hint_trace = []

    ok, guess_int, err = parse_guess(raw_guess)

    if not ok:
        st.session_state.attempts -= 1  # Don't charge an attempt for invalid input
        st.error(f"⚠️ {err}")
        logger.warning("Invalid guess input: %r — %s", raw_guess, err)
    else:
        outcome = check_guess(guess_int, st.session_state.secret)
        hot_cold = get_hot_cold(guess_int, st.session_state.secret, low, high) if outcome != "Win" else ""

        st.session_state.history.append({
            "guess": guess_int,
            "outcome": outcome,
            "hot_cold": hot_cold,
        })

        logger.info(
            "Guess=%d | outcome=%s | attempts=%d/%d | score=%d",
            guess_int, outcome, st.session_state.attempts, attempt_limit, st.session_state.score,
        )

        if show_hint:
            if outcome == "Win":
                st.success("🎉 Correct!")
            elif outcome == "Too High":
                st.error(f"📉 Too High! Go LOWER!   {hot_cold}")
            else:
                st.warning(f"📈 Too Low! Go HIGHER!   {hot_cold}")

        st.session_state.score = update_score(
            current_score=st.session_state.score,
            outcome=outcome,
            attempt_number=st.session_state.attempts,
        )

        if outcome == "Win":
            st.balloons()
            st.session_state.status = "won"
            logger.info("Player WON in %d attempts | score=%d", st.session_state.attempts, st.session_state.score)
            st.success(
                f"🏆 You won in {st.session_state.attempts} attempt(s)! "
                f"The secret was **{st.session_state.secret}**. "
                f"Final score: **{st.session_state.score}**"
            )
        elif st.session_state.attempts >= attempt_limit:
            st.session_state.status = "lost"
            logger.info("Player LOST | secret=%d | score=%d", st.session_state.secret, st.session_state.score)
            st.error(
                f"💀 Out of attempts! "
                f"The secret was **{st.session_state.secret}**. "
                f"Score: **{st.session_state.score}**"
            )

# ---------------------------------------------------------------------------
# Guess history table
# ---------------------------------------------------------------------------

valid_history = [h for h in st.session_state.history if isinstance(h, dict)]
if valid_history:
    st.divider()
    st.subheader("📋 Guess History")

    outcome_icon = {"Win": "✅", "Too High": "🔴", "Too Low": "🟡"}
    rows = [
        {
            "#": i,
            "Guess": entry["guess"],
            "Result": f"{outcome_icon.get(entry['outcome'], '')} {entry['outcome']}",
            "Temperature": entry["hot_cold"],
        }
        for i, entry in enumerate(valid_history, start=1)
    ]
    st.table(rows)

st.divider()
st.caption("Powered by Google Gemini")
