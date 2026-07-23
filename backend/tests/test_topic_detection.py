import asyncio
import importlib.util
import json
import os
import tempfile
import types
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

os.environ["DEBUG"] = "false"

from app.domains.topic_detection.repository import (
    TopicDetectionRepository,
    TopicDraft,
    TopicDraftSegment,
    TopicEmbeddingBatch,
    participant_canonical_name,
    parse_vector_text,
)
from app.domains.topic_detection.refinement_io import (
    NameNormalizer,
    build_refinement_job,
    parse_import_record,
    parse_redaction,
    redact_text,
    source_hash_from_job,
)
from app.domains.topic_detection.refinement import (
    OpenRouterTopicRefinementClient,
    TopicRefinementService,
    create_topic_refinement_client,
    validate_refinement,
)
from app.domains.topic_detection.service import (
    TopicDetectionService,
    cosine_similarity,
    placeholder_label,
)
from app.domains.topic_detection import worker
from app.models.chat_topic import ChatTopicParticipant

ROOM = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
LOCAL_REFINER_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../tools/topic_refinement/refine_topics_local.py")
)


def _settings(**overrides):
    base = dict(
        ai_topic_detection_enabled=True,
        ai_topic_similarity_threshold=0.62,
        ai_topic_min_cluster_batches=2,
        ai_topic_max_batches_per_run=1000,
        ai_topic_hard_gap_minutes=120,
        ai_topic_soft_gap_minutes=30,
        ai_topic_max_topic_duration_hours=6,
        ai_topic_detection_version="v2-semantic-time-cluster",
        ai_topic_llm_refinement_enabled=False,
        ai_topic_llm_provider="fake",
        ai_topic_llm_model="fake",
        ai_topic_llm_max_segments=8,
        ai_topic_llm_max_excerpt_chars=500,
        ai_api_key=None,
        ai_default_chat_model="default-model",
        ollama_base_url="http://ollama:11434",
        ollama_model="ollama-model",
        ollama_timeout=60,
        ai_embedding_model="fake-model",
        ai_embedding_provider="fake",
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _batch(idx, vector, text, created_at=None):
    start = created_at or datetime(2026, 6, 1, 12, 0, 0) + timedelta(minutes=idx)
    return TopicEmbeddingBatch(
        source_id=f"{ROOM}:{idx}-{idx}",
        room_id=ROOM,
        message_start_id=idx,
        message_end_id=idx,
        embedding=vector,
        content_preview=text,
        first_message_at=start,
        last_message_at=start + timedelta(minutes=1),
    )


class FakeRepo:
    def __init__(self, batches, room_settings=None):
        self.batches = batches
        self.room_settings = room_settings
        self.list_embedding_batches = AsyncMock(return_value=batches)
        self.replace_generated_topics = AsyncMock(return_value=0)
        self.count_current_topics = AsyncMock(return_value=0)
        self.get_room_settings = AsyncMock(return_value=room_settings)
        self.upsert_room_settings = AsyncMock()


class TopicDetectionHelpersTest(unittest.TestCase):
    def test_parse_vector_text(self):
        self.assertEqual(parse_vector_text("[0.5,-1,0.25]"), [0.5, -1.0, 0.25])
        self.assertEqual(parse_vector_text([1, 2.5]), [1.0, 2.5])
        self.assertEqual(parse_vector_text(""), [])

    def test_cosine_similarity(self):
        self.assertAlmostEqual(cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1, 0], [0, 1]), 0.0)
        self.assertEqual(cosine_similarity([1], [1, 0]), 0.0)

    def test_placeholder_label_prefers_repeated_terms(self):
        label, keywords = placeholder_label([
            "Benidorm flights and Benidorm hotels",
            "book benidorm flights soon",
        ])
        self.assertTrue(any("benidorm" in keyword for keyword in keywords))
        self.assertTrue(label)
        self.assertLessEqual(len(keywords), 3)

    def test_participant_alias_resolution_prefers_alias_and_avoids_emails(self):
        db = FakeQueryDb([
            FakeQueryResult(rows=[
                ("Small Willy Wray", "Will"),
            ]),
            FakeQueryResult(rows=[
                ("Small Willy Wray", "Bad fallback", "small"),
                ("Techlett", "Luke", "techlett"),
                ("Email User", "person@example.com", "emailuser"),
            ]),
        ])
        repo = TopicDetectionRepository(db)

        aliases = asyncio.run(repo.list_participant_name_aliases(room_id=ROOM))

        self.assertEqual(aliases["Small Willy Wray"], "Will")
        self.assertEqual(aliases["Techlett"], "Luke")
        self.assertEqual(aliases["Email User"], "emailuser")

    def test_participant_canonical_name_prefers_alias_and_avoids_email(self):
        user = types.SimpleNamespace(
            id=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
            nickname="Small Willy Wray",
            display_name="person@example.com",
            username="will",
        )

        self.assertEqual(
            participant_canonical_name(
                user=user,
                display_name="Small Willy Wray",
                aliases={"Small Willy Wray": "Will"},
            ),
            "Will",
        )
        self.assertEqual(
            participant_canonical_name(user=user, display_name="Email User", aliases={}),
            "will",
        )

    def test_participant_extraction_from_topic_segments(self):
        message_one = types.SimpleNamespace(
            is_deleted=False,
            is_imported=False,
            created_at=datetime(2026, 1, 1, 10, 0),
        )
        message_two = types.SimpleNamespace(
            is_deleted=False,
            is_imported=False,
            created_at=datetime(2026, 1, 1, 10, 1),
        )
        will = types.SimpleNamespace(
            id=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
            nickname="Small Willy Wray",
            display_name="person@example.com",
            username="will",
        )
        luke = types.SimpleNamespace(
            id=uuid.UUID("eeeeeeee-0000-0000-0000-000000000005"),
            nickname="Techlett",
            display_name="Luke",
            username="techlett",
        )
        fake_message_repo = types.SimpleNamespace(
            get_messages_in_id_range=AsyncMock(return_value=[
                (message_one, will, None, None, None, None),
                (message_two, luke, None, None, None, None),
            ])
        )
        repo = TopicDetectionRepository(db=object())

        with unittest.mock.patch(
            "app.domains.messages.repository.MessageRepository",
            return_value=fake_message_repo,
        ):
            participants = asyncio.run(repo._participant_drafts_for_topic(
                room_id=ROOM,
                segments=[
                    TopicDraftSegment(
                        embedding_source_id="batch-1",
                        message_start_id=1,
                        message_end_id=2,
                        score=0.9,
                        excerpt=None,
                        started_at=message_one.created_at,
                        ended_at=message_two.created_at,
                    )
                ],
                aliases={"Small Willy Wray": "Will"},
            ))

        names = {participant.canonical_name: participant for participant in participants}
        self.assertEqual(names["Will"].message_count, 1)
        self.assertEqual(names["Will"].segment_count, 1)
        self.assertEqual(names["Luke"].message_count, 1)
        self.assertNotIn("person@example.com", names)

    def test_imported_sender_name_wins_over_linked_room_nickname(self):
        message = types.SimpleNamespace(
            is_deleted=False,
            is_imported=True,
            created_at=datetime(2026, 1, 1, 10, 0),
        )
        linked_user = types.SimpleNamespace(
            id=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
            nickname="Small Willy Wray",
            display_name="person@example.com",
            username="htwray",
        )
        imported_identity = types.SimpleNamespace(source_display_name="Harrison Wray")
        fake_message_repo = types.SimpleNamespace(
            get_messages_in_id_range=AsyncMock(return_value=[
                (message, None, linked_user, None, None, None, imported_identity),
            ])
        )
        repo = TopicDetectionRepository(db=object())

        with unittest.mock.patch(
            "app.domains.messages.repository.MessageRepository",
            return_value=fake_message_repo,
        ):
            participants = asyncio.run(repo._participant_drafts_for_topic(
                room_id=ROOM,
                segments=[
                    TopicDraftSegment(
                        embedding_source_id="batch-1",
                        message_start_id=1,
                        message_end_id=1,
                        score=0.9,
                        excerpt=None,
                        started_at=message.created_at,
                        ended_at=message.created_at,
                    )
                ],
                aliases={},
            ))

        self.assertEqual(len(participants), 1)
        self.assertEqual(participants[0].canonical_name, "Harrison Wray")
        self.assertEqual(participants[0].display_name, "Harrison Wray")
        self.assertNotEqual(participants[0].canonical_name, "htwray")


