import streamlit as st
from datetime import datetime, timezone
from supabase import create_client
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
# Database setup (Supabase - persists across redeploys)
# ---------------------------------------------------------------
@st.cache_resource
def get_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

sb = get_supabase()

def create_chat(title="New Chat"):
    now = datetime.now(timezone.utc).isoformat()
    result = sb.table("chats").insert({"title": title, "created_at": now, "context": ""}).execute()
    return result.data[0]["id"]

def get_all_chats():
    result = sb.table("chats").select("id, title, created_at").order("created_at", desc=True).execute()
    return [(row["id"], row["title"], row["created_at"]) for row in result.data]

def get_chat_context(chat_id):
    result = sb.table("chats").select("context").eq("id", chat_id).execute()
    if result.data:
        return result.data[0].get("context") or ""
    return ""

def update_chat_context(chat_id, context):
    sb.table("chats").update({"context": context}).eq("id", chat_id).execute()

def get_messages(chat_id):
    result = (
        sb.table("messages")
        .select("role, content")
        .eq("chat_id", chat_id)
        .order("id", desc=False)
        .execute()
    )
    return [(row["role"], row["content"]) for row in result.data]

def add_message(chat_id, role, content):
    now = datetime.now(timezone.utc).isoformat()
    sb.table("messages").insert(
        {"chat_id": chat_id, "role": role, "content": content, "created_at": now}
    ).execute()

def update_chat_title(chat_id, title):
    sb.table("chats").update({"title": title}).eq("id", chat_id).execute()

def delete_chat(chat_id):
    sb.table("messages").delete().eq("chat_id", chat_id).execute()
    sb.table("chats").delete().eq("id", chat_id).execute()

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
    default_key = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""
    api_key = st.text_input("Enter your Gemini API Key", type="password", value=default_key)
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

    with st.expander("📋 Project Context for this chat", expanded=False):
        st.caption("Set background once (e.g. 'ServiceNow ITSM, focused on Incident and Change modules'). It's automatically included in every prompt for this chat.")
        current_context = get_chat_context(chat_id)
        new_context = st.text_area("Context", value=current_context, label_visibility="collapsed", height=100, key=f"context_{chat_id}")
        if st.button("Save Context", key=f"save_context_{chat_id}"):
            update_chat_context(chat_id, new_context)
            st.success("Context saved.")

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

                chat_context = get_chat_context(chat_id)
                system_prompt = QA_SYSTEM_PROMPT
                if chat_context.strip():
                    system_prompt += f"\n\nProject-specific context for this conversation:\n{chat_context.strip()}"

                response = client.models.generate_content(
                    model="gemini-flash-latest",
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
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