# Phase: AI Integration

## Goal

Integrate an AI assistant into Friend Hub as a chat-native bot that can answer questions, summarise conversations, generate images, and eventually perform approved actions such as creating polls, events, reminders, and agent jobs.

The AI should feel like another member of the group chat, not a separate disconnected feature.

---

## Core Principles

- AI appears as a bot user in chat, e.g. `Hub Bot`.
- AI is invoked intentionally with `@hub` or slash commands.
- Provider API keys are never exposed to users.
- Usage is tracked per group and per user.
- AI actions should draft first, then require confirmation.
- The system should be provider-agnostic so models can be swapped later.
- Start simple: recent messages first, clever memory later.

---

## Target Features

### Phase 1: Basic AI Bot

Add a basic AI bot that can respond in chat.

Example usage:

```text
@hub summarise the last 30 messages
@hub what did I miss?
@hub give us 5 ideas for Saturday
```

Requirements:

Add an AI bot/system user.
Detect messages beginning with @hub.
Fetch recent chat context.
Send request to selected chat model.
Post AI response back into the chat as a normal message.
Store usage metadata.
Add simple error handling and rate limiting.

Acceptance criteria:

Users can mention @hub in chat.
AI replies appear in the same chat thread.
AI replies are stored as normal chat messages.
Failed requests show a friendly error message.
Backend does not expose API keys to the frontend.
Phase 2: AI Provider Abstraction

Create a backend AI gateway layer.

Suggested structure:

```
app/
  ai/
    gateway.py
    providers/
      openai_provider.py
      anthropic_provider.py
      gemini_provider.py
    prompts/
      chat.py
      commands.py
    usage.py
```

Initial implementation can support one provider only, but the interface should allow others later.

Example interface:

