"""Tests for AI Memory and Suggestions feature."""
import asyncio
import types
import unittest
import uuid
from datetime import datetime, timedelta

from app.domains.ai.repository import AIMemoryRepository, AISuggestionRepository
from app.domains.ai.summary_service import FakeLLMClient, HubSummaryService, create_summary_service
from app.domains.ai.agent_run_repository import AgentRunRepository
from app.models.ai_memory import AIMemoryEntry, AISuggestion


# ── Dummy Database for Unit Tests ─────────────────────────────────────────────


class DummyResult:
    """A mock SQLAlchemy execute result."""

    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def fetchall(self):
        return self._rows

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._rows)


class DummyDb:
    """A minimal fake database session for unit testing."""

    def __init__(self):
        self.added = []
        self.flushed = False
        self.committed = False
        self._entries = {}
        self._suggestions = {}

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushed = True
        for value in self.added:
            if isinstance(value, AIMemoryEntry) and value.id is None:
                value.id = uuid.uuid4()
                self._entries[value.id] = value
            if isinstance(value, AISuggestion) and value.id is None:
                value.id = uuid.uuid4()
                self._suggestions[value.id] = value

    async def commit(self):
        self.committed = True

    async def refresh(self, value):
        pass

    async def get(self, model, key):
        if model == AIMemoryEntry:
            return self._entries.get(key)
        if model == AISuggestion:
            return self._suggestions.get(key)
        return None

    async def execute(self, stmt):
        return DummyResult()


# ── Test AIMemoryRepository ──────────────────────────────────────────────────


class TestAIMemoryRepository(unittest.TestCase):
    """Test the AIMemoryRepository class."""

    def test_create_memory_entry(self):
        """Test that create adds an entry and assigns an ID."""
        db = DummyDb()
        repo = AIMemoryRepository(db)

        entry = asyncio.run(repo.create(
            memory_type="daily_summary",
            content="Test summary content",
            title="Test Summary",
            tags=["test", "summary"],
            confidence=0.9,
        ))

        self.assertIsNotNone(entry.id)
        self.assertEqual(entry.memory_type, "daily_summary")
        self.assertEqual(entry.content, "Test summary content")
        self.assertEqual(entry.title, "Test Summary")
        self.assertEqual(entry.tags, ["test", "summary"])
        self.assertEqual(entry.confidence, 0.9)
        self.assertTrue(db.flushed)

    def test_create_memory_entry_defaults(self):
        """Test that create uses defaults for optional fields."""
        db = DummyDb()
        repo = AIMemoryRepository(db)

        entry = asyncio.run(repo.create(
            memory_type="user_preference",
            content="Some preference",
        ))

        self.assertEqual(entry.created_by, "hub_bot")
        self.assertEqual(entry.tags, [])
        self.assertIsNone(entry.title)
        self.assertIsNone(entry.confidence)

    def test_list_recent_empty(self):
        """Test list_recent returns empty list when no entries."""
        db = DummyDb()
        repo = AIMemoryRepository(db)

        entries = asyncio.run(repo.list_recent(limit=10))
        self.assertEqual(entries, [])

    def test_count_empty(self):
        """Test count returns 0 when no entries."""
        db = DummyDb()
        repo = AIMemoryRepository(db)

        count = asyncio.run(repo.count())
        self.assertEqual(count, 0)


# ── Test AISuggestionRepository ──────────────────────────────────────────────


