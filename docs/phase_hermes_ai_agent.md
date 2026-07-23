e# Phase: Hermes AI Agent

## Goal

Build a Hermes-style persistent AI agent layer for Friend Hub.

This should not replace the existing Hub Bot Lab, memory tables, suggestion tables, or Hub Items system.

Instead, it should sit above them as an orchestration layer that can:

- Read recent chat context
- Search stored memories
- Use explicit tools
- Propose actions
- Create suggestions
- Run scheduled summaries
- Ask for human approval before changing important state

The agent should behave like a careful group assistant, not an uncontrolled autonomous system.

---

## Current Foundation

Assume these already exist:

- AI memory entries table
- AI suggestions table
- Hub Bot Lab page
- FakeLLMClient
- LLMClient interface
- HubSummaryService
- Suggestion accept/reject flow
- Hub Items system
- Chat messages stored in Postgres

---

## Core Principle

The Hermes agent must not directly perform risky actions.

It may propose:

- Polls
- Events
- Reminders
- Tags
- Summaries
- Agenda items
- Memory entries
- Hub Item links

But user approval is required before these become real Hub Items, unless the action is explicitly marked as safe.

---

## Phase 1: Agent Tool Layer

Create an explicit tool registry.

Each tool should have:

- name
- description
- input schema
- output schema
- safety level
- handler function

Example tools:

- search_memories
- list_recent_chat_messages
- list_pending_suggestions
- create_memory_entry
- create_ai_suggestion
- propose_hub_item
- find_unresolved_plans
- summarise_recent_chat
- list_recent_hub_items
- get_item_by_reference
- link_items
- create_bot_announcement

Safety levels:

- read_only
- safe_write
- approval_required
- admin_only

The agent may call read_only and safe_write tools directly.

The agent must create suggestions for approval_required actions.

---

## Phase 2: Agent Runtime

Create a HubAgentService.

Responsibilities:

- Accept a user message or scheduled task
- Build agent context
- Select available tools
- Call the configured LLM
- Parse tool calls or structured JSON
- Execute safe tools
- Store outputs
- Return a human-readable reply

The agent must support:

- interactive mode from Hub Bot Lab
- scheduled mode from cron/background jobs
- future chat command mode from the main group chat

Initial agent modes:

- chat_assistant
- daily_summary
- weekly_recap
- unresolved_plan_scan
- suggestion_generation
- memory_cleanup

---

## Phase 3: Structured Agent Output

The LLM must return strict JSON.

Example output:

{
  "reply": "I found two unresolved plans and created suggestions for them.",
  "tool_calls": [
    {
      "tool": "search_memories",
      "arguments": {
        "query": "unresolved plans",
        "limit": 10
      }
    }
  ],
  "memory_entries": [
    {
      "memory_type": "unresolved_plan",
      "title": "Possible Friday pub plan",
      "content": "The group discussed going to the pub on Friday but no time was decided.",
      "confidence": 0.82,
      "tags": ["pub", "friday", "planning"]
    }
  ],
  "suggestions": [
    {
      "suggestion_type": "poll",
      "title": "Pick a Friday pub time",
      "body": "The group has not agreed a time yet. Suggested options: 7pm, 8pm, 9pm.",
      "proposed_hub_item_type": "poll",
      "proposed_payload": {
        "question": "What time should we go to the pub on Friday?",
        "options": ["7pm", "8pm", "9pm"]
      }
    }
  ],
  "announcements": [
    {
      "body": "I created a suggestion for the Friday pub plan."
    }
  ]
}

All output must be validated before database writes.

Invalid JSON should return a clean error and write nothing.

---

## Phase 4: Provider Support

Keep FakeLLMClient for tests.

Add provider implementations behind config:

- fake
- ollama
- openrouter
- openai compatible

Environment variables:

AI_PROVIDER=fake
AI_MODEL=
AI_BASE_URL=
AI_API_KEY=
AI_MAX_INPUT_MESSAGES=100
AI_MAX_MEMORY_RESULTS=20
AI_ENABLE_AGENT=false

Default must remain fake.

Real providers must be opt-in.

---

## Phase 5: Hub Bot Lab Upgrade

