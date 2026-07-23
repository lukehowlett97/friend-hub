import asyncio
import os
import types
import unittest
import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

os.environ["DEBUG"] = "false"

from app.api.v1 import topics_router

ROOM = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
TOPIC_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _topic(**overrides):
    base = dict(
        id=TOPIC_ID,
        room_id=ROOM,
        label="Camping / Tents",
        raw_label="Camping / Tents",
        refined_label=None,
        keywords=["camping", "tents"],
        description=None,
        summary=None,
        tags=[],
        topic_type=None,
        refinement_model=None,
        refined_at=None,
        confidence=0.88,
        label_source="keyword_placeholder",
        generation_type="semantic_time_cluster",
        topic_date=date(2026, 6, 1),
        bucket_start_at=datetime(2026, 6, 1, 12, 0, 0),
        bucket_end_at=datetime(2026, 6, 1, 12, 15, 0),
        message_start_id=10,
        message_end_id=20,
        first_message_at=datetime(2026, 6, 1, 12, 0, 0),
        last_message_at=datetime(2026, 6, 1, 12, 15, 0),
        batch_count=2,
        model_name="fake-model",
        model_version="fake",
        detection_version="v2-semantic-time-cluster",
        status="active",
        created_at=datetime(2026, 6, 1, 13, 0, 0),
        updated_at=datetime(2026, 6, 1, 13, 0, 0),
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _segment(**overrides):
    base = dict(
        id=1,
        topic_id=TOPIC_ID,
        room_id=ROOM,
        embedding_source_id=f"{ROOM}:10-20",
        message_start_id=10,
        message_end_id=20,
        score=0.9,
        excerpt="camping tents",
        started_at=datetime(2026, 6, 1, 12, 0, 0),
        ended_at=datetime(2026, 6, 1, 12, 15, 0),
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _participant():
    return types.SimpleNamespace(
        id=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
        topic_id=TOPIC_ID,
        room_id=ROOM,
        user_id=uuid.UUID("eeeeeeee-0000-0000-0000-000000000005"),
        canonical_name="Will",
        display_name="Small Willy Wray",
        message_count=7,
        segment_count=1,
        first_seen_at=datetime(2026, 6, 1, 12, 0, 0),
        last_seen_at=datetime(2026, 6, 1, 12, 15, 0),
    )


class TopicsRouterTest(unittest.TestCase):
    def test_list_topics_payload(self):
        repo = types.SimpleNamespace(
            list_topics=AsyncMock(return_value=[_topic()]),
            list_participants=AsyncMock(return_value=[_participant()]),
        )
        with patch.object(topics_router, "TopicDetectionRepository", return_value=repo), \
                patch.object(topics_router, "get_settings", return_value=types.SimpleNamespace(ai_topic_detection_version="v2-semantic-time-cluster")):
            result = asyncio.run(
                topics_router.list_topics(
                    limit=10,
                    room=types.SimpleNamespace(id=ROOM),
                    db=object(),
                )
            )

        self.assertEqual(result["limit"], 10)
        self.assertEqual(len(result["topics"]), 1)
        payload = result["topics"][0]
        self.assertEqual(payload["id"], str(TOPIC_ID))
        self.assertEqual(payload["label_source"], "keyword_placeholder")
        self.assertEqual(payload["display_label"], "Camping / Tents")
        self.assertEqual(payload["raw_label"], "Camping / Tents")
        self.assertEqual(payload["generation_type"], "semantic_time_cluster")
        self.assertEqual(payload["topic_date"], "2026-06-01")
        self.assertEqual(payload["participant_count"], 1)
        self.assertEqual(payload["participant_names"], ["Will"])
        self.assertNotIn("participants", payload)
        self.assertEqual(result["detection_version"], "v2-semantic-time-cluster")
        repo.list_topics.assert_awaited_once()
        self.assertEqual(repo.list_topics.await_args.kwargs["detection_version"], "v2-semantic-time-cluster")

    def test_list_topics_allows_detection_version_override(self):
        repo = types.SimpleNamespace(list_topics=AsyncMock(return_value=[_topic(detection_version="v1-embedding-cluster")]))
        with patch.object(topics_router, "TopicDetectionRepository", return_value=repo), \
                patch.object(topics_router, "get_settings", return_value=types.SimpleNamespace(ai_topic_detection_version="v2-semantic-time-cluster")):
            result = asyncio.run(
                topics_router.list_topics(
                    limit=10,
                    detection_version="v1-embedding-cluster",
                    room=types.SimpleNamespace(id=ROOM),
                    db=object(),
                )
            )

        self.assertEqual(result["detection_version"], "v1-embedding-cluster")
        self.assertEqual(repo.list_topics.await_args.kwargs["detection_version"], "v1-embedding-cluster")

    def test_get_topic_includes_segments(self):
        repo = types.SimpleNamespace(
            get_topic=AsyncMock(return_value=_topic()),
            list_segments=AsyncMock(return_value=[_segment()]),
            list_participants=AsyncMock(return_value=[]),
        )
        with patch.object(topics_router, "TopicDetectionRepository", return_value=repo), \
                patch.object(topics_router, "get_settings", return_value=types.SimpleNamespace(ai_topic_detection_version="v2-semantic-time-cluster")):
            result = asyncio.run(
                topics_router.get_topic(
                    topic_id=TOPIC_ID,
                    room=types.SimpleNamespace(id=ROOM),
                    db=object(),
                )
            )

        self.assertEqual(result["id"], str(TOPIC_ID))
        self.assertEqual(result["display_label"], "Camping / Tents")
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(result["segments"][0]["message_start_id"], 10)
        self.assertEqual(result["segments"][0]["chat_anchor"], "/chat?message=10")
        self.assertEqual(result["message_count"], 11)
        self.assertEqual(result["segment_count"], 1)

    def test_get_topic_includes_participants(self):
        repo = types.SimpleNamespace(
            get_topic=AsyncMock(return_value=_topic()),
            list_segments=AsyncMock(return_value=[_segment()]),
            list_participants=AsyncMock(return_value=[_participant()]),
        )
        with patch.object(topics_router, "TopicDetectionRepository", return_value=repo):
            result = asyncio.run(
                topics_router.get_topic(
                    topic_id=TOPIC_ID,
                    room=types.SimpleNamespace(id=ROOM),
                    db=object(),
                )
            )

        self.assertEqual(result["participant_count"], 1)
        self.assertEqual(result["participant_names"], ["Will"])
        self.assertEqual(result["participants"][0]["display_name"], "Small Willy Wray")

    def test_timeline_returns_day_summary(self):
        repo = types.SimpleNamespace(
            list_timeline_topics=AsyncMock(return_value=[_topic()]),
            list_segments=AsyncMock(return_value=[_segment()]),
            list_participants=AsyncMock(return_value=[_participant()]),
        )
        with patch.object(topics_router, "TopicDetectionRepository", return_value=repo):
            result = asyncio.run(
                topics_router.topic_timeline(
                    date=date(2026, 6, 1),
                    room=types.SimpleNamespace(id=ROOM),
                    db=object(),
                )
            )

        self.assertEqual(result["date"], "2026-06-01")
        self.assertEqual(result["detection_version"], "v2-semantic-time-cluster")
        self.assertEqual(len(result["topics"]), 1)
        topic = result["topics"][0]
        self.assertEqual(topic["id"], str(TOPIC_ID))
        self.assertEqual(topic["label"], "Camping / Tents")
        self.assertEqual(topic["display_label"], "Camping / Tents")
        self.assertEqual(topic["message_count"], 11)
        self.assertEqual(topic["segments"], 1)
        self.assertEqual(topic["chat_anchor"], "/chat?message=10&highlight=10")
        self.assertEqual(topic["participant_count"], 1)
        self.assertEqual(topic["participant_names"], ["Will"])
        args = repo.list_timeline_topics.await_args.kwargs
        self.assertEqual(args["room_id"], ROOM)
        self.assertEqual(args["day_start"].isoformat(), "2026-06-01T00:00:00+00:00")
        self.assertEqual(args["day_end"].isoformat(), "2026-06-02T00:00:00+00:00")
        self.assertEqual(args["detection_version"], "v2-semantic-time-cluster")

    def test_timeline_chat_anchor_highlights_segment_starts(self):
        topic = _topic(message_start_id=10, message_end_id=45)
        segments = [
            _segment(id=1, message_start_id=10, message_end_id=20),
            _segment(id=2, embedding_source_id=f"{ROOM}:30-45", message_start_id=30, message_end_id=45),
        ]

        payload = topics_router._timeline_topic_payload(topic, segments)

        self.assertEqual(payload["chat_anchor"], "/chat?message=10&highlight=10,30")

    def test_timeline_returns_date_range_grouped_by_day(self):
        topic_a = _topic(topic_date=date(2026, 6, 1))
        topic_b = _topic(
            id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002"),
            topic_date=date(2026, 6, 3),
            bucket_start_at=datetime(2026, 6, 3, 9, 0, 0),
            bucket_end_at=datetime(2026, 6, 3, 9, 30, 0),
            first_message_at=datetime(2026, 6, 3, 9, 0, 0),
            last_message_at=datetime(2026, 6, 3, 9, 30, 0),
        )
        repo = types.SimpleNamespace(
            list_timeline_topics=AsyncMock(return_value=[topic_a, topic_b]),
            list_segments=AsyncMock(return_value=[_segment()]),
            list_participants=AsyncMock(return_value=[_participant()]),
        )
        with patch.object(topics_router, "TopicDetectionRepository", return_value=repo):
            result = asyncio.run(
                topics_router.topic_timeline(
                    date_from=date(2026, 6, 1),
                    date_to=date(2026, 6, 3),
                    room=types.SimpleNamespace(id=ROOM),
                    db=object(),
                )
            )

        self.assertEqual(result["date_from"], "2026-06-01")
        self.assertEqual(result["date_to"], "2026-06-03")
        self.assertEqual([day["date"] for day in result["days"]], ["2026-06-01", "2026-06-02", "2026-06-03"])
        self.assertEqual(len(result["days"][0]["topics"]), 1)
        self.assertEqual(len(result["days"][1]["topics"]), 0)
        self.assertEqual(len(result["days"][2]["topics"]), 1)
        self.assertEqual(result["days"][0]["topics"][0]["segment_count"], 1)
        args = repo.list_timeline_topics.await_args.kwargs
        self.assertEqual(args["day_start"].isoformat(), "2026-06-01T00:00:00+00:00")
        self.assertEqual(args["day_end"].isoformat(), "2026-06-04T00:00:00+00:00")

    def test_debug_topics_includes_segment_previews_and_anchors(self):
        repo = types.SimpleNamespace(
            list_topics=AsyncMock(return_value=[_topic()]),
            list_segments=AsyncMock(return_value=[_segment()]),
        )
        with patch.object(topics_router, "TopicDetectionRepository", return_value=repo), \
                patch.object(topics_router, "get_settings", return_value=types.SimpleNamespace(ai_topic_detection_version="v2-semantic-time-cluster")):
            result = asyncio.run(
                topics_router.debug_topics(
                    room=types.SimpleNamespace(id=ROOM),
                    db=object(),
                )
            )

        self.assertIsNone(result["date"])
        self.assertEqual(result["detection_version"], "v2-semantic-time-cluster")
        self.assertEqual(len(result["topics"]), 1)
        topic = result["topics"][0]
        self.assertEqual(topic["segment_count"], 1)
        self.assertEqual(topic["segments"][0]["excerpt"], "camping tents")
        self.assertEqual(topic["segments"][0]["chat_anchor"], "/chat?message=10")
        self.assertEqual(repo.list_topics.await_args.kwargs["detection_version"], "v2-semantic-time-cluster")

    def test_api_display_label_prefers_refined_label(self):
        refined = _topic(
            raw_label="Camping / Tents",
            refined_label="Camping Gear Plans",
            summary="The group discusses camping equipment.",
            tags=["camping", "gear"],
            topic_type="planning",
            refinement_model="fake:fake",
            refined_at=datetime(2026, 6, 1, 14, 0, 0),
            label_source="llm_refined",
        )
        payload = topics_router._topic_payload(refined)
        timeline = topics_router._timeline_topic_payload(refined, [_segment()])

        self.assertEqual(payload["display_label"], "Camping Gear Plans")
        self.assertEqual(payload["label"], "Camping / Tents")
        self.assertEqual(payload["summary"], "The group discusses camping equipment.")
        self.assertEqual(payload["tags"], ["camping", "gear"])
        self.assertEqual(timeline["label"], "Camping Gear Plans")

    def test_debug_topics_allows_detection_version_override(self):
        repo = types.SimpleNamespace(
            list_timeline_topics=AsyncMock(return_value=[_topic(detection_version="v1-embedding-cluster")]),
            list_segments=AsyncMock(return_value=[_segment()]),
        )
        with patch.object(topics_router, "TopicDetectionRepository", return_value=repo), \
                patch.object(topics_router, "get_settings", return_value=types.SimpleNamespace(ai_topic_detection_version="v2-semantic-time-cluster")):
            result = asyncio.run(
                topics_router.debug_topics(
                    date=date(2026, 6, 1),
                    detection_version="v1-embedding-cluster",
                    room=types.SimpleNamespace(id=ROOM),
                    db=object(),
                )
            )

        self.assertEqual(result["detection_version"], "v1-embedding-cluster")
        self.assertEqual(repo.list_timeline_topics.await_args.kwargs["detection_version"], "v1-embedding-cluster")

    def test_get_topic_404(self):
        repo = types.SimpleNamespace(get_topic=AsyncMock(return_value=None))
        with patch.object(topics_router, "TopicDetectionRepository", return_value=repo):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    topics_router.get_topic(
                        topic_id=TOPIC_ID,
                        room=types.SimpleNamespace(id=ROOM),
                        db=object(),
                    )
                )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_status_payload_uses_service(self):
        service = types.SimpleNamespace(status=AsyncMock(return_value={"enabled": True}))
        with patch.object(topics_router, "TopicDetectionService", return_value=service):
            result = asyncio.run(
                topics_router.topic_status(room=types.SimpleNamespace(id=ROOM), db=object())
            )
        self.assertEqual(result, {"enabled": True})
        service.status.assert_awaited_once_with(room_id=ROOM)