class TopicDetectionServiceTest(unittest.TestCase):
    def test_disabled_detection_returns_without_scanning(self):
        repo = FakeRepo([])
        service = TopicDetectionService(
            db=object(),
            settings=_settings(ai_topic_detection_enabled=False),
            repository=repo,
        )
        result = asyncio.run(service.generate_topics(room_id=ROOM))

        self.assertEqual(result["status"], "disabled")
        repo.list_embedding_batches.assert_not_called()

    def test_single_batch_cluster_is_ignored(self):
        service = TopicDetectionService(
            db=object(),
            settings=_settings(),
            repository=FakeRepo([]),
        )
        drafts = service.detect_topic_drafts([
            _batch(1, [1.0, 0.0], "camping weekend")
        ])
        self.assertEqual(drafts, [])

    def test_related_batches_create_one_semantic_cluster(self):
        service = TopicDetectionService(
            db=object(),
            settings=_settings(ai_topic_similarity_threshold=0.6),
            repository=FakeRepo([]),
        )
        drafts = service.detect_topic_drafts([
            _batch(1, [1.0, 0.0], "Benidorm flights"),
            _batch(2, [0.95, 0.05], "Benidorm hotels"),
            _batch(3, [0.0, 1.0], "tax receipts"),
        ])

        self.assertEqual(len(drafts), 1)
        topic = drafts[0]
        self.assertEqual(topic.batch_count, 2)
        self.assertEqual(topic.message_start_id, 1)
        self.assertEqual(topic.message_end_id, 2)
        self.assertEqual(topic.topic_date.isoformat(), "2026-06-01")
        self.assertGreaterEqual(topic.confidence, 0.6)

    def test_unrelated_content_splits_clusters(self):
        service = TopicDetectionService(
            db=object(),
            settings=_settings(ai_topic_similarity_threshold=0.8),
            repository=FakeRepo([]),
        )
        drafts = service.detect_topic_drafts([
            _batch(1, [1.0, 0.0], "camping tents"),
            _batch(2, [0.99, 0.01], "camping stove"),
            _batch(3, [0.0, 1.0], "birthday dinner"),
            _batch(4, [0.01, 0.99], "birthday restaurant"),
        ])

        self.assertEqual(len(drafts), 2)
        self.assertEqual([draft.batch_count for draft in drafts], [2, 2])

    def test_generate_topics_replaces_with_room_model_version_and_date_range(self):
        date_from = datetime(2026, 6, 1)
        date_to = datetime(2026, 6, 2)
        batches = [
            _batch(1, [1.0, 0.0], "camping tents"),
            _batch(2, [0.99, 0.01], "camping stove"),
        ]
        repo = FakeRepo(batches)
        repo.replace_generated_topics.return_value = 1
        service = TopicDetectionService(db=object(), settings=_settings(), repository=repo)

        result = asyncio.run(
            service.generate_topics(
                room_id=ROOM,
                date_from=date_from,
                date_to=date_to,
                limit_batches=50,
            )
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["topics_detected"], 1)
        self.assertEqual(result["topics_written"], 1)
        repo.list_embedding_batches.assert_awaited_once_with(
            room_id=ROOM,
            model_name="fake-model",
            model_version="fake",
            date_from=date_from,
            date_to=date_to,
            limit=50,
        )
        kwargs = repo.replace_generated_topics.await_args.kwargs
        self.assertEqual(kwargs["room_id"], ROOM)
        self.assertEqual(kwargs["model_name"], "fake-model")
        self.assertEqual(kwargs["model_version"], "fake")
        self.assertEqual(kwargs["detection_version"], "v2-semantic-time-cluster")
        self.assertEqual(kwargs["date_from"], date_from)
        self.assertEqual(kwargs["date_to"], date_to)

    def test_generate_topics_sets_requested_topic_date_for_day_window(self):
        date_from = datetime(2020, 7, 13)
        date_to = datetime(2020, 7, 14)
        repo = FakeRepo([
            _batch(1, [1.0, 0.0], "previous evening", datetime(2020, 7, 12, 23, 30)),
            _batch(2, [1.0, 0.0], "monday lunch", datetime(2020, 7, 13, 12, 0)),
            _batch(3, [0.99, 0.01], "monday dinner", datetime(2020, 7, 13, 12, 20)),
        ])
        service = TopicDetectionService(db=object(), settings=_settings(), repository=repo)

        result = asyncio.run(
            service.generate_topics(
                room_id=ROOM,
                date_from=date_from,
                date_to=date_to,
                dry_run=True,
            )
        )

        self.assertEqual(result["topics_detected"], 1)
        self.assertEqual(result["topics"][0]["topic_date"], "2020-07-13")
        self.assertEqual(result["topics"][0]["batch_count"], 2)

    def test_dry_run_does_not_replace_topics(self):
        repo = FakeRepo([
            _batch(1, [1.0, 0.0], "camping tents"),
            _batch(2, [0.99, 0.01], "camping stove"),
        ])
        service = TopicDetectionService(db=object(), settings=_settings(), repository=repo)
        result = asyncio.run(service.generate_topics(room_id=ROOM, dry_run=True))

        self.assertEqual(result["topics_detected"], 1)
        self.assertEqual(result["topics_written"], 0)
        repo.replace_generated_topics.assert_not_called()

    def test_missing_embeddings_returns_embeddings_required(self):
        repo = FakeRepo([])
        service = TopicDetectionService(db=object(), settings=_settings(), repository=repo)
        result = asyncio.run(service.generate_topics(room_id=ROOM))

        self.assertEqual(result["status"], "embeddings_required")
        self.assertEqual(result["batches_scanned"], 0)
        self.assertEqual(result["topics_detected"], 0)
        repo.replace_generated_topics.assert_not_called()

    def test_hard_gap_prevents_merging_semantically_similar_batches(self):
        service = TopicDetectionService(
            db=object(),
            settings=_settings(ai_topic_hard_gap_minutes=120),
            repository=FakeRepo([]),
        )
        drafts = service.detect_topic_drafts([
            _batch(1, [1.0, 0.0], "football plans", datetime(2026, 6, 1, 9, 0)),
            _batch(2, [0.99, 0.01], "football pub", datetime(2026, 6, 1, 9, 10)),
            _batch(3, [1.0, 0.0], "football plans again", datetime(2026, 6, 1, 13, 0)),
            _batch(4, [0.99, 0.01], "football pub again", datetime(2026, 6, 1, 13, 10)),
        ])

        self.assertEqual(len(drafts), 2)
        self.assertEqual([draft.batch_count for draft in drafts], [2, 2])

    def test_max_duration_prevents_many_hour_topics(self):
        service = TopicDetectionService(
            db=object(),
            settings=_settings(ai_topic_max_topic_duration_hours=2, ai_topic_hard_gap_minutes=120),
            repository=FakeRepo([]),
        )
        drafts = service.detect_topic_drafts([
            _batch(1, [1.0, 0.0], "football plans", datetime(2026, 6, 1, 9, 0)),
            _batch(2, [0.99, 0.01], "football pub", datetime(2026, 6, 1, 9, 10)),
            _batch(3, [1.0, 0.0], "football later", datetime(2026, 6, 1, 11, 30)),
            _batch(4, [0.99, 0.01], "football later pub", datetime(2026, 6, 1, 11, 40)),
        ])

        self.assertEqual(len(drafts), 2)
        self.assertEqual([draft.batch_count for draft in drafts], [2, 2])

    def test_similarity_threshold_override_changes_clustering(self):
        service = TopicDetectionService(
            db=object(),
            settings=_settings(ai_topic_similarity_threshold=0.6),
            repository=FakeRepo([]),
        )
        batches = [
            _batch(1, [1.0, 0.0], "football plans", datetime(2026, 6, 1, 9, 0)),
            _batch(2, [0.75, 0.25], "football pub", datetime(2026, 6, 1, 9, 10)),
        ]

        self.assertEqual(len(service.detect_topic_drafts(batches, similarity_threshold=0.6)), 1)
        self.assertEqual(len(service.detect_topic_drafts(batches, similarity_threshold=0.98)), 0)

    def test_room_specific_setting_beats_global_default(self):
        repo = FakeRepo([], room_settings=types.SimpleNamespace(
            similarity_threshold=0.85,
            hard_gap_minutes=None,
            soft_gap_minutes=None,
            max_topic_duration_hours=None,
        ))
        service = TopicDetectionService(
            db=object(),
            settings=_settings(ai_topic_similarity_threshold=0.62),
            repository=repo,
        )

        config = asyncio.run(service.effective_config(room_id=ROOM))

        self.assertEqual(config.similarity_threshold, 0.85)
        self.assertEqual(config.hard_gap_minutes, 120)

    def test_cli_override_beats_room_specific_setting(self):
        repo = FakeRepo([], room_settings=types.SimpleNamespace(
            similarity_threshold=0.85,
            hard_gap_minutes=120,
            soft_gap_minutes=30,
            max_topic_duration_hours=6,
        ))
        service = TopicDetectionService(
            db=object(),
            settings=_settings(ai_topic_similarity_threshold=0.62),
            repository=repo,
        )

        config = asyncio.run(service.effective_config(room_id=ROOM, similarity_threshold=0.8))

        self.assertEqual(config.similarity_threshold, 0.8)

    def test_unset_room_setting_falls_back_to_global_default(self):
        service = TopicDetectionService(
            db=object(),
            settings=_settings(ai_topic_similarity_threshold=0.62),
            repository=FakeRepo([], room_settings=None),
        )

        config = asyncio.run(service.effective_config(room_id=ROOM))

        self.assertEqual(config.similarity_threshold, 0.62)

    def test_generate_topics_includes_effective_config(self):
        repo = FakeRepo([
            _batch(1, [1.0, 0.0], "camping tents"),
            _batch(2, [0.99, 0.01], "camping stove"),
        ], room_settings=types.SimpleNamespace(
            similarity_threshold=0.85,
            hard_gap_minutes=None,
            soft_gap_minutes=None,
            max_topic_duration_hours=None,
        ))
        service = TopicDetectionService(db=object(), settings=_settings(), repository=repo)
        result = asyncio.run(service.generate_topics(room_id=ROOM, dry_run=True))

        self.assertEqual(result["effective_config"]["similarity_threshold"], 0.85)
        self.assertEqual(result["detection_version"], "v2-semantic-time-cluster")