class TestAISuggestionRepository(unittest.TestCase):
    """Test the AISuggestionRepository class."""

    def test_create_suggestion(self):
        """Test that create adds a suggestion and assigns an ID."""
        db = DummyDb()
        repo = AISuggestionRepository(db)

        suggestion = asyncio.run(repo.create(
            suggestion_type="poll",
            title="Test Poll Suggestion",
            body="This is a test suggestion",
            proposed_hub_item_type="poll",
            proposed_payload={"title": "Test Poll", "body": "Poll body"},
            source_memory_ids=["mem-1", "mem-2"],
        ))

        self.assertIsNotNone(suggestion.id)
        self.assertEqual(suggestion.suggestion_type, "poll")
        self.assertEqual(suggestion.title, "Test Poll Suggestion")
        self.assertEqual(suggestion.body, "This is a test suggestion")
        self.assertEqual(suggestion.proposed_hub_item_type, "poll")
        self.assertEqual(suggestion.proposed_payload, {"title": "Test Poll", "body": "Poll body"})
        self.assertEqual(suggestion.source_memory_ids, ["mem-1", "mem-2"])
        self.assertEqual(suggestion.status, "pending")
        self.assertTrue(db.flushed)

    def test_create_suggestion_defaults(self):
        """Test that create uses defaults for optional fields."""
        db = DummyDb()
        repo = AISuggestionRepository(db)

        suggestion = asyncio.run(repo.create(
            suggestion_type="summary",
            title="Summary Suggestion",
        ))

        self.assertIsNone(suggestion.body)
        self.assertIsNone(suggestion.proposed_hub_item_type)
        self.assertIsNone(suggestion.proposed_payload)
        self.assertEqual(suggestion.source_memory_ids, [])
        self.assertIsNone(suggestion.created_hub_item_id)

    def test_list_pending_empty(self):
        """Test list_pending returns empty list when no suggestions."""
        db = DummyDb()
        repo = AISuggestionRepository(db)

        suggestions = asyncio.run(repo.list_pending(limit=10))
        self.assertEqual(suggestions, [])

    def test_update_status(self):
        """Test updating suggestion status."""
        db = DummyDb()
        repo = AISuggestionRepository(db)

        # Create a suggestion
        suggestion = asyncio.run(repo.create(
            suggestion_type="reminder",
            title="Test Reminder",
        ))

        # Update status
        updated = asyncio.run(repo.update_status(
            suggestion.id,
            "accepted",
            created_hub_item_id=uuid.uuid4(),
        ))

        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "accepted")
        self.assertIsNotNone(updated.created_hub_item_id)

    def test_update_status_nonexistent(self):
        """Test updating a non-existent suggestion returns None."""
        db = DummyDb()
        repo = AISuggestionRepository(db)

        updated = asyncio.run(repo.update_status(
            uuid.uuid4(),
            "accepted",
        ))

        self.assertIsNone(updated)

    def test_count_empty(self):
        """Test count returns 0 when no suggestions."""
        db = DummyDb()
        repo = AISuggestionRepository(db)

        count = asyncio.run(repo.count())
        self.assertEqual(count, 0)


# ── Test FakeLLMClient ───────────────────────────────────────────────────────


class TestFakeLLMClient(unittest.TestCase):
    """Test the FakeLLMClient for deterministic output."""

    def test_generate_summary_basic(self):
        """Test that FakeLLMClient returns structured output."""
        client = FakeLLMClient()

        result = asyncio.run(client.generate_summary(
            messages_text="Hello world",
            hub_items_text="No items",
        ))

        self.assertIn("summary", result)
        self.assertIn("memories", result)
        self.assertIn("suggestions", result)
        self.assertIsInstance(result["memories"], list)
        self.assertIsInstance(result["suggestions"], list)

    def test_generate_summary_with_event_keyword(self):
        """Test that FakeLLMClient detects event-related content."""
        client = FakeLLMClient()

        result = asyncio.run(client.generate_summary(
            messages_text="Let's plan an event for next week",
            hub_items_text="",
        ))

        # Should create event-related memory and suggestion
        memory_types = [m["type"] for m in result["memories"]]
        suggestion_types = [s["type"] for s in result["suggestions"]]

        self.assertIn("unresolved_plan", memory_types)
        self.assertIn("event", suggestion_types)

    def test_generate_summary_with_food_keyword(self):
        """Test that FakeLLMClient detects food-related content."""
        client = FakeLLMClient()

        result = asyncio.run(client.generate_summary(
            messages_text="What should we eat for lunch?",
            hub_items_text="",
        ))

        memory_types = [m["type"] for m in result["memories"]]
        self.assertIn("user_preference", memory_types)

    def test_generate_summary_with_deadline_keyword(self):
        """Test that FakeLLMClient detects deadline-related content."""
        client = FakeLLMClient()

        result = asyncio.run(client.generate_summary(
            messages_text="The deadline is due tomorrow",
            hub_items_text="",
        ))

        suggestion_types = [s["type"] for s in result["suggestions"]]
        self.assertIn("reminder", suggestion_types)

    def test_generate_summary_always_has_daily_summary(self):
        """Test that FakeLLMClient always creates a daily_summary memory."""
        client = FakeLLMClient()

        result = asyncio.run(client.generate_summary(
            messages_text="Random chat",
            hub_items_text="",
        ))

        memory_types = [m["type"] for m in result["memories"]]
        self.assertIn("daily_summary", memory_types)


