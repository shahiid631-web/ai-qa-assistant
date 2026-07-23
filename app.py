import streamlit as st
import sqlite3
from datetime import datetime
from google import genai
from google.genai import types


def sanitize_text(text: str) -> str:
    """Replace characters that break the API's request encoding with safe ASCII equivalents."""
    if not text:
        return text
    replacements = {
        "\u2018": "'", "\u2019": "'",   # curly single quotes
        "\u201c": '"', "\u201d": '"',   # curly double quotes
        "\u2013": "-", "\u2014": "-",   # en dash, em dash
        "\u2026": "...",                # ellipsis
        "\u2022": "-",                  # bullet
        "\u00a0": " ",                  # non-breaking space
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    # Strip anything else outside the basic multilingual plane (e.g. emoji, surrogate pairs)
    text = "".join(ch for ch in text if ord(ch) < 0x10000 or ch in "\n\t")
    return text

# ---------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------
DB_PATH = "chats.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (chat_id) REFERENCES chats (id)
        )
    """)
    conn.commit()
    return conn

conn = get_conn()

def create_chat(title="New Chat"):
    now = datetime.now().isoformat()
    cur = conn.execute("INSERT INTO chats (title, created_at) VALUES (?, ?)", (title, now))
    conn.commit()
    return cur.lastrowid

def get_all_chats():
    return conn.execute("SELECT id, title, created_at FROM chats ORDER BY created_at DESC").fetchall()

def get_messages(chat_id):
    return conn.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id ASC", (chat_id,)
    ).fetchall()

def add_message(chat_id, role, content):
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (chat_id, role, content, now),
    )
    conn.commit()

def update_chat_title(chat_id, title):
    conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
    conn.commit()

def delete_chat(chat_id):
    conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
    conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    conn.commit()

# ---------------------------------------------------------------
# Page config
# ---------------------------------------------------------------
st.set_page_config(page_title="AI QA Assistant", page_icon="⚙️", layout="wide")
st.title("🤖 Senior QA AI Assistant")
st.markdown(
    "Paste your project requirements or user stories below. This AI will generate comprehensive "
    "**Functional, Non-Functional, Edge-Case, and Accessibility** test cases instantly."
)

st.markdown("""
<style>
section[data-testid="stSidebar"] button {
    text-align: left;
    justify-content: flex-start;
    border: none;
    background: transparent;
    padding: 6px 10px;
}
section[data-testid="stSidebar"] button:hover {
    background: rgba(255, 255, 255, 0.08);
}
section[data-testid="stSidebar"] div[data-testid="column"]:nth-child(2) button {
    justify-content: center;
    padding: 6px;
}
</style>
""", unsafe_allow_html=True)

QA_SYSTEM_PROMPT = """
You are an expert Senior QA Automation and Manual Test Engineer. Your task is to analyze the user's software requirements or user stories and generate a highly detailed, professional test suite.
For any requirement provided, output your response in clean markdown with the following sections:
1. **Smoke Test Cases**: Crucial high-level validation paths.
2. **Functional Test Cases**: Positive and negative scenarios covering core logic.
3. **Boundary & Edge Cases**: Data limits, unexpected inputs, and error handling.
4. **Non-Functional Test Cases**: Security, Performance, and Cross-browser checks.
5. **Accessibility (WCAG) Test Cases**: Keyboard navigation, screen reader checks, and contrast rules.
Format each testcase with a short, punchy sentence detailing the action and expected result. Keep your tone technical, concise, and professional.
"""

# ---------------------------------------------------------------
# Sidebar: API key + chat management
# ---------------------------------------------------------------
if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = None

with st.sidebar:
    st.header("Configuration")
    api_key = st.text_input("Enter your Gemini API Key", type="password", value="")
    st.markdown("---")

    st.header("Chats")
    if st.button("➕ Start New Chat", use_container_width=True):
        new_id = create_chat("New Chat")
        st.session_state.active_chat_id = new_id
        st.rerun()

    st.markdown("")

    chats = get_all_chats()
    if not chats:
        st.caption("No chats yet. Start one above.")
    else:
        for chat_id, title, created_at in chats:
            is_active = st.session_state.active_chat_id == chat_id
            c1, c2 = st.columns([6, 1])
            with c1:
                icon = "🟢" if is_active else "💬"
                if st.button(f"{icon} {title}", key=f"open_{chat_id}", use_container_width=True):
                    st.session_state.active_chat_id = chat_id
                    st.rerun()
            with c2:
                if st.button("🗑️", key=f"delete_{chat_id}"):
                    delete_chat(chat_id)
                    if st.session_state.active_chat_id == chat_id:
                        st.session_state.active_chat_id = None
                    st.rerun()

    st.markdown("---")
    st.markdown("**Built by Shahid Iqbal**\n*Senior QA Engineer Portfolio Project*")

# ---------------------------------------------------------------
# Main area
# ---------------------------------------------------------------
if not api_key:
    st.warning("Please enter your Gemini API Key in the sidebar to activate the AI assistant.")
elif st.session_state.active_chat_id is None:
    st.info("Click **Start New Chat** in the sidebar, or open an existing chat, to begin.")
else:
    client = genai.Client(api_key=api_key)
    chat_id = st.session_state.active_chat_id

    history = get_messages(chat_id)
    for role, content in history:
        with st.chat_message(role):
            st.markdown(content)

    if user_input := st.chat_input(
        "Paste a user story (e.g., 'As a user I want to reset my password via email confirmation'...)"
    ):
        user_input = sanitize_text(user_input)
        add_message(chat_id, "user", user_input)
        with st.chat_message("user"):
            st.markdown(user_input)

        # Auto-title the chat from the first message
        current_history = get_messages(chat_id)
        if len(current_history) == 1:
            auto_title = user_input.strip()[:40] + ("..." if len(user_input.strip()) > 40 else "")
            update_chat_title(chat_id, auto_title)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown("*Analyzing requirements and structuring test suites...*")

            try:
                contents = []
                for role, content in get_messages(chat_id):
                    api_role = "user" if role == "user" else "model"
                    contents.append(
                        types.Content(role=api_role, parts=[types.Part(text=sanitize_text(content))])
                    )

                response = client.models.generate_content(
                    model="gemini-flash-latest",
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=QA_SYSTEM_PROMPT,
                        temperature=0.3,
                    ),
                )

                ai_response = sanitize_text(response.text)
                message_placeholder.markdown(ai_response)
                add_message(chat_id, "assistant", ai_response)

            except Exception as e:
                message_placeholder.error(f"An error occurred: {str(e)}")

        st.rerun()

    # Download current conversation
    history = get_messages(chat_id)
    if history:
        chat_export = "\n\n".join(f"**{role.upper()}:**\n{content}" for role, content in history)
        st.sidebar.download_button(
            label="📥 Download This Conversation",
            data=chat_export,
            file_name="qa_test_cases.md",
            mime="text/markdown",
        )