class TopicRefinementServiceTest(unittest.TestCase):
    def test_refinement_disabled_by_default(self):
        repo = FakeRefinementRepo([_topic_obj()])
        service = TopicRefinementService(
            db=object(),
            settings=_settings(ai_topic_llm_refinement_enabled=False),
            repository=repo,
            client=FakeRefinementClient({"title": "Pub Plans"}),
        )

        result = asyncio.run(service.refine_date(
            room_id=ROOM,
            date_value=worker._parse_day("2026-01-01"),
            dry_run=True,
        ))

        self.assertEqual(result["status"], "disabled")
        repo.list_topics_for_refinement.assert_not_called()

    def test_refinement_dry_run_writes_nothing(self):
        topic = _topic_obj()
        repo = FakeRefinementRepo([topic])
        service = TopicRefinementService(
            db=object(),
            settings=_settings(ai_topic_llm_refinement_enabled=True),
            repository=repo,
            client=FakeRefinementClient({
                "title": "Pub Plans",
                "summary": "The group discusses pub plans.",
                "tags": ["pub", "plans"],
                "topic_type": "planning",
                "confidence": 0.8,
            }),
        )

        result = asyncio.run(service.refine_date(
            room_id=ROOM,
            date_value=worker._parse_day("2026-01-01"),
            dry_run=True,
        ))

        self.assertEqual(result["topics_refined"], 1)
        self.assertEqual(result["refinements"][0]["display_label"], "Pub Plans")
        repo.apply_refinement.assert_not_called()

    def test_valid_llm_json_updates_topic_fields(self):
        topic = _topic_obj()
        repo = FakeRefinementRepo([topic])
        service = TopicRefinementService(
            db=object(),
            settings=_settings(ai_topic_llm_refinement_enabled=True),
            repository=repo,
            client=FakeRefinementClient({
                "title": "Pub Plans",
                "summary": "The group discusses pub plans.",
                "tags": ["pub", "plans"],
                "topic_type": "planning",
                "confidence": 0.82,
            }),
        )

        result = asyncio.run(service.refine_date(
            room_id=ROOM,
            date_value=worker._parse_day("2026-01-01"),
            dry_run=False,
        ))

        self.assertEqual(result["topics_refined"], 1)
        repo.apply_refinement.assert_awaited_once()
        kwargs = repo.apply_refinement.await_args.kwargs
        self.assertEqual(kwargs["title"], "Pub Plans")
        self.assertEqual(kwargs["topic_type"], "planning")
        self.assertEqual(kwargs["confidence"], 0.82)

    def test_invalid_llm_json_leaves_topic_unchanged(self):
        repo = FakeRefinementRepo([_topic_obj()])
        service = TopicRefinementService(
            db=object(),
            settings=_settings(ai_topic_llm_refinement_enabled=True),
            repository=repo,
            client=FakeRefinementClient(ValueError("bad json")),
        )

        result = asyncio.run(service.refine_date(
            room_id=ROOM,
            date_value=worker._parse_day("2026-01-01"),
            dry_run=False,
        ))

        self.assertEqual(result["topics_refined"], 0)
        self.assertEqual(result["topics_failed"], 1)
        repo.apply_refinement.assert_not_called()

    def test_force_refine_and_topic_id_limit_scope(self):
        topic_id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
        repo = FakeRefinementRepo([_topic_obj(topic_id=topic_id)])
        service = TopicRefinementService(
            db=object(),
            settings=_settings(ai_topic_llm_refinement_enabled=True),
            repository=repo,
            client=FakeRefinementClient({"title": "General chat"}),
        )

        asyncio.run(service.refine_date(
            room_id=ROOM,
            date_value=worker._parse_day("2026-01-01"),
            topic_id=topic_id,
            force=True,
            limit_topics=1,
            dry_run=True,
        ))

        kwargs = repo.list_topics_for_refinement.await_args.kwargs
        self.assertEqual(kwargs["topic_id"], topic_id)
        self.assertTrue(kwargs["force"])
        self.assertEqual(kwargs["limit"], 1)

    def test_openrouter_provider_selection(self):
        client = create_topic_refinement_client(_settings(
            ai_topic_llm_provider="openrouter",
            ai_topic_llm_model="openai/gpt-4.1-mini",
            ai_api_key="test-key",
        ))

        self.assertIsInstance(client, OpenRouterTopicRefinementClient)
        self.assertEqual(client.model, "openai/gpt-4.1-mini")

    def test_prompt_contains_capped_excerpts_only(self):
        long_excerpt = "A" * 200
        topic = _topic_obj()
        topic.segments = [
            types.SimpleNamespace(
                excerpt=f"[01 Jan 10:00] Ad: {long_excerpt}",
                started_at=datetime(2026, 1, 1, 10, 0),
                ended_at=datetime(2026, 1, 1, 10, 1),
                message_start_id=1,
            ),
            types.SimpleNamespace(
                excerpt="[01 Jan 10:02] Bob: second segment",
                started_at=datetime(2026, 1, 1, 10, 2),
                ended_at=datetime(2026, 1, 1, 10, 3),
                message_start_id=2,
            ),
        ]
        client = FakeRefinementClient({"title": "General chat"})
        service = TopicRefinementService(
            db=object(),
            settings=_settings(
                ai_topic_llm_refinement_enabled=True,
                ai_topic_llm_max_segments=1,
                ai_topic_llm_max_excerpt_chars=25,
            ),
            repository=FakeRefinementRepo([topic]),
            client=client,
        )

        asyncio.run(service.refine_date(
            room_id=ROOM,
            date_value=worker._parse_day("2026-01-01"),
            dry_run=True,
        ))

        self.assertIn("Participants seen in excerpts: Ad", client.prompts[0])
        self.assertIn("A" * 10, client.prompts[0])
        self.assertNotIn("second segment", client.prompts[0])

    def test_validate_refinement_sanitises_invalid_topic_type(self):
        result = validate_refinement({
            "title": "  A title  ",
            "summary": " A summary ",
            "tags": ["Tag One", "Tag One", "weird/tag"],
            "topic_type": "not-real",
            "confidence": 2,
        })

        self.assertEqual(result.title, "A title")
        self.assertEqual(result.tags, ["tag_one", "weird_tag"])
        self.assertEqual(result.topic_type, "unknown")
        self.assertEqual(result.confidence, 1.0)

    def test_validate_refinement_accepts_timeline_topic_types(self):
        for topic_type in ("sport", "food_drink", "relationship", "memory", "unknown"):
            result = validate_refinement({
                "title": "A title",
                "summary": "A summary",
                "tags": [],
                "topic_type": topic_type,
                "confidence": 0.5,
            })

            self.assertEqual(result.topic_type, topic_type)

    def test_validate_refinement_filters_generic_tags_and_applies_type_overrides(self):
        result = validate_refinement({
            "title": "A title",
            "summary": "A summary",
            "tags": ["discussion", "Gaming", "chat", "xbox"],
            "topic_type": "general_chat",
            "confidence": 0.5,
        })

        self.assertEqual(result.tags, ["gaming", "xbox"])
        self.assertEqual(result.topic_type, "gaming")

        result = validate_refinement({
            "title": "A title",
            "summary": "A summary",
            "tags": ["football", "match"],
            "topic_type": "unknown",
            "confidence": 0.5,
        })

        self.assertEqual(result.topic_type, "sport")

    def test_validate_refinement_does_not_override_specific_topic_type(self):
        result = validate_refinement({
            "title": "A title",
            "summary": "A summary",
            "tags": ["pub", "plans"],
            "topic_type": "planning",
            "confidence": 0.5,
        })

        self.assertEqual(result.topic_type, "planning")

    def test_validate_refinement_demotes_weak_work_classification(self):
        result = validate_refinement({
            "title": "Discussing stats and dates",
            "summary": "Chat about upcoming deadlines and statistics.",
            "tags": ["general_chat", "work"],
            "topic_type": "work",
            "confidence": 0.7,
        })

        self.assertEqual(result.topic_type, "general_chat")
        self.assertNotIn("work", result.tags)

        result = validate_refinement({
            "title": "Talking about shifts",
            "summary": "The group discuss job shifts and workplace plans.",
            "tags": ["work"],
            "topic_type": "work",
            "confidence": 0.7,
        })

        self.assertEqual(result.topic_type, "work")
        self.assertIn("work", result.tags)

    def test_validate_refinement_requires_title_and_summary(self):
        with self.assertRaises(ValueError):
            validate_refinement({
                "title": "",
                "summary": "A summary",
                "tags": [],
                "topic_type": "general_chat",
                "confidence": 0.5,
            })
        with self.assertRaises(ValueError):
            validate_refinement({
                "title": "A title",
                "summary": "",
                "tags": [],
                "topic_type": "general_chat",
                "confidence": 0.5,
            })

    def test_refinement_job_redacts_and_includes_source_hash(self):
        topic = _topic_obj()
        topic.segments[0].excerpt = "[01 Jan 10:00] Ad: see https://example.com or ad@example.com 07123 456789"

        job = build_refinement_job(
            topic=topic,
            room_id=ROOM,
            room_slug="nips",
            export_id=uuid.UUID("eeeeeeee-0000-0000-0000-000000000005"),
            max_segments=8,
            max_excerpt_chars=500,
            redaction=parse_redaction(None),
        )

        excerpt = job["segments"][0]["excerpt"]
        self.assertIn("[url]", excerpt)
        self.assertIn("[email]", excerpt)
        self.assertIn("[phone]", excerpt)
        self.assertTrue(job["source_hash"].startswith("sha256:"))
        self.assertEqual(job["source_hash"], source_hash_from_job(job))

    def test_redact_names_is_optional(self):
        text = "[01 Jan 10:00] Ad: hello"

        self.assertIn("Ad:", redact_text(text, ["urls", "emails", "phones"]))
        self.assertIn("[name]:", redact_text(text, ["names"]))

    def test_name_normalizer_canonical_display_and_anonymous_modes(self):
        text = "[01 Jan 10:00] Small Willy Wray: hello Techlett"

        canonical = NameNormalizer(mode="canonical", aliases={
            "Small Willy Wray": "Will",
            "Techlett": "Luke",
        }).normalize_excerpt(text)
        display = NameNormalizer(mode="display", aliases={
            "Small Willy Wray": "Will",
        }).normalize_excerpt(text)
        anonymous = NameNormalizer(mode="anonymous").normalize_excerpt(text)

        self.assertEqual(canonical, "[01 Jan 10:00] Will: hello Luke")
        self.assertEqual(display, text)
        self.assertEqual(anonymous, "[01 Jan 10:00] Participant 1: hello Techlett")

    def test_name_normalizer_falls_back_when_no_canonical_exists(self):
        text = "[01 Jan 10:00] Unknown Friend: hello"

        canonical = NameNormalizer(mode="canonical", aliases={}).normalize_excerpt(text)

        self.assertEqual(canonical, text)