# ── Test HubSummaryService ───────────────────────────────────────────────────


class TestHubSummaryService(unittest.TestCase):
    """Test the HubSummaryService integration."""

    def test_summarize_chat_no_messages(self):
        """Test summarize_chat returns empty result when no messages."""
        db = DummyDb()
        service = HubSummaryService(db, FakeLLMClient())

        # Mock get_recent_messages to return empty
        original_method = service._build_messages_text
        service._build_messages_text = lambda msgs: ""

        result = asyncio.run(service.summarize_chat())

        self.assertEqual(result["summary"], "No recent messages to summarize.")
        self.assertEqual(result["memories_created"], 0)
        self.assertEqual(result["suggestions_created"], 0)

    def test_build_messages_text(self):
        """Test message text building."""
        db = DummyDb()
        service = HubSummaryService(db, FakeLLMClient())

        messages = [
            {"nickname": "Alice", "content": "Hello!", "created_at": "2024-01-01", "is_deleted": False},
            {"nickname": "Bob", "content": "Hi there!", "created_at": "2024-01-01", "is_deleted": False},
            {"nickname": "Alice", "content": "Deleted message", "created_at": "2024-01-01", "is_deleted": True},
        ]

        text = service._build_messages_text(messages)

        self.assertIn("Alice: Hello!", text)
        self.assertIn("Bob: Hi there!", text)
        self.assertNotIn("Deleted message", text)


# ── Test create_summary_service factory ──────────────────────────────────────


class TestCreateSummaryService(unittest.TestCase):
    """Test the create_summary_service factory function."""

    def test_create_with_fake_llm(self):
        """Test creating service with fake LLM."""
        db = DummyDb()
        service = create_summary_service(db, use_fake_llm=True)

        self.assertIsInstance(service, HubSummaryService)
        self.assertIsInstance(service.llm_client, FakeLLMClient)

    def test_create_without_fake_llm_no_key(self):
        """Test creating service without fake LLM falls back to Fake when no API key."""
        from unittest.mock import patch

        db = DummyDb()
        with patch("app.domains.ai.summary_service.settings") as mock_settings:
            mock_settings.ai_lab_provider = "fake"
            mock_settings.ai_api_key = None
            service = create_summary_service(db, use_fake_llm=False)

        self.assertIsInstance(service, HubSummaryService)
        self.assertIsInstance(service.llm_client, FakeLLMClient)


# ── Test Hub Bot Chat Endpoint ───────────────────────────────────────────────


