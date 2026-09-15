"""
Sovereignty Assessment Questionnaire
-------------------------------------
A Streamlit app that walks a user through the SEAL sovereignty framework
(objectives -> criteria -> weighted-score answers) and computes:

  - SOV score (0-100): weighted percentage across all objectives
  - SEAL score (0-4): weakest-link minimum seal level across all
    answered criteria

Run with:  python -m streamlit run "C:/Users/TomSchonkeren/Documents/local/app_OG4.py"

Theme: pinned to a light theme via .streamlit/config.toml (keep that
folder alongside this file).
"""

import base64
import json
import time
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

DATA_PATH = Path(__file__).parent / "framework.json"
LOGO_DARK_PATH = Path(__file__).parent / "assets" / "valcon_logo.png"
LOGO_LIGHT_PATH = Path(__file__).parent / "assets" / "valcon_logo_light.png"
NA_LABEL = "Not applicable"
UNANSWERED_LABEL = "-- Select an answer --"

st.set_page_config(page_title="Sovereignty Assessment", layout="wide")


# --------------------------------------------------------------------------
# Logo helper
# --------------------------------------------------------------------------
# The app is pinned to a light theme (see .streamlit/config.toml), so the
# dark logo (valcon_logo.png) is used everywhere - it reads cleanly on
# both the white main background and the light-gray sidebar. The light
# variant (valcon_logo_light.png) is kept in assets/ unused for now, ready
# for if a dark theme is ever added back.
@st.cache_data
def load_image_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


LOGO_DARK_B64 = load_image_base64(LOGO_DARK_PATH)


def render_logo(height_px: int, opacity: float = 1.0, align: str = "left"):
    justify = {"left": "flex-start", "center": "center", "right": "flex-end"}[align]
    st.markdown(
        f"""
        <div style="display:flex; justify-content:{justify}; margin:0.25rem 0;">
            <img src="data:image/png;base64,{LOGO_DARK_B64}"
                 style="height:{height_px}px; opacity:{opacity};" />
        </div>
        """,
        unsafe_allow_html=True,
    )

