import random
import streamlit as st
from logic_utils import get_range_for_difficulty, parse_guess, check_guess, update_score


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


st.set_page_config(page_title="Glitchy Guesser", page_icon="🎮")

st.title("🎮 Game Glitch Investigator")
st.caption("An AI-generated guessing game. Something is off.")

st.sidebar.header("Settings")

difficulty = st.sidebar.selectbox(
    "Difficulty",
    ["Easy", "Normal", "Hard"],
    index=1,
)

attempt_limit_map = {
    "Easy": 6,
    "Normal": 8,
    "Hard": 5,
}
attempt_limit = attempt_limit_map[difficulty]

low, high = get_range_for_difficulty(difficulty)

st.sidebar.caption(f"Range: {low} to {high}")
st.sidebar.caption(f"Attempts allowed: {attempt_limit}")

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

# ── Status bar ──────────────────────────────────────────────────────────────
attempts_left = attempt_limit - st.session_state.attempts
m1, m2, m3 = st.columns(3)
m1.metric("Score", st.session_state.score)
m2.metric("Attempts Left", attempts_left)
m3.metric("Difficulty", difficulty)

st.divider()

st.subheader("Make a guess")
st.info(f"Guess a number between **{low}** and **{high}**.")

with st.expander("Developer Debug Info"):
    st.write("Secret:", st.session_state.secret)
    st.write("Attempts:", st.session_state.attempts)
    st.write("Score:", st.session_state.score)
    st.write("Difficulty:", difficulty)
    st.write("History:", st.session_state.history)

raw_guess = st.text_input(
    "Enter your guess:",
    key=f"guess_input_{difficulty}"
)

col1, col2, col3 = st.columns(3)
with col1:
    submit = st.button("Submit Guess 🚀")
with col2:
    new_game = st.button("New Game 🔁")
with col3:
    show_hint = st.checkbox("Show hint", value=True)

if new_game:
    st.session_state.attempts = 0
    st.session_state.secret = random.randint(low, high)
    st.session_state.score = 0
    st.session_state.status = "playing"
    st.session_state.history = []
    st.success("New game started.")
    st.rerun()

if st.session_state.status != "playing":
    if st.session_state.status == "won":
        st.success("You already won. Start a new game to play again.")
    else:
        st.error("Game over. Start a new game to try again.")
    st.stop()

if submit:
    st.session_state.attempts += 1

    ok, guess_int, err = parse_guess(raw_guess)

    if not ok:
        st.error(f"⚠️ {err}")
    else:
        outcome = check_guess(guess_int, st.session_state.secret)
        hot_cold = get_hot_cold(guess_int, st.session_state.secret, low, high) if outcome != "Win" else ""

        # Store rich history entry
        st.session_state.history.append({
            "guess": guess_int,
            "outcome": outcome,
            "hot_cold": hot_cold,
        })

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
            st.success(
                f"🏆 You won in {st.session_state.attempts} attempt(s)! "
                f"The secret was **{st.session_state.secret}**. "
                f"Final score: **{st.session_state.score}**"
            )
        elif st.session_state.attempts >= attempt_limit:
            st.session_state.status = "lost"
            st.error(
                f"💀 Out of attempts! "
                f"The secret was **{st.session_state.secret}**. "
                f"Score: **{st.session_state.score}**"
            )

# ── Session summary table ────────────────────────────────────────────────────
valid_history = [h for h in st.session_state.history if isinstance(h, dict)]
if valid_history:
    st.divider()
    st.subheader("📋 Guess History")

    outcome_icon = {"Win": "✅", "Too High": "🔴", "Too Low": "🟡"}
    rows = []
    for i, entry in enumerate(valid_history, start=1):
        rows.append({
            "#": i,
            "Guess": entry["guess"],
            "Result": f"{outcome_icon.get(entry['outcome'], '')} {entry['outcome']}",
            "Temperature": entry["hot_cold"],
        })

    st.table(rows)

st.divider()
st.caption("Built by an AI that claims this code is production-ready.")