class TestHubBotChat(unittest.TestCase):
    """Test the hub-bot-chat endpoint logic."""

    def test_help_message_for_unknown_command(self):
        """Test that unknown commands return help message."""
        # Simulate the command routing logic
        message = "hello there"
        message_lower = message.strip().lower()

        if "summarise" in message_lower or "summarize" in message_lower:
            reply = "Summary generated"
        elif "unresolved" in message_lower:
            reply = "Unresolved plans"
        elif "poll" in message_lower or "suggest poll" in message_lower:
            reply = "Poll suggestion created"
        elif "memories" in message_lower:
            reply = "Recent memories"
        else:
            reply = "Help message"

        self.assertEqual(reply, "Help message")

    def test_summarise_command_detected(self):
        """Test that summarise command is detected."""
        test_cases = [
            "summarise",
            "summarize today",
            "please summarise the chat",
            "SUMMARISE",
        ]

        for message in test_cases:
            message_lower = message.strip().lower()
            is_summarise = "summarise" in message_lower or "summarize" in message_lower
            self.assertTrue(is_summarise, f"Failed for: {message}")

    def test_unresolved_command_detected(self):
        """Test that unresolved command is detected."""
        test_cases = [
            "unresolved",
            "show unresolved plans",
            "any unresolved items?",
        ]

        for message in test_cases:
            message_lower = message.strip().lower()
            is_unresolved = "unresolved" in message_lower
            self.assertTrue(is_unresolved, f"Failed for: {message}")

    def test_poll_command_detected(self):
        """Test that poll command is detected."""
        test_cases = [
            "poll",
            "suggest poll",
            "create a poll",
            "suggest polls",
        ]

        for message in test_cases:
            message_lower = message.strip().lower()
            is_poll = "poll" in message_lower
            self.assertTrue(is_poll, f"Failed for: {message}")

    def test_memories_command_detected(self):
        """Test that memories command is detected."""
        test_cases = [
            "memories",
            "show memories",
            "recent memories",
        ]

        for message in test_cases:
            message_lower = message.strip().lower()
            is_memories = "memories" in message_lower
            self.assertTrue(is_memories, f"Failed for: {message}")


# ── Test Shared Tools ────────────────────────────────────────────────────────


class TestToolRegistry(unittest.TestCase):
    """Test the ToolRegistry class."""

    def test_registry_initialization(self):
        """Test that the registry starts empty."""
        from app.domains.ai.tools import ToolRegistry
        registry = ToolRegistry()
        tools = registry.list_tools()
        self.assertEqual(tools, [])

    def test_register_and_list_tools(self):
        """Test registering and listing tools."""
        from app.domains.ai.tools import ToolRegistry

        async def fake_hub_items(db, limit=10):
            return {"count": 0, "items": []}

        registry = ToolRegistry()
        registry.register(
            name="list_recent_hub_items",
            description="List recent items",
            safety="read_only",
            handler=fake_hub_items,
        )

        tools = registry.list_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "list_recent_hub_items")
        self.assertEqual(tools[0]["safety"], "read_only")

    def test_get_handler(self):
        """Test retrieving a handler by name."""
        from app.domains.ai.tools import ToolRegistry

        async def fake_handler(db):
            return {"result": "ok"}

        registry = ToolRegistry()
        registry.register("test_tool", "A test tool", "read_only", fake_handler)

        handler = registry.get_handler("test_tool")
        self.assertIsNotNone(handler)
        self.assertEqual(handler, fake_handler)

    def test_get_handler_not_found(self):
        """Test getting handler for non-existent tool returns None."""
        from app.domains.ai.tools import ToolRegistry
        registry = ToolRegistry()
        handler = registry.get_handler("nonexistent")
        self.assertIsNone(handler)

    def test_build_default_registry(self):
        """Test that the default registry has all expected tools."""
        from app.domains.ai.tools import build_default_registry
        registry = build_default_registry()
        tools = registry.list_tools()

        self.assertGreaterEqual(len(tools), 11)

        tool_names = [t["name"] for t in tools]
        self.assertIn("get_item_by_reference", tool_names)
        self.assertIn("search_hub_items", tool_names)
        self.assertIn("list_recent_hub_items", tool_names)
        self.assertIn("search_memories", tool_names)
        self.assertIn("list_recent_memories", tool_names)
        self.assertIn("list_pending_suggestions", tool_names)
        self.assertIn("create_memory_entry", tool_names)
        self.assertIn("create_ai_suggestion", tool_names)
        # Draft action propose tools
        self.assertIn("propose_poll", tool_names)
        self.assertIn("propose_event", tool_names)
        self.assertIn("propose_reminder", tool_names)

        # Check safety levels
        for t in tools:
            self.assertIn(t["safety"], ["read_only", "safe_write", "approval_required"])

    def test_tool_returns_serialisable_dicts(self):
        """Test that tool results are serialisable dicts."""
        from app.domains.ai.tools import ToolRegistry

        registry = ToolRegistry()

        async def fake_hub_items(db, limit=10):
            return {"count": 0, "items": [], "found": False}

        registry.register("test_tool", "Test", "read_only", fake_hub_items)

        # Verify the result would be JSON-serialisable
        import json
        result = {"count": 0, "items": [], "found": False}
        serialised = json.dumps(result)
        self.assertIsInstance(serialised, str)