class TopicDetectionWorkerTest(unittest.TestCase):
    def test_january_date_range_is_inclusive(self):
        windows = worker._date_windows(
            date_from=worker._parse_day("2026-01-01"),
            date_to=worker._parse_day("2026-01-31"),
        )

        self.assertEqual(len(windows), 31)
        self.assertEqual(windows[0][0].isoformat(), "2026-01-01")
        self.assertEqual(windows[0][1].isoformat(), "2026-01-01T00:00:00+00:00")
        self.assertEqual(windows[0][2].isoformat(), "2026-01-02T00:00:00+00:00")
        self.assertEqual(windows[-1][0].isoformat(), "2026-01-31")
        self.assertEqual(windows[-1][2].isoformat(), "2026-02-01T00:00:00+00:00")

    def test_single_date_window(self):
        windows = worker._date_windows(date_value=worker._parse_day("2026-01-01"))

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0][0].isoformat(), "2026-01-01")
        self.assertEqual(windows[0][1].isoformat(), "2026-01-01T00:00:00+00:00")
        self.assertEqual(windows[0][2].isoformat(), "2026-01-02T00:00:00+00:00")

    def test_worker_returns_empty_when_disabled(self):
        with unittest.mock.patch.object(
            worker,
            "get_settings",
            return_value=_settings(ai_topic_detection_enabled=False),
        ):
            result = asyncio.run(worker.run_once(room_id=ROOM))

        self.assertEqual(result, [])

    def test_worker_requires_room_or_all_rooms(self):
        async def _go():
            db = object()
            with self.assertRaises(ValueError):
                await worker._resolve_room_ids(db, room_id=None, all_rooms=False)

        asyncio.run(_go())

    def test_resolve_room_by_slug(self):
        db = FakeQueryDb([
            FakeQueryResult(rows=[(ROOM, "nips-and-crips", "nips and crips")])
        ])

        rooms = asyncio.run(worker._resolve_rooms(db, room_slug="nips-and-crips"))

        self.assertEqual(rooms[0].id, ROOM)
        self.assertEqual(rooms[0].slug, "nips-and-crips")
        self.assertEqual(rooms[0].name, "nips and crips")

    def test_resolve_room_by_name_requires_unique_match(self):
        db = FakeQueryDb([
            FakeQueryResult(rows=[
                (ROOM, "nips-and-crips", "nips and crips"),
                (uuid.UUID("dddddddd-0000-0000-0000-000000000004"), "duplicate", "nips and crips"),
            ])
        ])

        with self.assertRaises(ValueError) as ctx:
            asyncio.run(worker._resolve_rooms(db, room_name="nips and crips"))

        self.assertIn("Multiple rooms matched", str(ctx.exception))
        self.assertIn("Use --room-id", str(ctx.exception))

    def test_resolve_room_by_slug_fails_clearly_when_missing(self):
        db = FakeQueryDb([FakeQueryResult(rows=[])])

        with self.assertRaises(ValueError) as ctx:
            asyncio.run(worker._resolve_rooms(db, room_slug="nips-and-crips"))

        self.assertIn("No room found for slug", str(ctx.exception))

    def test_list_embedding_dates_outputs_message_batch_dates_for_room(self):
        row_date = datetime(2026, 1, 3).date()
        db = FakeQueryDb([
            FakeQueryResult(rows=[(ROOM, "nips-and-crips", "nips and crips")]),
            FakeQueryResult(mapping_rows=[{
                "embedding_date": row_date,
                "batch_count": 4,
                "first_batch_timestamp": datetime(2026, 1, 3, 10, 0, 0),
                "last_batch_timestamp": datetime(2026, 1, 3, 23, 0, 0),
            }]),
        ])

        with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)):
            rows = asyncio.run(worker.list_embedding_dates(room_slug="nips-and-crips"))

        self.assertEqual(rows, [{
            "room_id": str(ROOM),
            "room_slug": "nips-and-crips",
            "room_name": "nips and crips",
            "date": "2026-01-03",
            "embedding_batch_count": 4,
            "first_batch_timestamp": "2026-01-03T10:00:00",
            "last_batch_timestamp": "2026-01-03T23:00:00",
        }])

    def test_worker_processes_date_range_day_by_day(self):
        db = FakeWorkerDb()
        service = FakeWorkerService()
        with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)), \
                unittest.mock.patch.object(worker, "TopicDetectionService", return_value=service):
            result = asyncio.run(
                worker.run_date_backfill(
                    room_id=ROOM,
                    date_from=worker._parse_day("2026-01-01"),
                    date_to=worker._parse_day("2026-01-02"),
                )
            )

        self.assertEqual([row["date"] for row in result], ["2026-01-01", "2026-01-02"])
        self.assertEqual(len(service.calls), 2)
        self.assertEqual(service.calls[0]["date_from"].isoformat(), "2026-01-01T00:00:00+00:00")
        self.assertEqual(service.calls[0]["date_to"].isoformat(), "2026-01-02T00:00:00+00:00")
        self.assertEqual(service.calls[1]["date_from"].isoformat(), "2026-01-02T00:00:00+00:00")
        self.assertEqual(service.calls[1]["date_to"].isoformat(), "2026-01-03T00:00:00+00:00")
        self.assertEqual(db.commits, 2)
        self.assertEqual(db.rollbacks, 0)

    def test_worker_dry_run_rolls_back_each_day(self):
        db = FakeWorkerDb()
        service = FakeWorkerService()
        with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)), \
                unittest.mock.patch.object(worker, "TopicDetectionService", return_value=service):
            result = asyncio.run(
                worker.run_date_backfill(
                    room_id=ROOM,
                    date_value=worker._parse_day("2026-01-01"),
                    dry_run=True,
                )
            )

        self.assertTrue(result[0]["dry_run"])
        self.assertEqual(service.calls[0]["dry_run"], True)
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)

    def test_worker_passes_similarity_threshold_override(self):
        db = FakeWorkerDb()
        service = FakeWorkerService()
        with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)), \
                unittest.mock.patch.object(worker, "TopicDetectionService", return_value=service):
            asyncio.run(
                worker.run_date_backfill(
                    room_id=ROOM,
                    date_value=worker._parse_day("2026-01-01"),
                    dry_run=True,
                    similarity_threshold=0.85,
                )
            )

        self.assertEqual(service.calls[0]["similarity_threshold"], 0.85)

    def test_worker_passes_gap_overrides(self):
        db = FakeWorkerDb()
        service = FakeWorkerService()
        with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)), \
                unittest.mock.patch.object(worker, "TopicDetectionService", return_value=service):
            asyncio.run(
                worker.run_date_backfill(
                    room_id=ROOM,
                    date_value=worker._parse_day("2026-01-01"),
                    dry_run=True,
                    hard_gap_minutes=90,
                    soft_gap_minutes=15,
                    max_topic_duration_hours=4,
                )
            )

        self.assertEqual(service.calls[0]["hard_gap_minutes"], 90)
        self.assertEqual(service.calls[0]["soft_gap_minutes"], 15)
        self.assertEqual(service.calls[0]["max_topic_duration_hours"], 4)

    def test_printed_date_backfill_payload_contains_topic_summary(self):
        db = FakeWorkerDb()
        service = FakeWorkerService(result={
            "status": "ok",
            "room_id": str(ROOM),
            "topics_detected": 1,
            "topics_written": 0,
            "batches_scanned": 2,
            "dry_run": True,
            "topics": [{"label": "Football Pub", "batch_count": 2}],
        })
        with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)), \
                unittest.mock.patch.object(worker, "TopicDetectionService", return_value=service), \
                unittest.mock.patch("sys.argv", [
                    "worker",
                    "--room-id", str(ROOM),
                    "--date", "2026-01-01",
                    "--dry-run",
                ]), \
                unittest.mock.patch("builtins.print") as printed:
            worker.main()

        payload = json.loads(printed.call_args.args[0])
        self.assertEqual(payload["batches_scanned"], 2)
        self.assertEqual(payload["topics_detected"], 1)
        self.assertEqual(payload["topics"][0]["label"], "Football Pub")

    def test_inspect_date_returns_stored_topic_summaries(self):
        topic = types.SimpleNamespace(
            id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
            label="Football Pub",
            raw_label="Football Pub",
            refined_label="Pub Plans",
            summary="The group discusses pub plans.",
            tags=["pub", "plans"],
            topic_type="planning",
            refinement_model="fake:fake",
            refined_at=datetime(2026, 1, 1, 11, 0),
            confidence=0.8,
            generation_type="semantic_time_cluster",
            label_source="keyword_placeholder",
            topic_date=datetime(2026, 1, 1).date(),
            first_message_at=datetime(2026, 1, 1, 10, 0),
            last_message_at=datetime(2026, 1, 1, 10, 30),
            bucket_start_at=datetime(2026, 1, 1, 10, 0),
            bucket_end_at=datetime(2026, 1, 1, 10, 30),
            batch_count=2,
            segments=[
                types.SimpleNamespace(
                    embedding_source_id="batch-1",
                    message_start_id=10,
                    message_end_id=20,
                    score=0.91,
                    started_at=datetime(2026, 1, 1, 10, 0),
                    ended_at=datetime(2026, 1, 1, 10, 10),
                    excerpt="pub plans",
                )
            ],
            participants=[
                types.SimpleNamespace(
                    id=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
                    topic_id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
                    room_id=ROOM,
                    user_id=uuid.UUID("eeeeeeee-0000-0000-0000-000000000005"),
                    canonical_name="Will",
                    display_name="Small Willy Wray",
                    message_count=5,
                    segment_count=1,
                    first_seen_at=datetime(2026, 1, 1, 10, 0),
                    last_seen_at=datetime(2026, 1, 1, 10, 10),
                )
            ],
        )
        db = FakeQueryDb([
            FakeQueryResult(rows=[(ROOM, "nips", "Nips & Crips")]),
            FakeQueryResult(scalar_rows=[topic]),
        ])

        with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)):
            result = asyncio.run(worker.inspect_date(room_id=ROOM, date_value=worker._parse_day("2026-01-01")))

        self.assertEqual(result["detection_version"], "v2-semantic-time-cluster")
        self.assertEqual(result["topics"][0]["label"], "Football Pub")
        self.assertEqual(result["topics"][0]["display_label"], "Pub Plans")
        self.assertEqual(result["topics"][0]["summary"], "The group discusses pub plans.")
        self.assertEqual(result["topics"][0]["tags"], ["pub", "plans"])
        self.assertEqual(result["topics"][0]["participant_count"], 1)
        self.assertEqual(result["topics"][0]["participant_names"], ["Will"])
        self.assertEqual(result["topics"][0]["participants"][0]["display_name"], "Small Willy Wray")
        self.assertEqual(result["topics"][0]["segments"][0]["message_start_id"], 10)

    def test_inspect_date_allows_detection_version_filter(self):
        db = FakeQueryDb([
            FakeQueryResult(rows=[(ROOM, "nips", "Nips & Crips")]),
            FakeQueryResult(scalar_rows=[]),
        ])

        with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)):
            result = asyncio.run(
                worker.inspect_date(
                    room_id=ROOM,
                    date_value=worker._parse_day("2026-01-01"),
                    detection_version="v1-embedding-cluster",
                )
            )

        self.assertEqual(result["detection_version"], "v1-embedding-cluster")

    def test_print_settings_outputs_effective_config(self):
        db = FakeQueryDb([FakeQueryResult(rows=[(ROOM, "nips", "Nips & Crips")])])
        service = types.SimpleNamespace(
            repository=types.SimpleNamespace(
                get_room_settings=AsyncMock(return_value=types.SimpleNamespace(
                    enabled=None,
                    similarity_threshold=0.85,
                    hard_gap_minutes=None,
                    soft_gap_minutes=None,
                    max_topic_duration_hours=None,
                    created_at=None,
                    updated_at=None,
                ))
            ),
            effective_config=AsyncMock(return_value=types.SimpleNamespace(
                as_dict=lambda: {
                    "similarity_threshold": 0.85,
                    "hard_gap_minutes": 120,
                    "soft_gap_minutes": 30,
                    "max_topic_duration_hours": 6,
                }
            )),
        )
        with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)), \
                unittest.mock.patch.object(worker, "TopicDetectionService", return_value=service):
            result = asyncio.run(worker.print_settings(room_id=ROOM))

        self.assertEqual(result["room_settings"]["similarity_threshold"], 0.85)
        self.assertEqual(result["effective_config"]["similarity_threshold"], 0.85)

    def test_replace_generated_topics_adds_recomputed_participants(self):
        db = FakeWriteDb([
            FakeQueryResult(),
            FakeQueryResult(rows=[]),
            FakeQueryResult(rows=[]),
        ])
        repo = TopicDetectionRepository(db)
        participant = types.SimpleNamespace(
            user_id=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
            canonical_name="Will",
            display_name="Small Willy Wray",
            message_count=3,
            segment_count=1,
            first_seen_at=datetime(2026, 1, 1, 10, 0),
            last_seen_at=datetime(2026, 1, 1, 10, 5),
        )
        repo._participant_drafts_for_topic = AsyncMock(return_value=[participant])

        inserted = asyncio.run(repo.replace_generated_topics(
            room_id=ROOM,
            model_name="fake-model",
            model_version="fake",
            detection_version="v2-semantic-time-cluster",
            topics=[
                TopicDraft(
                    label="Pub plans",
                    keywords=["pub"],
                    description=None,
                    confidence=0.8,
                    topic_date=datetime(2026, 1, 1).date(),
                    bucket_start_at=datetime(2026, 1, 1, 10, 0),
                    bucket_end_at=datetime(2026, 1, 1, 10, 10),
                    message_start_id=1,
                    message_end_id=3,
                    first_message_at=datetime(2026, 1, 1, 10, 0),
                    last_message_at=datetime(2026, 1, 1, 10, 10),
                    batch_count=1,
                    segments=[
                        TopicDraftSegment(
                            embedding_source_id="batch-1",
                            message_start_id=1,
                            message_end_id=3,
                            score=0.9,
                            excerpt="pub plans",
                            started_at=datetime(2026, 1, 1, 10, 0),
                            ended_at=datetime(2026, 1, 1, 10, 10),
                        )
                    ],
                )
            ],
        ))

        self.assertEqual(inserted, 1)
        added_participants = [row for row in db.added if isinstance(row, ChatTopicParticipant)]
        self.assertEqual(len(added_participants), 1)
        self.assertEqual(added_participants[0].canonical_name, "Will")
        self.assertEqual(added_participants[0].message_count, 3)

    def test_worker_iterates_all_rooms_with_date_range(self):
        other_room = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
        db = FakeWorkerDb(room_ids=[ROOM, other_room])
        service = FakeWorkerService()
        with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)), \
                unittest.mock.patch.object(worker, "TopicDetectionService", return_value=service):
            result = asyncio.run(
                worker.run_date_backfill(
                    room_id=None,
                    all_rooms=True,
                    date_from=worker._parse_day("2026-01-01"),
                    date_to=worker._parse_day("2026-01-02"),
                )
            )

        self.assertEqual(len(result), 4)
        self.assertEqual(
            [call["room_id"] for call in service.calls],
            [ROOM, other_room, ROOM, other_room],
        )
        self.assertEqual(db.commits, 4)

    def test_export_refinement_jobs_writes_jsonl_and_manifest(self):
        topic = _topic_obj()
        topic.segments[0].excerpt = "[01 Jan 10:00] Small Willy Wray: The group discusses going to the pub."
        topic.label = "Sep / Small Willy Wray / Techlett"
        topic.raw_label = topic.label
        topic.participants = [
            types.SimpleNamespace(
                canonical_name="Will",
                display_name="Small Willy Wray",
                message_count=4,
                segment_count=1,
                first_seen_at=datetime(2026, 1, 1, 10, 0),
                last_seen_at=datetime(2026, 1, 1, 10, 10),
            ),
            types.SimpleNamespace(
                canonical_name="Luke",
                display_name="Techlett",
                message_count=2,
                segment_count=1,
                first_seen_at=datetime(2026, 1, 1, 10, 1),
                last_seen_at=datetime(2026, 1, 1, 10, 9),
            ),
        ]
        refined_topic = _topic_obj(topic_id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000099"))
        refined_topic.refined_label = "Already refined"
        db = FakeQueryDb([FakeQueryResult(rows=[(ROOM, "nips", "Nips & Crips")])])
        repo = FakeRefinementIoRepo(
            export_topics=[topic, refined_topic],
            aliases={"Small Willy Wray": "Will", "Techlett": "Luke"},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "jobs.jsonl")
            with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                    unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)), \
                    unittest.mock.patch.object(worker, "TopicDetectionRepository", return_value=repo):
                result = asyncio.run(worker.export_refinement_jobs(
                    output_path=worker.Path(output_path),
                    room_id=ROOM,
                    date_value=worker._parse_day("2026-01-01"),
                ))

            with open(output_path, encoding="utf-8") as handle:
                lines = [json.loads(line) for line in handle if line.strip()]
            with open(result["manifest_path"], encoding="utf-8") as handle:
                manifest = json.load(handle)

        self.assertEqual(result["exported"], 1)
        self.assertEqual(result["skipped_refined"], 1)
        self.assertEqual(manifest["export_id"], result["export_id"])
        self.assertEqual(lines[0]["export_id"], result["export_id"])
        self.assertTrue(lines[0]["source_hash"].startswith("sha256:"))
        self.assertEqual(lines[0]["segments"][0]["excerpt"], "[01 Jan 10:00] Will: The group discusses going to the pub.")
        self.assertEqual(lines[0]["raw_label"], "Sep / Will / Luke")
        self.assertEqual([participant["canonical_name"] for participant in lines[0]["participants"]], ["Will", "Luke"])
        self.assertEqual(manifest["name_mode"], "canonical")

    def test_export_refinement_jobs_supports_display_and_anonymous_name_modes(self):
        topic = _topic_obj()
        topic.segments[0].excerpt = "[01 Jan 10:00] Small Willy Wray: hello"
        db = FakeQueryDb([
            FakeQueryResult(rows=[(ROOM, "nips", "Nips & Crips")]),
            FakeQueryResult(rows=[(ROOM, "nips", "Nips & Crips")]),
        ])
        repo = FakeRefinementIoRepo(
            export_topics=[topic],
            aliases={"Small Willy Wray": "Will"},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            display_path = os.path.join(tmpdir, "display.jsonl")
            anon_path = os.path.join(tmpdir, "anon.jsonl")
            with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                    unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)), \
                    unittest.mock.patch.object(worker, "TopicDetectionRepository", return_value=repo):
                asyncio.run(worker.export_refinement_jobs(
                    output_path=worker.Path(display_path),
                    room_id=ROOM,
                    date_value=worker._parse_day("2026-01-01"),
                    name_mode="display",
                ))
                asyncio.run(worker.export_refinement_jobs(
                    output_path=worker.Path(anon_path),
                    room_id=ROOM,
                    date_value=worker._parse_day("2026-01-01"),
                    name_mode="anonymous",
                ))
            display = json.loads(open(display_path, encoding="utf-8").readline())
            anonymous = json.loads(open(anon_path, encoding="utf-8").readline())

        self.assertEqual(display["segments"][0]["excerpt"], "[01 Jan 10:00] Small Willy Wray: hello")
        self.assertEqual(anonymous["segments"][0]["excerpt"], "[01 Jan 10:00] Participant 1: hello")
        self.assertNotEqual(display["source_hash"], anonymous["source_hash"])

    def test_import_refinements_dry_run_writes_nothing(self):
        topic = _topic_obj()
        job = build_refinement_job(
            topic=topic,
            room_id=ROOM,
            room_slug="nips",
            export_id=uuid.UUID("eeeeeeee-0000-0000-0000-000000000005"),
            max_segments=8,
            max_excerpt_chars=500,
            redaction=parse_redaction(None),
        )
        record = {
            "schema_version": "topic_refinement_result_v1",
            "record_type": "topic_refinement",
            "export_id": job["export_id"],
            "topic_id": str(topic.id),
            "room_id": str(ROOM),
            "topic_date": topic.topic_date.isoformat(),
            "source_hash": job["source_hash"],
            "status": "refined",
            "refined_label": "Pub plans",
            "summary": "The group discusses pub plans.",
            "tags": ["pub", "plans"],
            "topic_type": "planning",
            "confidence": 0.8,
            "refinement_model": "local:test",
        }
        db = FakeQueryDb([FakeQueryResult(rows=[(ROOM, "nips", "Nips & Crips")])])
        repo = FakeRefinementIoRepo(import_topics={topic.id: topic})

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "results.jsonl")
            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                    unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)), \
                    unittest.mock.patch.object(worker, "TopicDetectionRepository", return_value=repo):
                result = asyncio.run(worker.import_refinements(
                    input_path=worker.Path(input_path),
                    room_id=ROOM,
                    dry_run=True,
                ))

        self.assertEqual(result["would_update"], 1)
        self.assertEqual(result["updated"], 0)
        repo.apply_refinement.assert_not_called()

    def test_import_refinements_reports_unknown_topic(self):
        record = {
            "schema_version": "topic_refinement_result_v1",
            "record_type": "topic_refinement",
            "export_id": "eeeeeeee-0000-0000-0000-000000000005",
            "topic_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "room_id": str(ROOM),
            "source_hash": "sha256:nope",
            "status": "refined",
            "refined_label": "Pub plans",
            "summary": "The group discusses pub plans.",
            "tags": ["pub"],
            "topic_type": "planning",
            "confidence": 0.8,
        }
        db = FakeQueryDb([FakeQueryResult(rows=[(ROOM, "nips", "Nips & Crips")])])
        repo = FakeRefinementIoRepo(import_topics={})

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "results.jsonl")
            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            with unittest.mock.patch.object(worker, "get_settings", return_value=_settings()), \
                    unittest.mock.patch.object(worker, "async_session_factory", return_value=FakeSessionFactory(db)), \
                    unittest.mock.patch.object(worker, "TopicDetectionRepository", return_value=repo):
                result = asyncio.run(worker.import_refinements(
                    input_path=worker.Path(input_path),
                    room_id=ROOM,
                    dry_run=True,
                ))

        self.assertEqual(result["skipped_records"], 1)
        self.assertEqual(result["records"][0]["reason"], "topic_not_found")


