import asyncio
import types
import unittest
from unittest.mock import patch


class TestReminderSchedulerMessages(unittest.TestCase):
    def test_llm_prompt_includes_reminder_context_as_required_input(self):
        from app.domains.reminders.scheduler import _generate_reminder_message

        captured = {}

        class FakeProvider:
            async def complete_chat(self, messages, model, temperature):
                captured["messages"] = messages
                captured["model"] = model
                captured["temperature"] = temperature
                return ("Reminder reply", None, None)

        class FakeLLM:
            model = "fake-model"

            def _get_provider(self):
                return FakeProvider()

        reminder = types.SimpleNamespace(
            text="Book taxis",
            context="The group needs taxis booked before Friday night out.",
            recurrence=None,
        )

        with (
            patch("app.config.get_settings", return_value=types.SimpleNamespace(ai_api_key="key")),
            patch("app.domains.ai.summary_service.create_llm_client", return_value=FakeLLM()),
        ):
            reply = asyncio.run(_generate_reminder_message(reminder, ["Jimi"]))

        self.assertEqual(reply, "Reminder reply")
        prompt_text = "\n".join(message["content"] for message in captured["messages"])
        self.assertIn("Reminder context (must influence the response when provided)", prompt_text)
        self.assertIn("The group needs taxis booked before Friday night out.", prompt_text)
        self.assertIn("do not ignore it", prompt_text)
        self.assertIn("Assigned to: Jimi", prompt_text)

    def test_simple_fallback_includes_context(self):
        from app.domains.reminders.scheduler import _simple_reminder_message

        reminder = types.SimpleNamespace(
            text="Book taxis",
            context="The group needs taxis booked before Friday night out.",
        )

        message = _simple_reminder_message(reminder, ["Jimi"])

        self.assertIn("Reminder: Book taxis", message)
        self.assertIn("The group needs taxis booked before Friday night out.", message)
        self.assertIn("@Jimi", message)

    def test_append_reminder_reference_places_ref_at_end_once(self):
        from app.domains.reminders.scheduler import _append_reminder_reference

        self.assertEqual(
            _append_reminder_reference("Reminder: Book taxis", "#R-6"),
            "Reminder: Book taxis #R-6",
        )
        self.assertEqual(
            _append_reminder_reference("Reminder: Book taxis #R-6", "#R-6"),
            "Reminder: Book taxis #R-6",
        )