Upgrade the Hub Bot Lab page into the main agent control room.

Tabs:

- Chat
- Suggestions
- Memories
- Agent Runs
- Tools
- Settings

Chat tab:

- user can talk to Hub Bot
- command buttons for common workflows
- show tool calls used
- show created memories/suggestions
- show errors cleanly

Agent Runs tab:

- list previous runs
- status
- mode
- prompt summary
- model used
- tool calls
- created memories
- created suggestions
- error messages

Tools tab:

- list available tools
- safety level
- description
- enabled/disabled state

Settings tab:

- provider
- model
- max messages
- agent enabled flag
- dry run mode

---

## Phase 6: Agent Run Logging

Create ai_agent_runs table.

Fields:

- id UUID primary key
- mode string
- status string
- user_message text nullable
- prompt_summary text nullable
- provider string
- model string nullable
- raw_response text nullable
- parsed_response JSON nullable
- tool_calls JSON nullable
- created_memory_ids JSON/list
- created_suggestion_ids JSON/list
- error_message text nullable
- started_at datetime
- completed_at datetime nullable

Every agent run must be inspectable.

No silent failures.

---

## Phase 7: Scheduled Agent Jobs

Add scheduled jobs only after manual Hub Bot Lab usage works.

Initial scheduled jobs:

- daily_summary
- weekly_recap
- unresolved_plan_scan
- stale_suggestion_cleanup

Do not add Celery initially.

Use the simplest existing deployment-compatible option:

- cron hitting an internal endpoint
- lightweight FastAPI background task
- VPS cron command
- later upgrade to a proper worker if needed

Scheduled jobs must respect:

- AI_ENABLE_AGENT
- dry run mode
- max run frequency
- max token or cost budget

---

## Phase 8: Announcements

Do not create a separate announcements channel immediately.

First, create bot announcements as stored activity items.

Announcement examples:

- Hub Bot created 2 suggestions from today’s chat
- Hub Bot found an unresolved plan
- Hub Bot generated the weekly recap
- Luke accepted a suggested poll
- Poll #P-12 was created from a bot suggestion

Later options:

- show announcements in Hub Bot Lab
- show them in notifications
- optionally mirror them into main chat
- optionally create a dedicated bot announcements channel

---

## Phase 9: Safety Rules

The agent must not:

- delete data
- edit user messages
- create events without approval
- create polls without approval
- invite people without approval
- send external messages
- run shell commands
- access unrelated files
- make hidden changes

The agent may directly:

- read recent messages
- search memories
- create low-risk memory entries
- create AI suggestions
- create agent run logs
- create bot activity logs

---

## Phase 10: Tests

Add tests for:

- tool registry
- tool safety levels
- HubAgentService with FakeLLMClient
- invalid JSON handling
- suggestion creation
- memory creation
- agent run logging
- dry run mode
- scheduled mode
- provider config selection

Tests must not call real LLM providers.

---

## Acceptance Criteria

This phase is complete when:

- Hub Bot Lab can run a real agent interaction
- the agent can call read-only tools
- the agent can create memory entries
- the agent can create suggestions
- all writes are logged
- all agent runs are inspectable
- unsafe actions become suggestions, not direct writes
- fake provider tests pass
- real provider can be enabled locally via config
- the feature works without paid APIs by default

---

## Non-Goals

Do not implement:

- full Hermes Agent package integration
- autonomous infinite loops
- self-modifying code
- shell access
- browser automation
- multi-agent delegation
- vector database
- Redis
- Celery
- paid API dependency
- separate announcements channel

These can be considered later if the simple agent proves useful.

---

## Implementation Prompt

Implement Phase Hermes AI Agent for Friend Hub.

Build a Hermes-style persistent agent orchestration layer using the existing AI memory, AI suggestions, Hub Bot Lab, and Hub Items systems.

Do not integrate the Hermes Agent package directly.

Focus on:

- explicit tools
- safe tool execution
- structured JSON output
- inspectable agent runs
- human approval for risky actions
- fake provider tests
- optional local/provider model support

Keep the implementation small, reviewable, and deterministic.

Do not add autonomous loops or background workers until the manual Hub Bot Lab flow works.