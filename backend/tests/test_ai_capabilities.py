"""Tests for the capabilities module and the two-pass agent runtime.

All tests are unit tests — no real database or network calls.
"""
import asyncio
import json
import os
import unittest

os.environ.setdefault("DEBUG", "false")

from app.domains.ai.capabilities import (
    LLM_COMMANDS,
    SERVER_COMMANDS,
    build_capabilities_prompt,
    build_capabilities_sentence,
    build_help_reply,
    is_catchup_query,
    is_help_query,
)
from app.domains.ai.agent_runtime import HubAgentRuntime
from app.domains.ai.tools import ToolRegistry


# ── Capabilities module ───────────────────────────────────────────────────────


class TestIsHelpQuery(unittest.TestCase):
    def test_matches_help_phrases(self):
        for q in (
            "/help",
            "/HELP",
            "help",
            "Help!",
            "what can you do?",
            "  What can you do  ",
            "commands",
        ):
            self.assertTrue(is_help_query(q), q)

    def test_does_not_match_questions_containing_help(self):
        for q in (
            "can you help me plan Friday?",
            "help me make a poll",
            "what can you do about Mike being late",
            "",
        ):
            self.assertFalse(is_help_query(q), q)


class TestIsCatchupQuery(unittest.TestCase):
    def test_matches_catchup_phrases(self):
        for q in (
            "/catchup",
            "/CATCHUP since Monday",
            "catch up",
            "Catch me up!",
            "what did I miss?",
            "  What have I missed  ",
            "anything I missed?",
        ):
            self.assertTrue(is_catchup_query(q), q)

    def test_does_not_match_messages_merely_mentioning_missing(self):
        for q in (
            "I miss summer",
            "did you catch the game",
            "we missed you at the pub",
            "summarise camping",
            "",
        ):
            self.assertFalse(is_catchup_query(q), q)

    def test_catchup_listed_in_help(self):
        self.assertIn("/catchup", build_help_reply())
        self.assertIn("/catchup", build_capabilities_sentence())


class TestCapabilitiesText(unittest.TestCase):
    def test_help_reply_lists_every_command(self):
        reply = build_help_reply()
        for cmd in SERVER_COMMANDS + LLM_COMMANDS:
            self.assertIn(cmd["command"].split(" ")[0], reply)

    def test_prompt_block_mentions_memory_and_commands(self):
        prompt = build_capabilities_prompt()
        self.assertIn("memory", prompt.lower())
        for cmd in SERVER_COMMANDS + LLM_COMMANDS:
            self.assertIn(cmd["command"].split(" ")[0], prompt)

    def test_sentence_is_single_line(self):
        sentence = build_capabilities_sentence()
        self.assertNotIn("\n", sentence)
        self.assertIn("/help", sentence)


# ── Two-pass runtime ──────────────────────────────────────────────────────────


class _ScriptedProvider:
    """Returns scripted responses in order, recording prompts it received."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete_chat(self, messages, model, temperature=0.7):
        self.calls.append(messages)
        return self.responses.pop(0), 0, 0


class _ScriptedLLMClient:
    """Looks like OpenRouterLLMClient to the runtime (_get_provider + model)."""

    model = "test-model"

    def __init__(self, responses):
        self.provider = _ScriptedProvider(responses)

    def _get_provider(self):
        return self.provider


def _registry_with_tools():
    registry = ToolRegistry()

    async def lookup(db, query: str = "", _ctx: dict | None = None):
        return {"found": True, "answer": "camping was discussed in March"}

    async def create_thing(db, title: str = "", _ctx: dict | None = None):
        return {"success": True, "title": title}

    registry.register("lookup", "Look something up", "read_only", lookup)
    registry.register("create_thing", "Create a thing", "safe_write", create_thing)
    return registry


def _response(reply, tool_calls=None):
    return json.dumps(
        {"reply": reply, "tool_calls": tool_calls or [], "memories": [], "suggestions": []}
    )


class TestTwoPassRuntime(unittest.TestCase):
    def _run(self, responses):
        client = _ScriptedLLMClient(responses)
        runtime = HubAgentRuntime(
            db=None, llm_client=client, registry=_registry_with_tools()
        )
        result = asyncio.run(runtime.run(user_message="when did we talk about camping?"))
        return result, client

    def test_read_only_tools_trigger_second_pass(self):
        result, client = self._run([
            _response("Let me check.", [{"tool": "lookup", "arguments": {"query": "camping"}}]),
            _response("You discussed camping in March."),
        ])
        self.assertEqual(result.reply, "You discussed camping in March.")
        self.assertEqual(len(client.provider.calls), 2)
        # The follow-up prompt must contain the pass-1 tool results
        followup_prompt = client.provider.calls[1][1]["content"]
        self.assertIn("camping was discussed in March", followup_prompt)

    def test_no_tools_means_single_pass(self):
        result, client = self._run([_response("Just chatting.")])
        self.assertEqual(result.reply, "Just chatting.")
        self.assertEqual(len(client.provider.calls), 1)

    def test_write_tools_do_not_trigger_second_pass(self):
        result, client = self._run([
            _response("Created!", [{"tool": "create_thing", "arguments": {"title": "BBQ"}}]),
        ])
        self.assertEqual(result.reply, "Created!")
        self.assertEqual(len(client.provider.calls), 1)

    def test_second_pass_can_execute_write_tools(self):
        result, client = self._run([
            _response("Let me check.", [{"tool": "lookup", "arguments": {"query": "camping"}}]),
            _response("Made it a poll.", [{"tool": "create_thing", "arguments": {"title": "Camping?"}}]),
        ])
        self.assertEqual(len(client.provider.calls), 2)
        executed = [tr["tool"] for tr in result.tool_results if tr.get("success")]
        self.assertEqual(executed, ["lookup", "create_thing"])

    def test_second_pass_read_tools_are_blocked(self):
        result, client = self._run([
            _response("Let me check.", [{"tool": "lookup", "arguments": {"query": "camping"}}]),
            _response("Checking again.", [{"tool": "lookup", "arguments": {"query": "again"}}]),
        ])
        self.assertEqual(len(client.provider.calls), 2)
        skipped = [tr for tr in result.tool_results if tr.get("skipped")]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["tool"], "lookup")

    def test_failed_second_pass_keeps_first_reply(self):
        class _ExplodingProvider(_ScriptedProvider):
            async def complete_chat(self, messages, model, temperature=0.7):
                if self.calls:
                    raise RuntimeError("provider down")
                return await super().complete_chat(messages, model, temperature)

        client = _ScriptedLLMClient([])
        client.provider = _ExplodingProvider([
            _response("Let me check.", [{"tool": "lookup", "arguments": {"query": "camping"}}]),
        ])
        runtime = HubAgentRuntime(
            db=None, llm_client=client, registry=_registry_with_tools()
        )
        result = asyncio.run(runtime.run(user_message="camping?"))
        self.assertEqual(result.reply, "Let me check.")


if __name__ == "__main__":
    unittest.main()