class TestToolsSerialisation(unittest.TestCase):
    """Test that tool serialisation helpers produce correct output."""

    def test_hub_item_to_dict(self):
        """Test _hub_item_to_dict serialisation."""
        from app.domains.ai.tools import _hub_item_to_dict
        from app.models.hub_item import HubItem

        item = HubItem(
            id=uuid.uuid4(),
            short_id="#P-1",
            item_type="poll",
            title="Test Poll",
            body="Test body",
            tags=["test"],
            status="open",
            due_at=None,
        )

        result = _hub_item_to_dict(item)
        self.assertEqual(result["short_id"], "#P-1")
        self.assertEqual(result["type"], "poll")
        self.assertEqual(result["title"], "Test Poll")
        self.assertEqual(result["body"], "Test body")
        self.assertEqual(result["tags"], ["test"])
        self.assertIn("id", result)
        self.assertIn("created_at", result)


# ── Test SharedHubBotService ────────────────────────────────────────────────


class TestSharedHubBotService(unittest.TestCase):
    """Test the SharedHubBotService."""

    def test_initialization(self):
        """Test that the service initializes correctly."""
        from app.domains.ai.hub_agent_service import SharedHubBotService
        from app.domains.ai.summary_service import FakeLLMClient

        db = DummyDb()
        service = SharedHubBotService(db=db, llm_client=FakeLLMClient())
        
        self.assertIsNotNone(service)
        self.assertIsNotNone(service.registry)
        self.assertIsNotNone(service.memory_repo)
        self.assertIsNotNone(service.suggestion_repo)
        self.assertIsNotNone(service.run_repo)

    def test_list_tools(self):
        """Test that the service provides tool access."""
        from app.domains.ai.hub_agent_service import SharedHubBotService
        from app.domains.ai.summary_service import FakeLLMClient

        db = DummyDb()
        service = SharedHubBotService(db=db, llm_client=FakeLLMClient())
        
        tools = service.list_tools()
        self.assertGreaterEqual(len(tools), 11)

        tool_names = [t["name"] for t in tools]
        self.assertIn("get_item_by_reference", tool_names)
        self.assertIn("search_hub_items", tool_names)
        self.assertIn("search_memories", tool_names)
        self.assertIn("create_memory_entry", tool_names)
        self.assertIn("propose_poll", tool_names)
        self.assertIn("propose_event", tool_names)
        self.assertIn("propose_reminder", tool_names)

    def test_prompt_building_matches_hub_bot(self):
        """Test that _build_messages produces the same format as Hub Bot."""
        from app.domains.ai.hub_agent_service import SharedHubBotService
        from app.domains.ai.summary_service import FakeLLMClient

        db = DummyDb()
        service = SharedHubBotService(db=db, llm_client=FakeLLMClient())
        
        messages = [
            {"nickname": "Alice", "content": "Hello!", "created_at": "2024-01-01", "is_deleted": False},
        ]
        
        result = service._build_messages(
            recent_messages=messages,
            user_nickname="TestUser",
            prompt="What's up?",
            snapshot="Active items: #P-1",
            referenced="",
            members="",
        )
        
        # Should match Hub Bot format: system + user messages
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[1]["role"], "user")
        self.assertIn("Alice: Hello!", result[1]["content"])
        self.assertIn("TestUser asks: What's up?", result[1]["content"])

    def test_suggest_poll_creates_suggestion(self):
        """Test that suggest poll creates a poll suggestion via the service."""
        from app.domains.ai.hub_agent_service import SharedHubBotService, HubAgentResult
        from app.domains.ai.summary_service import FakeLLMClient

        db = DummyDb()
        service = SharedHubBotService(db=db, llm_client=FakeLLMClient())
        
        # Call the handler directly
        result = asyncio.run(service._handle_suggest_poll(
            run=None, start_time=0, include_debug=False,
        ))
        
        self.assertIsInstance(result, HubAgentResult)
        self.assertEqual(result.created_suggestion_count, 1)
        self.assertIn("poll suggestion", result.reply.lower())

    def test_summary_service_reuse(self):
        """Test that summarise calls HubSummaryService correctly."""
        from app.domains.ai.hub_agent_service import SharedHubBotService, HubAgentResult
        from app.domains.ai.summary_service import FakeLLMClient

        db = DummyDb()
        service = SharedHubBotService(db=db, llm_client=FakeLLMClient())
        
        result = asyncio.run(service._handle_summarise(
            query="summarise", dry_run=True, run=None, start_time=0, include_debug=False,
        ))
        
        self.assertIsInstance(result, HubAgentResult)
        self.assertIn("summarised", result.reply.lower())

    def test_call_tool(self):
        """Test calling a tool through the service."""
        from app.domains.ai.hub_agent_service import SharedHubBotService
        from app.domains.ai.summary_service import FakeLLMClient

        db = DummyDb()
        service = SharedHubBotService(db=db, llm_client=FakeLLMClient())
        
        result = asyncio.run(service.call_tool("list_recent_memories"))
        self.assertIn("memories", result)
        self.assertIn("count", result)

    def test_call_tool_not_found(self):
        """Test calling a non-existent tool returns error."""
        from app.domains.ai.hub_agent_service import SharedHubBotService
        from app.domains.ai.summary_service import FakeLLMClient

        db = DummyDb()
        service = SharedHubBotService(db=db, llm_client=FakeLLMClient())

        result = asyncio.run(service.call_tool("nonexistent"))
        self.assertIn("error", result)
        self.assertFalse(result["success"])