class LocalTopicRefinementToolTest(unittest.TestCase):
    def test_local_tool_writes_valid_result_and_report_without_excerpts(self):
        tool = _load_local_refiner()
        topic = _topic_obj()
        export_id = uuid.UUID("eeeeeeee-0000-0000-0000-000000000005")
        job = build_refinement_job(
            topic=topic,
            room_id=ROOM,
            room_slug="nips",
            export_id=export_id,
            max_segments=8,
            max_excerpt_chars=500,
            redaction=parse_redaction(None),
        )
        manifest = {
            "schema_version": "topic_refinement_export_manifest_v1",
            "export_id": str(export_id),
            "room_id": str(ROOM),
            "room_slug": "nips",
            "date_from": "2026-01-01",
            "date_to": "2026-01-01",
            "detection_version": "v2-semantic-time-cluster",
            "topic_count": 1,
            "max_segments": 8,
            "max_excerpt_chars": 500,
            "redaction": ["urls", "emails", "phones"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "jobs.jsonl")
            manifest_path = os.path.join(tmpdir, "jobs.manifest.json")
            output_path = os.path.join(tmpdir, "results.jsonl")
            report_path = os.path.join(tmpdir, "results.md")
            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(job) + "\n")
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
            with unittest.mock.patch.object(tool, "call_local_model", return_value={
                "title": "Pub plans",
                "summary": "The group discusses pub plans.",
                "tags": ["pub"],
                "topic_type": "planning",
                "confidence": 0.8,
            }):
                result = tool.refine_file(
                    input_path=tool.Path(input_path),
                    manifest_path=tool.Path(manifest_path),
                    output_path=tool.Path(output_path),
                    report_path=tool.Path(report_path),
                    provider="ollama",
                    base_url="http://localhost:11434",
                    model="qwen2.5:7b-instruct",
                    force=True,
                )
            with open(output_path, encoding="utf-8") as handle:
                records = [json.loads(line) for line in handle if line.strip()]
            report = open(report_path, encoding="utf-8").read()

        self.assertEqual(result["refined"], 1)
        self.assertEqual(records[0]["status"], "refined")
        self.assertEqual(records[0]["refined_label"], "Pub plans")
        self.assertNotIn("The group discusses going to the pub.", report)

    def test_local_tool_records_invalid_model_json_as_failure(self):
        tool = _load_local_refiner()
        topic = _topic_obj()
        export_id = uuid.UUID("eeeeeeee-0000-0000-0000-000000000005")
        job = build_refinement_job(
            topic=topic,
            room_id=ROOM,
            room_slug="nips",
            export_id=export_id,
            max_segments=8,
            max_excerpt_chars=500,
            redaction=parse_redaction(None),
        )
        manifest = {
            "schema_version": "topic_refinement_export_manifest_v1",
            "export_id": str(export_id),
            "max_segments": 8,
            "max_excerpt_chars": 500,
        }

        with unittest.mock.patch.object(tool, "call_local_model", side_effect=ValueError("invalid_json")):
            result = tool.refine_job(
                job=job,
                manifest=manifest,
                provider="ollama",
                base_url="http://localhost:11434",
                model="qwen2.5:7b-instruct",
                temperature=0,
                max_retries=0,
                timeout=1,
            )

        self.assertEqual(result["status"], "failed")


