# 💭 Reflection: Game Glitch Investigator

Answer each question in 3 to 5 sentences. Be specific and honest about what actually happened while you worked. This is about your process, not trying to sound perfect.

## 1. What was broken when you started?

**What did the game look like the first time you ran it?** The UI loaded, but the secret number, replay button and hints changed after every interaction, making gameplay inconsistent and frustrating.

**List at least two concrete bugs you noticed at the start.** First, the secret number regenerated on every rerun. Second, the hint logic could return wrong directional text for guesses when the game should have ended.

---

## 2. How did you use AI as a teammate?

**Which AI tools did you use on this project?** I used GitHub Copilot and Claude Code suggestions from within VS Code.

**One correct AI suggestion and verification.** AI correctly suggested using `st.session_state` so the secret number initializes only once; I verified by running the app and seeing stable secret number across guesses.

**One incorrect AI suggestion and verification.** AI suggested returning the secret from a function instead of session state, which did not solve reruns; I verified by testing and the number still changed after interactions.

---

## 3. Debugging and testing your fixes

**How did you decide whether a bug was really fixed?** I reproduced the failure and then reran the same steps to confirm the behavior was stable and consistent.

**Describe one test you ran and what it showed.** I ran `pytest` on `tests/test_game_logic.py`, and the expected guess/hint cases passed, showing the logic functions were behaving correctly.

**Did AI help design/understand tests?** Yes, AI helped suggest boundary case tests (too low, too high, correct), which I used to validate fixes.

---

## 4. What did you learn about Streamlit and state?

**Why did the secret number keep changing originally?** Because Streamlit re-runs the script on every interaction, and the code recreated the secret number each rerun.

**How to explain reruns and session state to a friend?** Reruns mean the entire app code runs again whenever you click a widget. Session state is a place to store values across these reruns so the app remembers the secret number.

**What change gave a stable secret number?** I initialized `st.session_state['secret_number']` once and reused it for guesses.

---

## 5. Looking ahead: your developer habits

**What strategy do you want to reuse?** I want to reuse the habit of writing focused tests early and using incremental Git commits.

**What would you do differently next time with AI?** I would request precise code snippets based on current functions and verify every suggestion with tests before trusting it.

**How did this project change your view on AI-generated code?** It reinforced that AI is a helpful collaborator, but I still need to verify and test AI suggestions carefully rather than assuming they’re correct.

---

## 6. Ethics and Critical Reflection (Applied AI Extension)

**Limitations and biases in the system:**
The strategy evaluator assumes binary search is always optimal, which disadvantages players
who reach the answer efficiently through other patterns. On Easy difficulty (range 1–20),
many strategies work equally well but score poorly against the midpoint benchmark. The
system also has no cross-game memory — it cannot recognise a player’s habitual tendencies
or improve its advice over time.

**Misuse risks and mitigations:**
The hint assistant has a narrow scope and cannot produce harmful content, but has two
operational risks. First, repeated API calls in a public deployment could generate
significant cost without rate limiting — mitigated by capping hints per game and adding
per-IP request limits. Second, the current setup allows the API key to be entered in the
browser sidebar, which exposes it in shared environments — in production the key should
only live server-side.

**What surprised me during reliability testing:**
The agent consistently called all three tools in the specified order without any code
enforcing that sequence — the system prompt alone was sufficient. I expected occasional
deviations and planned to add ordering enforcement, but it was never needed. This
suggests that precise system prompts can substitute for procedural control flow in
constrained agentic tasks.

**Helpful AI suggestion:**
GitHub Copilot correctly suggested `st.session_state` to fix the secret number resetting
on every Streamlit rerun. It identified the root cause (Streamlit reruns the full script
on every interaction), pointed to the right primitive, and I verified the fix held across
ten consecutive guesses.

**Flawed AI suggestion:**
An AI assistant suggested passing the guess history to Claude as a formatted prose string
(e.g., "Guess 50: Too Low, Guess 75: Too High"). This caused the tool input schema to
reject the string type and led to direction-label misreads on longer histories. Switching
to a typed JSON array with a structured input schema fixed both issues. The lesson:
tool-use APIs need structured data, not prose, even when the model can parse prose.