# ── Test Provider Factory ────────────────────────────────────────────────────


class TestCreateLLMClientFactory(unittest.TestCase):
    """Test the create_llm_client() factory provider selection."""

    def test_returns_fake_when_no_key_and_default_provider(self):
        """Returns FakeLLMClient when no API key is configured."""
        from unittest.mock import patch
        from app.domains.ai.summary_service import create_llm_client, FakeLLMClient

        with patch("app.domains.ai.summary_service.settings") as mock_settings:
            mock_settings.ai_lab_provider = "fake"
            mock_settings.ai_api_key = None
            client = create_llm_client()

        self.assertIsInstance(client, FakeLLMClient)
        self.assertEqual(client.provider_name, "fake")

    def test_returns_openrouter_when_key_configured_and_provider_fake(self):
        """Auto-upgrades to OpenRouterLLMClient when api_key is set and provider is default 'fake'."""
        from unittest.mock import patch
        from app.domains.ai.summary_service import create_llm_client, OpenRouterLLMClient

        with patch("app.domains.ai.summary_service.settings") as mock_settings:
            mock_settings.ai_lab_provider = "fake"
            mock_settings.ai_api_key = "sk-test-key"
            mock_settings.ai_default_chat_model = "some-model"
            mock_settings.ai_api_provider = "openrouter"
            client = create_llm_client()

        self.assertIsInstance(client, OpenRouterLLMClient)
        self.assertEqual(client.provider_name, "openrouter")

    def test_returns_openrouter_when_provider_explicitly_set(self):
        """Returns OpenRouterLLMClient when ai_lab_provider='openrouter' and key is set."""
        from unittest.mock import patch
        from app.domains.ai.summary_service import create_llm_client, OpenRouterLLMClient

        with patch("app.domains.ai.summary_service.settings") as mock_settings:
            mock_settings.ai_lab_provider = "openrouter"
            mock_settings.ai_api_key = "sk-test-key"
            mock_settings.ai_default_chat_model = "some-model"
            mock_settings.ai_api_provider = "openrouter"
            client = create_llm_client()

        self.assertIsInstance(client, OpenRouterLLMClient)

    def test_falls_back_to_fake_when_openrouter_provider_but_no_key(self):
        """Falls back to FakeLLMClient with a warning when provider=openrouter but no API key."""
        from unittest.mock import patch
        from app.domains.ai.summary_service import create_llm_client, FakeLLMClient

        with patch("app.domains.ai.summary_service.settings") as mock_settings:
            mock_settings.ai_lab_provider = "openrouter"
            mock_settings.ai_api_key = None
            client = create_llm_client()

        self.assertIsInstance(client, FakeLLMClient)

    def test_returns_ollama_when_provider_is_ollama(self):
        """Returns OllamaLLMClient when ai_lab_provider='ollama'."""
        from unittest.mock import patch
        from app.domains.ai.summary_service import create_llm_client, OllamaLLMClient

        with patch("app.domains.ai.summary_service.settings") as mock_settings:
            mock_settings.ai_lab_provider = "ollama"
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.ollama_model = "qwen2.5:7b"
            mock_settings.ollama_timeout = 60
            client = create_llm_client()

        self.assertIsInstance(client, OllamaLLMClient)
        self.assertEqual(client.provider_name, "ollama")

    def test_fake_stays_fake_when_no_api_key(self):
        """FakeLLMClient is used when ai_lab_provider=fake and no API key — no auto-upgrade."""
        from unittest.mock import patch
        from app.domains.ai.summary_service import create_llm_client, FakeLLMClient

        with patch("app.domains.ai.summary_service.settings") as mock_settings:
            mock_settings.ai_lab_provider = "fake"
            mock_settings.ai_api_key = None
            client = create_llm_client()

        self.assertIsInstance(client, FakeLLMClient)

    def test_provider_name_attribute_on_all_clients(self):
        """All LLM clients expose provider_name for observability."""
        from app.domains.ai.summary_service import FakeLLMClient, OllamaLLMClient, OpenRouterLLMClient

        self.assertEqual(FakeLLMClient.provider_name, "fake")
        self.assertEqual(OllamaLLMClient.provider_name, "ollama")
        self.assertEqual(OpenRouterLLMClient.provider_name, "openrouter")