```
class ChatModelProvider:
    def complete_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
    ) -> str:
...


Recommended starting provider:
```
Primary: OpenAI
Default chat model: cheap/fast model
Premium model: stronger reasoning model
Image model: separate image generation model
```

Acceptance criteria:

AI calls go through one backend gateway.
Model/provider choice is configurable.
Frontend does not know provider details.
Usage events are recorded.
Phase 3: Context Strategy

Start with simple recent-message context, then build towards smarter retrieval.

Initial Context

For normal @hub calls, include:

- system prompt
- current group/chat metadata
- pinned items
- latest 20–50 chat messages
- user request
Later Context

Add:

- active polls
- upcoming events
- open reminders
- rolling chat summaries
- referenced Hub Items
- semantic search results

Context should be command-aware.

Examples:

@summarise
→ last 100 messages

@poll
→ current message + last 30 messages + existing active polls

@event
→ current message + recent messages + upcoming events

@catchup
→ messages since user last read

Acceptance criteria:

AI receives enough context to be useful.
Token usage is bounded.
Context assembly is handled server-side.
Referenced items like #E-1 or #P-3 can be included later.
Phase 4: Credit And Usage Ledger

Add AI usage tracking and group-level credits.

Do not expose provider tokens to users. Instead, maintain a credit balance.

Suggested tables:

ai_credit_transactions
- id
- group_id
- user_id
- amount_pence
- type
- created_at

ai_usage_events
- id
- group_id
- user_id
- provider
- model
- command
- input_tokens
- output_tokens
- image_count
- estimated_cost_pence
- created_at

Transaction types:

contribution
usage
refund
adjustment

Frontend should show:

Group AI balance
User contributions
Recent AI usage
Estimated cost per request

Acceptance criteria:

Each AI request records usage.
Group balance can be checked before expensive calls.
AI requests can be blocked when balance is too low.
Admin/dev can manually add credits initially.
Phase 5: Slash Commands

Add explicit AI commands.

Initial commands:

/hub summarise
/hub catchup
/hub poll
/hub event
/hub reminder
/hub image
/hub decide

Command examples:

/hub summarise last 50 messages
/hub poll where should we go Friday?
/hub event make an event for pub Friday 8pm
/hub reminder remind Mike to book the train
/hub image make a terrible Sunday league poster

Command model:

name
description
handler_type
required_permission
estimated_cost_level
enabled

Handler types:

llm
image
tool
agent

Acceptance criteria:

Commands are parsed consistently.
Unknown commands return helpful suggestions.
Commands can be enabled/disabled.
Command usage is tracked.
Phase 6: Drafted Tool Actions

Allow AI to create app objects only after user confirmation.

Supported draft actions:

create_poll
create_event
create_reminder
create_idea
pin_item

Example flow:

User:
@hub make this into a poll

AI:
I can create this poll:

Title: Where should we go Friday?
Options:
- Pub
- Town
- Someone's house
- Stay in

[Create Poll] [Edit] [Cancel]

The AI should return structured data, not directly mutate the database.

Suggested draft object:

{
  "action_type": "create_poll",
  "title": "Where should we go Friday?",
  "payload": {
    "options": ["Pub", "Town", "Someone's house", "Stay in"]
  },
  "requires_confirmation": true
}

Acceptance criteria:

AI can draft polls/events/reminders.
User must confirm before creation.
Confirmed actions create normal Hub Items.
Drafts can be cancelled or edited.
Phase 7: Image Generation

Add image generation as a higher-cost command.

Example usage:

/hub image generate a poster for Friday pub night
/hub image make our football XI as a terrible Sunday league graphic

Flow:

prompt
→ estimate cost
→ confirm if needed
→ generate image
→ post image into chat
→ optionally save to Photos

Acceptance criteria:

Image generation is separate from chat completion.
Cost is tracked.
Generated images appear in chat.
Images can be saved into Photos.
Expensive generation can require confirmation.
Phase 8: Rolling Summaries And Memory

Add lightweight conversation memory.

Suggested summary types:

daily_summary
weekly_summary
open_questions
decisions_made
possible_events
possible_poll_topics
group_lore

Trigger options:

Every 100 messages
Daily scheduled job
Manual /hub summarise

Stored summary fields:

id
group_id
chat_id
summary_type
content
message_start_id
message_end_id
created_at

Acceptance criteria:

AI can use summaries instead of always reading large chat history.
Summaries are regenerated or appended periodically.
Users can inspect summaries.
Summaries link back to message ranges where possible.
Phase 9: Semantic Search

Add embeddings for older chat retrieval.

Embeddable entities:

messages
message batches
Hub Items
comments
summaries

Example flow:

User:
@hub when did we talk about camping?

System:
- embed query
- search old messages/summaries
- retrieve relevant results
- answer with links back to chat

Acceptance criteria:

AI can retrieve old relevant discussions.
Search results include links back to source messages/items.
Retrieval is bounded and cost-controlled.
Phase 10: OpenClaw / External Agent Integration

Integrate external agents as long-running jobs, not direct chat execution.

Architecture:

Chat command
→ AI Gateway
→ Agent Job Queue
→ OpenClaw Worker
→ Progress updates
→ Final result posted back to chat

Example:

@hub ask OpenClaw to find cottages in the Lakes for 6 people

Response:

Agent job started.
Status: researching options.

Later:

Found 5 options. Want me to create a poll?

Agent jobs should be heavily permissioned.

Permission levels:

Level 0: Read-only
Level 1: Draft actions
Level 2: Create Friend Hub objects
Level 3: External tools
Level 4: Server/admin actions

Acceptance criteria:

OpenClaw runs as a separate worker/service.
Jobs have status tracking.
Results post back into chat.
External actions require explicit approval.
Full audit trail is stored.
Backend Tasks
Add AI gateway service.
Add provider abstraction.
Add environment variables for provider keys.
Add bot user/system sender.
Add @hub mention detection.
Add usage event table.
Add credit transaction table.
Add command parser.
Add context builder.
Add draft action model.
Add confirmation endpoint.
Add image generation endpoint.
Add optional background worker for summaries/agents.
Frontend Tasks
Show AI bot messages in chat.
Add loading state while AI responds.
Add failed-response state.
Add command suggestions.
Add AI credit/balance display.
Add draft action cards.
Add confirm/edit/cancel buttons.
Add image generation UI.
Add AI settings/admin page.
Environment Variables
AI_PROVIDER=openai
AI_DEFAULT_CHAT_MODEL=
AI_PREMIUM_CHAT_MODEL=
AI_IMAGE_MODEL=
AI_API_KEY=
AI_MONTHLY_BUDGET_PENCE=
AI_DEFAULT_GROUP_LIMIT_PENCE=
AI_ENABLE_IMAGE_GENERATION=false
AI_ENABLE_AGENT_JOBS=false
Safety Rules
Never expose provider API keys to the frontend.
Never allow AI to mutate data without confirmation.
Store all AI usage events.
Apply rate limits per user and group.
Require confirmation for costly image generation.
Require admin approval for external agent tools.
Keep prompts and context server-side.
Sanitize user-provided prompts before tool execution.
Log agent actions clearly.
Suggested Build Order
Step 1

Basic @hub chat response using latest 30 messages.

Step 2

Usage tracking and simple per-user rate limit.

Step 3

Pinned items and active items included in context.

Step 4

Slash command parsing.

Step 5

Draft poll/event/reminder creation.

Step 6

Credit ledger and group balance UI.

Step 7

Image generation.

Step 8

Rolling summaries.

Step 9

Semantic search.

Step 10

OpenClaw agent jobs.

Minimal First Version

The first useful version should only include:

@hub mention detection
latest 30 message context
one chat model provider
AI replies as bot messages
usage logging
basic error handling

Do not start with:

OpenClaw
semantic search
autonomous tool use
complex memory
multi-provider UI
payment integration

Those can come later once the group is actually using the bot.

Definition Of Done
Users can mention @hub in chat.
AI responds in the same chat.
AI response is stored as a normal message.
AI request includes recent chat context.
Backend usage event is recorded.
API keys are server-side only.
Failed AI calls do not break chat.
Implementation is provider-agnostic enough to swap models later.

