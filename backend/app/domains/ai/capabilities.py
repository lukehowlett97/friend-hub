"""
Single source of truth for Hub Bot's user-facing capabilities.

The slash-command tables and blurbs here feed every place the bot describes
itself: the agent runtime system prompt, the legacy chat prompt in
hub_agent_service, and the /help fast path. Add new commands here, not in
individual prompts, so the bot's self-description cannot drift between layers.
"""

import re

# Commands intercepted server-side in SharedHubBotService.process_query —
# the LLM never sees these, so prompts must describe them explicitly.
SERVER_COMMANDS: list[dict] = [
    {
        "command": "/summarise [window]",
        "description": "Summarise recent chat. Windows: 'past 3 hours', 'today', 'yesterday', 'since 14:00' (default: past 2 hours).",
    },
    {
        "command": "/search <question>",
        "description": "Answer a question from older chat history, hub items, and saved memories — by topic ('when did we talk about camping?') or date ('what happened on 1 June 2025?').",
    },
    {
        "command": "/image <prompt>",
        "description": "Generate an image and post it into the chat.",
    },
    {
        "command": "/catchup [window]",
        "description": "Catch up on everything since you last read — messages, new events, open polls and reminders. Optional window: '/catchup since Monday'.",
    },
    {
        "command": "/help",
        "description": "Show this list of commands and capabilities.",
    },
]

# Commands rewritten into propose_* instructions and handled by the LLM runtime.
LLM_COMMANDS: list[dict] = [
    {
        "command": "/event <details>",
        "description": "Create an event, e.g. /event pub Friday 8pm.",
    },
    {
        "command": "/poll <question>",
        "description": "Create a poll, e.g. /poll where should we go Saturday?",
    },
    {
        "command": "/remind <details>",
        "description": "Create a reminder (can repeat daily/weekly), e.g. /remind everyone to book taxis Thursday.",
    },
    {
        "command": "/idea <details>",
        "description": "Log an idea for later.",
    },
]

MEMORY_BLURB = (
    "Hub Bot has long-term memory: it saves notes about decisions, unresolved plans, "
    "preferences, and group lore from chat, and uses them when answering. "
    "Relevant memories appear in the MEMORY section of the context."
)

ITEMS_BLURB = (
    "Items Hub Bot creates (events, polls, reminders, ideas) get short IDs like "
    "#E-1 or #P-2 that anyone can reference later in chat."
)


def _command_lines(commands: list[dict]) -> list[str]:
    return [f"- {c['command']} — {c['description']}" for c in commands]


def build_capabilities_prompt() -> str:
    """Capability block for LLM system prompts.

    Tells the model about the server-side commands it never sees, its memory
    system, and how to answer "what can you do" accurately.
    """
    lines = [
        "You can do the following for users. Commands handled by the server "
        "before you see them (still describe them when asked):",
        *_command_lines(SERVER_COMMANDS),
        "Commands you handle yourself via the matching propose_* tool:",
        *_command_lines(LLM_COMMANDS),
        MEMORY_BLURB,
        ITEMS_BLURB,
        "Users can also just mention @hub with a question — no command needed. "
        "When asked what you can do, describe ONLY the commands and abilities "
        "listed here; never invent capabilities.",
    ]
    return "\n".join(lines)


def build_capabilities_sentence() -> str:
    """One-line command summary for compact prose prompts."""
    all_cmds = ", ".join(
        c["command"].split(" ")[0] for c in SERVER_COMMANDS + LLM_COMMANDS
    )
    return (
        f"Users can trigger you with slash commands ({all_cmds}); "
        "/help lists everything you can do."
    )


def build_help_reply() -> str:
    """User-facing /help message, answered without an LLM call."""
    lines = [
        "Here's what I can do 👋",
        "",
        "**Commands:**",
        *_command_lines(SERVER_COMMANDS + LLM_COMMANDS),
        "",
        "You can also just mention me — `@hub what did I miss?`, "
        "`@hub make this into a poll` — and I'll work it out.",
        "",
        f"_{MEMORY_BLURB}_",
    ]
    return "\n".join(lines)


_HELP_PHRASES = {
    "help",
    "/help",
    "/commands",
    "commands",
    "what can you do",
    "what do you do",
    "what can you do for me",
    "what are your capabilities",
    "list your capabilities",
    "list commands",
    "show commands",
    "how do i use you",
    "how do you work",
}


def is_help_query(query: str) -> bool:
    """True when the query is asking what the bot can do.

    Deliberately conservative: exact phrase matches only (after stripping
    punctuation), so questions that merely contain the word 'help' still go
    to the LLM.
    """
    normalized = re.sub(r"[?!.,]+", "", (query or "").strip().lower())
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized in _HELP_PHRASES or normalized.startswith("/help")


_CATCHUP_PHRASES = {
    "catchup",
    "catch up",
    "catch me up",
    "what did i miss",
    "what have i missed",
    "what did i miss while i was away",
    "anything i missed",
    "did i miss anything",
}


def is_catchup_query(query: str) -> bool:
    """True when the query is asking to catch up on missed chat.

    Same conservative exact-phrase matching as is_help_query, so messages
    that merely mention missing something still go to the LLM.
    """
    normalized = re.sub(r"[?!.,]+", "", (query or "").strip().lower())
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized in _CATCHUP_PHRASES or normalized.startswith("/catchup")