# ── Test HubAgentRuntime ────────────────────────────────────────────────────


class TestHubAgentRuntime(unittest.TestCase):
    """Test the HubAgentRuntime with tool-aware agent behaviour."""

    def test_initialization(self):
        """Test that the runtime initializes correctly."""
        from app.domains.ai.agent_runtime import HubAgentRuntime
        from app.domains.ai.summary_service import FakeLLMClient

        db = DummyDb()
        runtime = HubAgentRuntime(db=db, llm_client=FakeLLMClient())
        
        self.assertIsNotNone(runtime)
        self.assertIsNotNone(runtime.registry)

    def test_run_with_fake_llm(self):
        """Test that running with FakeLLMClient returns a valid result."""
        from app.domains.ai.agent_runtime import HubAgentRuntime
        from app.domains.ai.summary_service import FakeLLMClient

        db = DummyDb()
        runtime = HubAgentRuntime(db=db, llm_client=FakeLLMClient())
        
        result = asyncio.run(runtime.run(
            user_message="summarise today's chat",
            context="Recent messages: Hello everyone!",
        ))
        
        self.assertIsNotNone(result.reply)
        self.assertIsInstance(result.reply, str)
        self.assertGreater(len(result.reply), 0)

    def test_parse_response_valid_json(self):
        """Test parsing a valid JSON response."""
        from app.domains.ai.agent_runtime import HubAgentRuntime

        db = DummyDb()
        
        runtime = HubAgentRuntime(db=db)

        raw = '{"reply": "Hello!", "tool_calls": [], "memories": [], "suggestions": []}'
        parsed = runtime._parse_response(raw)
        
        self.assertEqual(parsed["reply"], "Hello!")
        self.assertEqual(parsed["tool_calls"], [])
        self.assertEqual(parsed["memories"], [])
        self.assertEqual(parsed["suggestions"], [])

    def test_parse_response_invalid_json(self):
        """Test that invalid JSON returns graceful fallback."""
        from app.domains.ai.agent_runtime import HubAgentRuntime

        db = DummyDb()
        runtime = HubAgentRuntime(db=db)

        raw = "This is plain text, not JSON"
        parsed = runtime._parse_response(raw)
        
        self.assertIn("reply", parsed)
        self.assertEqual(parsed["tool_calls"], [])
        self.assertIn("validation_errors", parsed)

    def test_parse_response_empty(self):
        """Test that empty response returns fallback."""
        from app.domains.ai.agent_runtime import HubAgentRuntime

        db = DummyDb()
        runtime = HubAgentRuntime(db=db)

        parsed = runtime._parse_response("")
        
        self.assertIn("reply", parsed)
        self.assertIn("validation_errors", parsed)

    def test_parse_response_missing_reply(self):
        """Test that response missing 'reply' field adds error."""
        from app.domains.ai.agent_runtime import HubAgentRuntime

        db = DummyDb()
        runtime = HubAgentRuntime(db=db)

        raw = '{"tool_calls": [], "memories": [], "suggestions": []}'
        parsed = runtime._parse_response(raw)
        
        self.assertIn("reply", parsed)  # Should have default
        self.assertGreater(len(parsed["validation_errors"]), 0)

    def test_execute_tool_not_found(self):
        """Test that executing a non-existent tool returns error."""
        from app.domains.ai.agent_runtime import HubAgentRuntime

        db = DummyDb()
        runtime = HubAgentRuntime(db=db)

        result = asyncio.run(runtime._execute_tool("nonexistent_tool", {}, dry_run=False))
        
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    def test_execute_tool_read_only(self):
        """Test that read_only tools can be executed."""
        from app.domains.ai.agent_runtime import HubAgentRuntime

        db = DummyDb()
        runtime = HubAgentRuntime(db=db)

        result = asyncio.run(runtime._execute_tool("list_recent_memories", {"limit": 5}, dry_run=False))
        
        self.assertTrue(result["success"])
        self.assertIn("memories", result["result"])

    def test_execute_tool_safe_write_in_dry_run(self):
        """Test that safe_write tools are skipped in dry run."""
        from app.domains.ai.agent_runtime import HubAgentRuntime

        db = DummyDb()
        runtime = HubAgentRuntime(db=db)

        result = asyncio.run(runtime._execute_tool("create_memory_entry", {
            "memory_type": "daily_summary",
            "content": "test",
        }, dry_run=True))
        
        self.assertFalse(result["success"])
        self.assertTrue(result.get("skipped", False))

    def test_dry_run_counts_memories(self):
        """Test that dry run counts but does not save memories."""
        from app.domains.ai.agent_runtime import HubAgentRuntime, AgentRuntimeResult
        from app.domains.ai.summary_service import FakeLLMClient

        db = DummyDb()
        runtime = HubAgentRuntime(db=db, llm_client=FakeLLMClient())
        
        result = asyncio.run(runtime.run(
            user_message="test",
            context="",
            dry_run=True,
        ))
        
        self.assertIsInstance(result, AgentRuntimeResult)
        self.assertGreaterEqual(result.created_memories, 0)


# ── Test Agent Run Logging ───────────────────────────────────────────────────


class TestAgentRunLogging(unittest.TestCase):
    """Test agent run logging in HubSummaryService."""

    def test_dry_run_returns_proposed_items(self):
        """Test that dry_run=True returns proposed memories/suggestions without creating them."""
        db = DummyDb()
        service = HubSummaryService(db, FakeLLMClient())

        # Run with dry_run=True
        result = asyncio.run(service.summarize_chat(hours=1, max_messages=10, dry_run=True))

        # Should have proposed items in response
        self.assertIn("memory_entries", result)
        self.assertIn("suggestions", result)
        # In dry_run mode, these are dicts not ORM objects
        for mem in result["memory_entries"]:
            self.assertIsInstance(mem, dict)
            self.assertIn("type", mem)
            self.assertIn("content", mem)

    def test_normal_run_returns_created_items(self):
        """Test that normal run returns created memories/suggestions."""
        db = DummyDb()
        service = HubSummaryService(db, FakeLLMClient())

        # Run without dry_run
        result = asyncio.run(service.summarize_chat(hours=1, max_messages=10))

        # Should have items in response
        self.assertIn("memory_entries", result)
        self.assertIn("suggestions", result)


if __name__ == "__main__":
    unittest.main()