# --------------------------------------------------------------------------
# Light visual polish (safe CSS only - no <script> here, that's handled
# separately below via components.html, since browsers ignore <script>
# tags injected through st.markdown/innerHTML).
# --------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 2.5rem;
        padding-bottom: 3rem;
        max-width: 880px;
    }
    h1, h2, h3 {
        color: #16324F;
    }
    div[data-testid="stMetricValue"] {
        color: #1B4965;
    }
    div[data-testid="stMetric"] {
        background-color: #F2F5F7;
        border-radius: 10px;
        padding: 0.75rem 1rem;
        border: 1px solid #E3E8EC;
    }
    .stButton > button {
        border-radius: 8px;
        font-weight: 500;
    }
    div[data-testid="stRadio"] label {
        font-weight: 400;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------
@st.cache_data
def load_framework():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


framework = load_framework()
objectives = framework["objectives"]


# --------------------------------------------------------------------------
# Answer state
# --------------------------------------------------------------------------
# We keep a single, independent dict (st.session_state.answers) as the
# source of truth for what's been answered, rather than reading each radio
# widget's own linked session_state entry, since that can lose track of
# values when a widget isn't rendered on a given run (e.g. a different
# page). The answers dict is a plain session_state entry, not tied to
# widget instantiation, so it survives page navigation.
if "answers" not in st.session_state:
    st.session_state.answers = {}  # crit_id -> selected option label (str)


def radio_key(criterion_id: str) -> str:
    return f"radio_{criterion_id}"


def on_answer_change(crit_id: str):
    st.session_state.answers[crit_id] = st.session_state[radio_key(crit_id)]


def get_answer(criterion: dict):
    """Return the selected answer dict for a criterion, 'NA', or None."""
    choice = st.session_state.answers.get(criterion["id"])
    if choice in (None, UNANSWERED_LABEL):
        return None
    if choice == NA_LABEL:
        return "NA"
    for a in criterion["answers"]:
        if a["label"] == choice:
            return a
    return None


def objective_progress(obj: dict):
    total = len(obj["criteria"])
    answered = sum(1 for c in obj["criteria"] if get_answer(c) is not None)
    return answered, total


def compute_scores():
    """Compute per-objective breakdown, overall SOV score, and SEAL score."""
    objective_results = []
    total_weighted_pct = 0.0
    total_weight_used = 0.0
    all_seals = []

    for obj in objectives:
        raw_score = 0.0
        achievable_max = 0.0
        answered_count = 0
        na_count = 0

        for crit in obj["criteria"]:
            ans = get_answer(crit)
            if ans is None:
                continue
            if ans == "NA":
                na_count += 1
                continue
            answered_count += 1
            raw_score += ans["score"]
            achievable_max += max(a["score"] for a in crit["answers"])
            all_seals.append(ans["seal"])

        pct = (raw_score / achievable_max * 100) if achievable_max > 0 else None

        objective_results.append(
            {
                "id": obj["id"],
                "name": obj["name"],
                "weight": obj["weight"],
                "raw_score": raw_score,
                "achievable_max": achievable_max,
                "pct": pct,
                "answered": answered_count,
                "na": na_count,
                "total": len(obj["criteria"]),
            }
        )

        if pct is not None:
            total_weighted_pct += pct * obj["weight"]
            total_weight_used += obj["weight"]

    sov_score = (total_weighted_pct / total_weight_used) if total_weight_used > 0 else None
    seal_score = min(all_seals) if all_seals else None

    return objective_results, sov_score, seal_score, total_weight_used


def total_progress():
    answered = 0
    total = 0
    for obj in objectives:
        a, t = objective_progress(obj)
        answered += a
        total += t
    return answered, total


# --------------------------------------------------------------------------
# Scroll-to-top helper (anchor-based)
# --------------------------------------------------------------------------
# Real root cause of the earlier flakiness: components.html() builds its
# iframe from a hash of the HTML/JS it's given. Since the old script was
# byte-for-byte identical on every call, the browser could reuse the very
# first iframe instead of re-running the script on later reruns - so it
# only reliably fired once, which explains why it wasn't just a "Next
# button" thing.
#
# Fix: (1) drop a real, invisible anchor element at the very top of the
# actual page content (not inside the iframe), and scroll to *that*
# element with scrollIntoView - this is the "scroll anchor" approach.
# (2) Embed a fresh nonce (current time) in the injected script every
# single call, so its content is never identical twice and the iframe is
# always forced to reload and actually execute.
def render_scroll_anchor(anchor_id: str):
    st.markdown(f'<div id="{anchor_id}"></div>', unsafe_allow_html=True)


def scroll_to_anchor(anchor_id: str):
    nonce = time.time_ns()
    components.html(
        f"""
        <!-- nonce: {nonce} -->
        <script>
        function scrollToAnchor() {{
            try {{
                var doc = window.parent.document;
                var el = doc.getElementById("{anchor_id}");
                if (el) {{
                    el.scrollIntoView({{behavior: "instant", block: "start"}});
                }} else {{
                    doc.documentElement.scrollTop = 0;
                    doc.body.scrollTop = 0;
                }}
            }} catch (e) {{}}
        }}
        scrollToAnchor();
        setTimeout(scrollToAnchor, 50);
        setTimeout(scrollToAnchor, 150);
        setTimeout(scrollToAnchor, 300);
        </script>
        """,
        height=0,
    )


def go_to_page(new_page):
    st.session_state.page = new_page
    st.session_state.scroll_top = True
    st.rerun()


# --------------------------------------------------------------------------
# Rendering: a single objective's questions
# --------------------------------------------------------------------------
def render_objective(obj: dict):
    st.header(f"{obj['id']}: {obj['name']}")
    st.caption(f"Objective weight: {obj['weight'] * 100:.0f}% of total SOV score")
    st.divider()

    for crit in obj["criteria"]:
        with st.container(border=True):
            st.subheader(crit["title"])
            if crit.get("description"):
                st.write(crit["description"])

            options = [UNANSWERED_LABEL] + [a["label"] for a in crit["answers"]]
            if crit.get("allow_na", False):
                options.append(NA_LABEL)

            current_value = st.session_state.answers.get(crit["id"], UNANSWERED_LABEL)
            try:
                default_index = options.index(current_value)
            except ValueError:
                default_index = 0

            st.radio(
                "Select your answer:",
                options,
                index=default_index,
                key=radio_key(crit["id"]),
                on_change=on_answer_change,
                args=(crit["id"],),
                label_visibility="collapsed",
            )
        st.write("")


# --------------------------------------------------------------------------
# Rendering: results page
# --------------------------------------------------------------------------
def render_results():
    st.header("Results")

    objective_results, sov_score, seal_score, weight_used = compute_scores()
    answered, total = total_progress()

    if answered == 0:
        st.info("No questions answered yet. Go through the objectives in the sidebar first.")
        return

    if weight_used < 0.999:
        st.warning(
            f"Only {weight_used * 100:.0f}% of the total objective weight has been "
            "answered so far (some objectives are entirely unanswered or N/A). "
            "The SOV score below is renormalized over what's been answered — "
            "answer more questions for a fully representative score."
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("SOV Score", f"{sov_score:.1f} / 100" if sov_score is not None else "N/A")
    with col2:
        st.metric("SEAL Score", f"{seal_score} / 4" if seal_score is not None else "N/A")
    with col3:
        st.metric("Questions answered", f"{answered} / {total}")

    st.caption(
        "SOV score: weighted percentage across all objectives. "
        "SEAL score: weakest-link minimum seal level across all answered criteria."
    )

    st.divider()
    st.subheader("Breakdown by objective")

    df = pd.DataFrame(objective_results)
    df_display = df.copy()
    df_display["pct"] = df_display["pct"].apply(lambda v: f"{v:.1f}%" if v is not None else "—")
    df_display["weight"] = df_display["weight"].apply(lambda v: f"{v * 100:.0f}%")
    df_display["answered / total"] = df_display["answered"].astype(str) + " / " + df_display["total"].astype(str)
    df_display = df_display[["id", "name", "weight", "pct", "answered / total", "na"]]
    df_display.columns = ["ID", "Objective", "Weight", "Score (%)", "Answered", "N/A"]
    st.dataframe(df_display, hide_index=True, use_container_width=True)

    chart_df = pd.DataFrame(
        {
            "Objective": [f"{r['id']}" for r in objective_results if r["pct"] is not None],
            "Score (%)": [r["pct"] for r in objective_results if r["pct"] is not None],
        }
    ).set_index("Objective")
    if not chart_df.empty:
        st.bar_chart(chart_df)

    st.divider()
    export = {
        "model_version": framework.get("model_version"),
        "sov_score": sov_score,
        "seal_score": seal_score,
        "objectives": objective_results,
        "answers": {
            crit["id"]: (get_answer(crit) if get_answer(crit) != "NA" else "N/A")
            for obj in objectives
            for crit in obj["criteria"]
            if get_answer(crit) is not None
        },
    }
    st.download_button(
        "⬇ Download results (JSON)",
        data=json.dumps(export, indent=2, default=str),
        file_name="sovereignty_assessment_results.json",
        mime="application/json",
    )


# --------------------------------------------------------------------------
# Main layout / navigation
# --------------------------------------------------------------------------
if "page" not in st.session_state:
    st.session_state.page = 0  # int index into objectives, or "results"
if "scroll_top" not in st.session_state:
    st.session_state.scroll_top = False

page_anchor_id = f"page-top-{st.session_state.page}"
render_scroll_anchor(page_anchor_id)

render_logo(height_px=30, opacity=1.0, align="left")
st.title("Sovereignty Assessment Questionnaire")
st.caption(f"Model version: {framework.get('model_version', '')}")

with st.sidebar:
    render_logo(height_px=22, opacity=1.0, align="left")
    st.divider()
    st.header("Navigation")
    for i, obj in enumerate(objectives):
        a, t = objective_progress(obj)
        done = "☑" if a == t else f"{a}/{t}"
        if st.button(f"{obj['id']} · {obj['name']}  ({done})", key=f"nav_{i}", use_container_width=True):
            go_to_page(i)

    st.divider()
    total_answered, total_questions = total_progress()
    st.progress(total_answered / total_questions if total_questions else 0)
    st.caption(f"{total_answered} / {total_questions} questions answered")

    if st.button("View Results", use_container_width=True, type="primary", key="sidebar_results"):
        go_to_page("results")

    if st.button("Reset all answers", use_container_width=True, key="sidebar_reset"):
        st.session_state.answers = {}
        for obj in objectives:
            for crit in obj["criteria"]:
                st.session_state.pop(radio_key(crit["id"]), None)
        go_to_page(0)

page = st.session_state.page

if page == "results":
    render_results()
else:
    render_objective(objectives[page])

    nav_col1, nav_col2, nav_col3 = st.columns([1, 1, 1])
    with nav_col1:
        if page > 0:
            # Page-specific key: makes this a "new" element every time
            # the page changes, instead of Streamlit reusing the same
            # button node across reruns.
            if st.button("⬅ Previous objective", key=f"prev_btn_{page}"):
                go_to_page(page - 1)
    with nav_col3:
        if page < len(objectives) - 1:
            if st.button("Next objective ➡", key=f"next_btn_{page}"):
                go_to_page(page + 1)
        else:
            if st.button("View Results", type="primary", key=f"results_btn_{page}"):
                go_to_page("results")

# Scroll-to-anchor runs AFTER the full page (including nav buttons) has
# been rendered, so it acts on the final DOM rather than racing the
# layout, and targets the anchor placed at the very top of this page.
if st.session_state.scroll_top:
    scroll_to_anchor(page_anchor_id)
    st.session_state.scroll_top = False

# Footer logo - subtle, faded, centered, shown on every page.
st.markdown(
    "<hr style='margin-top:3rem; margin-bottom:1rem; border: none; "
    "border-top: 1px solid #E3E8EC;'>",
    unsafe_allow_html=True,
)
render_logo(height_px=20, opacity=0.45, align="center")
