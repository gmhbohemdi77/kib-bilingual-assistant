"""
KIB Bilingual Assistant — Streamlit web app.

Phase 5.2: Streamlit deployment to Azure Web Apps.
Phase 5.3: Entra ID single sign-on.
Phase 5.4: Role-based access (AI Trainer panel vs. employee chat).
Phase 6.3: AI Trainer manual update portal (calls core.update.run_update()).
Phase 6.4: New offers/promotions are surfaced in the trainer panel.

Run locally:
    streamlit run streamlit_app/app.py

Deploy to Azure Web Apps:
    See docs/DEPLOY_STREAMLIT.md
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

# Make the parent directory importable so `from core import ...` works whether
# we run `streamlit run streamlit_app/app.py` from the project root or Azure
# does `streamlit run app.py` from inside this folder.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402

from core.auth import (  # noqa: E402
    AuthenticatedUser,
    ROLE_AI_TRAINER,
    build_login_url,
    dev_user,
    exchange_code,
)
from core.rag import KIBAssistant  # noqa: E402
from core.update import run_update  # noqa: E402


# ----------------------------------------------------------------------------
# Page setup
# ----------------------------------------------------------------------------

st.set_page_config(
    page_title="KIB Assistant",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ----------------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------------


def _is_dev_mode() -> bool:
    return os.getenv("KIB_DEV_AUTH") == "1"


def _login_screen() -> None:
    st.title("🏦 KIB Assistant")
    st.write(
        "Sign in with your KIB Microsoft account to access the bilingual "
        "(English / العربية) banking assistant."
    )

    if _is_dev_mode():
        st.warning("Dev auth mode is enabled (KIB_DEV_AUTH=1). Skipping Entra ID.")
        col1, col2 = st.columns(2)
        if col1.button("Sign in as Employee", use_container_width=True):
            st.session_state["user"] = dev_user(trainer=False)
            st.rerun()
        if col2.button("Sign in as AI Trainer", use_container_width=True):
            st.session_state["user"] = dev_user(trainer=True)
            st.rerun()
        return

    # Real Entra ID flow
    if "auth_state" not in st.session_state:
        st.session_state["auth_state"] = secrets.token_urlsafe(16)

    login_url = build_login_url(st.session_state["auth_state"])
    st.link_button("Sign in with Microsoft", login_url, use_container_width=True)
    st.caption("You'll be redirected to login.microsoftonline.com.")


def _consume_auth_callback() -> None:
    """If the URL has ?code=..., exchange it for a token and stash the user."""
    params = st.query_params
    code = params.get("code")
    state = params.get("state")
    if not code:
        return
    if state != st.session_state.get("auth_state"):
        st.error("Login state mismatch. Please try again.")
        st.query_params.clear()
        return
    user = exchange_code(code if isinstance(code, str) else code[0])
    if user is None:
        st.error("Sign-in failed. Please try again.")
        st.query_params.clear()
        return
    st.session_state["user"] = user
    st.query_params.clear()
    st.rerun()


# ----------------------------------------------------------------------------
# Cached resources
# ----------------------------------------------------------------------------


@st.cache_resource(show_spinner=False)
def _get_assistant() -> KIBAssistant:
    return KIBAssistant()


# ----------------------------------------------------------------------------
# Chat UI (visible to everyone after login)
# ----------------------------------------------------------------------------


def _render_chat(user: AuthenticatedUser) -> None:
    st.header("💬 Ask KIB")
    st.caption("Ask in English or العربية. Answers come from the official KIB website.")

    if "history" not in st.session_state:
        st.session_state["history"] = []

    for msg in st.session_state["history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sources"):
                with st.expander("Sources"):
                    for s in msg["sources"]:
                        st.markdown(f"- [{s['url']}]({s['url']}) — score `{s['score']:.3f}`")

    user_input = st.chat_input("Type your question...")
    if not user_input:
        return

    st.session_state["history"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = _get_assistant().ask(user_input)
        st.markdown(result.answer)
        sources_payload = [
            {"url": s.url, "score": s.score} for s in result.sources
        ]
        if sources_payload:
            with st.expander("Sources"):
                for s in sources_payload:
                    st.markdown(f"- [{s['url']}]({s['url']}) — score `{s['score']:.3f}`")

    st.session_state["history"].append(
        {"role": "assistant", "content": result.answer, "sources": sources_payload}
    )


# ----------------------------------------------------------------------------
# AI Trainer admin panel (Phase 5.4 + 6.3 + 6.4)
# ----------------------------------------------------------------------------


def _render_trainer_panel(user: AuthenticatedUser) -> None:
    st.header("🛠️ AI Trainer Panel")
    st.caption("Only visible to users in the AI Trainer Entra ID group.")

    st.subheader("Manual data refresh")
    st.write(
        "Trigger a scrape + change-detection update right now. Use this when "
        "you know KIB's website has been updated and you don't want to wait for "
        "the daily Azure Function."
    )

    if st.button("🔄 Run update now", type="primary"):
        with st.spinner("Scraping, translating, embedding... this can take a few minutes."):
            report = run_update(triggered_by=f"trainer:{user.email}")
        if report.error:
            st.error(report.summary())
        else:
            st.success(report.summary())
        st.session_state["last_update_report"] = report

    last = st.session_state.get("last_update_report")
    if last is not None:
        st.divider()
        st.subheader("Last update report")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Pages scraped", last.pages_scraped)
        col2.metric("New chunks", last.chunks_added)
        col3.metric("Marked stale", last.chunks_marked_stale)
        col4.metric("New offers", last.new_offer_chunks)
        st.caption(f"Started: {last.started_at}  |  Finished: {last.finished_at}")

        if last.new_offer_samples:
            st.subheader("🎁 New offers / promotions detected")
            for sample in last.new_offer_samples:
                st.markdown(f"- {sample}")


# ----------------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------------


def _render_sidebar(user: AuthenticatedUser) -> None:
    st.sidebar.title("KIB Assistant")
    st.sidebar.write(f"**{user.display_name}**")
    st.sidebar.caption(user.email)
    role_label = "🛠️ AI Trainer" if user.is_trainer else "👤 Employee"
    st.sidebar.markdown(f"**Role:** {role_label}")
    st.sidebar.divider()
    if st.sidebar.button("Sign out", use_container_width=True):
        for k in ("user", "history", "last_update_report"):
            st.session_state.pop(k, None)
        st.rerun()


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------


def main() -> None:
    if "user" not in st.session_state:
        _consume_auth_callback()
    if "user" not in st.session_state:
        _login_screen()
        return

    user: AuthenticatedUser = st.session_state["user"]
    _render_sidebar(user)

    if user.is_trainer:
        # Trainers see chat + admin panel side by side
        chat_tab, trainer_tab = st.tabs(["💬 Chat", "🛠️ AI Trainer Panel"])
        with chat_tab:
            _render_chat(user)
        with trainer_tab:
            _render_trainer_panel(user)
    else:
        _render_chat(user)


if __name__ == "__main__":
    main()