def _topic_obj(topic_id=None):
    topic_id = topic_id or uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    return types.SimpleNamespace(
        id=topic_id,
        room_id=ROOM,
        label="Sep / Small Willy / Willy Wray",
        raw_label=None,
        refined_label=None,
        summary=None,
        tags=[],
        topic_type=None,
        confidence=0.9,
        label_source="keyword_placeholder",
        generation_type="semantic_time_cluster",
        detection_version="v2-semantic-time-cluster",
        topic_date=datetime(2026, 1, 1).date(),
        first_message_at=datetime(2026, 1, 1, 10, 0),
        last_message_at=datetime(2026, 1, 1, 10, 30),
        bucket_start_at=datetime(2026, 1, 1, 10, 0),
        bucket_end_at=datetime(2026, 1, 1, 10, 30),
        batch_count=2,
        segments=[
            types.SimpleNamespace(
                id=101,
                excerpt="The group discusses going to the pub.",
                started_at=datetime(2026, 1, 1, 10, 0),
                ended_at=datetime(2026, 1, 1, 10, 10),
                message_start_id=10,
                score=0.91,
            )
        ],
    )


def _load_local_refiner():
    spec = importlib.util.spec_from_file_location("refine_topics_local", LOCAL_REFINER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeRefinementClient:
    provider_name = "fake"
    model = "fake"

    def __init__(self, response):
        self.response = response
        self.prompts = []

    async def refine_topic(self, *, prompt: str, system_prompt: str):
        self.prompts.append(prompt)
        if isinstance(self.response, Exception):
            raise self.response
        payload = {
            "title": "General chat",
            "summary": "A general chat topic.",
            "tags": ["chat"],
            "topic_type": "general_chat",
            "confidence": 0.5,
        }
        payload.update(self.response)
        return payload


class FakeRefinementRepo:
    def __init__(self, topics):
        self.list_topics_for_refinement = AsyncMock(return_value=topics)
        self.apply_refinement = AsyncMock()


class FakeRefinementIoRepo:
    def __init__(self, export_topics=None, import_topics=None, aliases=None):
        self.export_topics = export_topics or []
        self.import_topics = import_topics or {}
        self.aliases = aliases or {}
        self.list_topics_for_refinement_export = AsyncMock(return_value=self.export_topics)
        self.list_participant_name_aliases = AsyncMock(return_value=self.aliases)
        self.apply_refinement = AsyncMock()

    async def get_topic_for_refinement_import(self, *, topic_id, room_id):
        return self.import_topics.get(topic_id)


class FakeWorkerDb:
    def __init__(self, room_ids=None):
        self.room_ids = room_ids or [ROOM]
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt):
        return FakeQueryResult(rows=[
            (room_id, f"room-{idx}", f"Room {idx}")
            for idx, room_id in enumerate(self.room_ids, start=1)
        ])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class FakeQueryResult:
    def __init__(self, rows=None, mapping_rows=None, scalar_rows=None):
        self._rows = rows or []
        self._mapping_rows = mapping_rows or []
        self._scalar_rows = scalar_rows or []

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows

    def mappings(self):
        return types.SimpleNamespace(all=lambda: self._mapping_rows)

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._scalar_rows)


class FakeQueryDb:
    def __init__(self, results):
        self.results = list(results)
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt, params=None):
        if not self.results:
            raise AssertionError("No fake query result queued")
        return self.results.pop(0)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class FakeWriteDb(FakeQueryDb):
    def __init__(self, results):
        super().__init__(results)
        self.added = []
        self.flushes = 0

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushes += 1


class FakeSessionFactory:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeWorkerService:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    async def generate_topics(self, **kwargs):
        self.calls.append(kwargs)
        if self.result is not None:
            return dict(self.result)
        return {
            "status": "embeddings_required",
            "room_id": str(kwargs["room_id"]),
            "topics_detected": 0,
            "topics_written": 0,
            "batches_scanned": 0,
            "dry_run": kwargs["dry_run"],
        }
