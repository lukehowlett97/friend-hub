from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import get_provider
from app.config import get_settings
from app.domains.topic_detection.repository import TopicDetectionRepository

logger = logging.getLogger(__name__)

TOPIC_TYPES = {
    "general_chat",
    "planning",
    "event",
    "sport",
    "gaming",
    "food_drink",
    "music",
    "travel",
    "work",
    "relationship",
    "memory",
    "unknown",
}
GENERIC_TAGS = {"discussion", "chat", "conversation", "topic", "general"}
TYPE_TAG_OVERRIDES = {
    "gaming": {"gaming", "video_games", "xbox", "playstation", "fifa", "cod", "warzone", "steam"},
    "sport": {"sport", "football", "boxing", "mma", "fight", "match"},
    "music": {"music", "song", "playlist", "album"},
    "travel": {"travel", "holiday", "flight", "airport"},
    "food_drink": {"food", "drink", "pub", "restaurant", "takeaway"},
}
WORK_EVIDENCE_TERMS = {
    "assignment",
    "boss",
    "business",
    "client",
    "coursework",
    "employment",
    "job",
    "jobs",
    "manager",
    "office",
    "professional",
    "project",
    "schoolwork",
    "shift",
    "shifts",
    "workplace",
}
JOB_SCHEMA_VERSION = "topic_refinement_job_v1"
RESULT_SCHEMA_VERSION = "topic_refinement_result_v1"


class TopicRefinementClient(Protocol):
    provider_name: str
    model: str

    async def refine_topic(self, *, prompt: str, system_prompt: str) -> dict:
        ...


@dataclass(frozen=True)
class TopicRefinementResult:
    title: str
    summary: str
    tags: list[str]
    topic_type: str
    confidence: float

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "summary": self.summary,
            "tags": self.tags,
            "topic_type": self.topic_type,
            "confidence": self.confidence,
        }


class FakeTopicRefinementClient:
    provider_name = "fake"
    model = "fake"

    async def refine_topic(self, *, prompt: str, system_prompt: str) -> dict:
        lowered = prompt.lower()
        if "pub" in lowered or "spoons" in lowered:
            title = "Pub Plans"
            topic_type = "planning"
            tags = ["planning", "pub"]
        elif "football" in lowered:
            title = "Football Chat"
            topic_type = "sport"
            tags = ["football"]
        elif "nazi" in lowered or "china" in lowered or "government" in lowered:
            title = "Article Chat"
            topic_type = "general_chat"
            tags = ["general_chat"]
        else:
            title = "General Chat"
            topic_type = "general_chat"
            tags = ["chat"]
        return {
            "title": title,
            "summary": "The group discusses the topic shown in the provided excerpts.",
            "tags": tags,
            "topic_type": topic_type,
            "confidence": 0.65,
        }


class OllamaTopicRefinementClient:
    provider_name = "ollama"

    def __init__(self, *, base_url: str, model: str, timeout: int):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def refine_topic(self, *, prompt: str, system_prompt: str) -> dict:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "format": "json",
        }
        async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
            resp = await client.post(f"{self.base_url}/api/generate", json=payload)
            resp.raise_for_status()
            return _extract_json(resp.json().get("response", ""))


class OpenRouterTopicRefinementClient:
    provider_name = "openrouter"

    def __init__(self, *, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self._provider = None

    def _get_provider(self):
        if self._provider is None:
            self._provider = get_provider(self.api_key, "openrouter")
        return self._provider

    async def refine_topic(self, *, prompt: str, system_prompt: str) -> dict:
        response_text, _, _ = await self._get_provider().complete_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            self.model,
            temperature=0.2,
        )
        return _extract_json(response_text)


class TopicRefinementService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        settings=None,
        repository: TopicDetectionRepository | None = None,
        client: TopicRefinementClient | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.repository = repository or TopicDetectionRepository(db)
        self.client = client or create_topic_refinement_client(self.settings)

    async def refine_date(
        self,
        *,
        room_id: uuid.UUID,
        date_value: date,
        detection_version: str | None = None,
        topic_id: uuid.UUID | None = None,
        dry_run: bool = False,
        force: bool = False,
        limit_topics: int | None = None,
    ) -> dict:
        selected_version = detection_version or self.settings.ai_topic_detection_version
        if not self.settings.ai_topic_llm_refinement_enabled:
            return {
                "status": "disabled",
                "room_id": str(room_id),
                "date": date_value.isoformat(),
                "detection_version": selected_version,
                "dry_run": dry_run,
                "topics_scanned": 0,
                "topics_refined": 0,
                "topics_failed": 0,
                "refinements": [],
            }

        day_start = datetime.combine(date_value, datetime.min.time(), tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        topics = await self.repository.list_topics_for_refinement(
            room_id=room_id,
            day_start=day_start,
            day_end=day_end,
            detection_version=selected_version,
            topic_id=topic_id,
            force=force,
            limit=limit_topics,
        )
        refinements = []
        refined = 0
        failed = 0
        for topic in topics:
            try:
                prompt = self._build_prompt(topic)
                raw = await self.client.refine_topic(
                    prompt=prompt,
                    system_prompt=_system_prompt(),
                )
                proposal = validate_refinement(raw)
            except Exception as exc:
                logger.warning("Topic refinement failed topic=%s: %s", topic.id, exc)
                failed += 1
                refinements.append({
                    "topic_id": str(topic.id),
                    "status": "failed",
                    "error": str(exc),
                    "raw_label": topic.raw_label or topic.label,
                })
                continue

            payload = {
                "topic_id": str(topic.id),
                "status": "proposed" if dry_run else "refined",
                "raw_label": topic.raw_label or topic.label,
                "display_label": proposal.title,
                "refinement": proposal.as_dict(),
                "first_message_at": topic.first_message_at.isoformat() if topic.first_message_at else None,
                "last_message_at": topic.last_message_at.isoformat() if topic.last_message_at else None,
                "batch_count": topic.batch_count,
            }
            refinements.append(payload)
            if not dry_run:
                await self.repository.apply_refinement(
                    topic=topic,
                    title=proposal.title,
                    summary=proposal.summary,
                    tags=proposal.tags,
                    topic_type=proposal.topic_type,
                    confidence=proposal.confidence,
                    refinement_model=self.refinement_model,
                )
            refined += 1

        return {
            "status": "ok",
            "room_id": str(room_id),
            "date": date_value.isoformat(),
            "detection_version": selected_version,
            "dry_run": dry_run,
            "force": force,
            "topic_id": str(topic_id) if topic_id else None,
            "limit_topics": limit_topics,
            "refinement_model": self.refinement_model,
            "topics_scanned": len(topics),
            "topics_refined": refined,
            "topics_failed": failed,
            "refinements": refinements,
        }

    @property
    def refinement_model(self) -> str:
        return f"{self.client.provider_name}:{self.client.model}"

    def _build_prompt(self, topic) -> str:
        segments = sorted(
            getattr(topic, "segments", []) or [],
            key=lambda segment: (segment.started_at or datetime.min.replace(tzinfo=timezone.utc), segment.message_start_id or 0),
        )
        return build_refinement_prompt(
            raw_label=topic.raw_label or topic.label,
            confidence=topic.confidence,
            started_at=_iso(topic.first_message_at),
            ended_at=_iso(topic.last_message_at),
            batch_count=topic.batch_count,
            segments=[
                {
                    "started_at": _iso(segment.started_at),
                    "ended_at": _iso(segment.ended_at),
                    "excerpt": segment.excerpt,
                }
                for segment in segments
            ],
            participants=[
                {
                    "canonical_name": participant.canonical_name,
                    "message_count": participant.message_count,
                    "segment_count": participant.segment_count,
                }
                for participant in (getattr(topic, "participants", []) or [])
            ],
            max_segments=max(1, int(self.settings.ai_topic_llm_max_segments)),
            max_excerpt_chars=max(100, int(self.settings.ai_topic_llm_max_excerpt_chars)),
        )


def create_topic_refinement_client(settings) -> TopicRefinementClient:
    provider = settings.ai_topic_llm_provider
    model = settings.ai_topic_llm_model
    if provider == "fake":
        return FakeTopicRefinementClient()
    if provider == "ollama":
        return OllamaTopicRefinementClient(
            base_url=settings.ollama_base_url,
            model=model if model != "fake" else settings.ollama_model,
            timeout=settings.ollama_timeout,
        )
    if provider == "openrouter":
        if not settings.ai_api_key:
            raise ValueError("AI_API_KEY is required for OpenRouter topic refinement")
        return OpenRouterTopicRefinementClient(
            api_key=settings.ai_api_key,
            model=model if model != "fake" else settings.ai_default_chat_model,
        )
    raise ValueError(f"Unknown topic LLM provider: {provider!r}")


def validate_refinement(data: dict) -> TopicRefinementResult:
    if not isinstance(data, dict):
        raise ValueError("refinement response must be a JSON object")
    title = _clean_text(data.get("title", ""), limit=80)
    if not title:
        raise ValueError("refinement title is required")
    title = " ".join(title.split()[:8])
    summary = _clean_text(data.get("summary", ""), limit=500)
    if not summary:
        raise ValueError("refinement summary is required")
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    clean_tags = []
    for tag in tags:
        clean = _normalise_tag(str(tag))
        if clean in GENERIC_TAGS:
            continue
        if clean and clean not in clean_tags:
            clean_tags.append(clean)
        if len(clean_tags) >= 5:
            break
    topic_type = str(data.get("topic_type") or "unknown").strip().lower()
    if topic_type not in TOPIC_TYPES:
        topic_type = "unknown"
    topic_type = _align_topic_type_with_tags(topic_type=topic_type, tags=clean_tags)
    topic_type, clean_tags = _normalise_work_classification(
        topic_type=topic_type,
        tags=clean_tags,
        title=title,
        summary=summary,
    )
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = min(1.0, max(0.0, confidence))
    return TopicRefinementResult(
        title=title,
        summary=summary,
        tags=clean_tags,
        topic_type=topic_type,
        confidence=round(confidence, 4),
    )


def build_refinement_prompt(
    *,
    raw_label: str | None,
    confidence: float | None,
    started_at: str | None,
    ended_at: str | None,
    batch_count: int | None,
    segments: list[dict],
    max_segments: int,
    max_excerpt_chars: int,
    participants: list[dict] | None = None,
) -> str:
    max_segments = max(1, int(max_segments))
    max_excerpt_chars = max(100, int(max_excerpt_chars))
    excerpt_lines = []
    excerpt_participants = set()
    for idx, segment in enumerate(segments[:max_segments], start=1):
        excerpt = (segment.get("excerpt") or "").strip().replace("\x00", "")
        excerpt = excerpt[:max_excerpt_chars]
        excerpt_participants.update(_extract_participants(excerpt))
        excerpt_lines.append(
            f"{idx}. [{segment.get('started_at')} - {segment.get('ended_at')}] {excerpt}"
        )
    stored_participants = [
        str(participant.get("canonical_name") or "").strip()
        for participant in (participants or [])
        if str(participant.get("canonical_name") or "").strip()
    ]
    participant_line = ", ".join(stored_participants[:12])
    if not participant_line:
        participant_line = ", ".join(sorted(excerpt_participants)[:12]) or "unknown"

    return "\n".join([
        f"Raw label: {raw_label or ''}",
        f"Current confidence: {confidence}",
        f"Time range: {started_at} to {ended_at}",
        f"Batch count: {batch_count}",
        f"Participants seen in excerpts: {participant_line}",
        "Segment excerpts:",
        *excerpt_lines,
    ])


def topic_refinement_system_prompt() -> str:
    return _system_prompt()


def _system_prompt() -> str:
    return """You label short historical group-chat topic clusters for a private friend-group timeline.

Output ONLY valid JSON:
{
  "title": "short human-readable title",
  "summary": "one or two sentence summary",
  "tags": ["tag1", "tag2"],
  "topic_type": "general_chat|planning|event|sport|gaming|food_drink|music|travel|work|relationship|memory|unknown",
  "confidence": 0.0
}

Rules:
- Produce labels that would make sense on a timeline card.
- Prefer natural labels like "Planning a night out", "Football chat", "Debating a weird article", "Talking about the moon landing", or "Arranging pub plans".
- Avoid stiff titles like "Discussion about...", "Debate regarding...", or "Conversation concerning...".
- Do not include participant names in the title unless essential.
- Use only the provided excerpts. Do not invent facts.
- Preserve real participant names exactly as provided when names are needed.
- Do not describe people with unsupported roles such as player, boxer, worker, organiser, or host unless the excerpts clearly show that role.
- Do not use "work" just because the topic mentions dates, numbers, stats, deadlines, tasks, or plans. Only use "work" when the excerpts clearly refer to employment, professional projects, shifts, business, schoolwork, coursework, or workplace responsibilities.
- For casual group chat, prefer tags such as general_chat, sport, football, boxing, mma, pub, night_out, plans, travel, gaming, food, music, relationships, banter, logistics, watch_party.
- Avoid vague tags like discussion, chat, conversation, topic, or general unless no better tag is possible.
- If tags include a domain-specific category such as gaming, sport, football, boxing, music, travel, pub, food, or food_drink, topic_type should usually match that domain rather than general_chat.
- Topic type guidance: fight commentary, football matches, and sport events are sport; arranging where or when to meet is planning; chatting during a party, match, trip, or night out is event; otherwise use general_chat.
- If the cluster is messy, label it honestly as general_chat or unknown.
- Keep titles under 8 words.
- Keep summaries short, plain, and in British English.
- Tags must be lowercase snake_case.
- Return strict JSON only. No Markdown. No surrounding explanation."""


def _extract_json(text: str) -> dict:
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(match.group())


def _clean_text(value: str, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _normalise_tag(value: str) -> str:
    text = _clean_text(value.lower(), limit=64)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:32]


def _align_topic_type_with_tags(*, topic_type: str, tags: list[str]) -> str:
    if topic_type not in {"general_chat", "unknown"}:
        return topic_type
    tag_set = set(tags)
    for override_type, override_tags in TYPE_TAG_OVERRIDES.items():
        if tag_set & override_tags:
            return override_type
    return topic_type


def _normalise_work_classification(
    *,
    topic_type: str,
    tags: list[str],
    title: str,
    summary: str,
) -> tuple[str, list[str]]:
    if topic_type != "work" and "work" not in tags:
        return topic_type, tags
    evidence_text = f"{title} {summary} {' '.join(tag for tag in tags if tag != 'work')}".lower()
    has_work_evidence = any(re.search(rf"\b{re.escape(term)}\b", evidence_text) for term in WORK_EVIDENCE_TERMS)
    if has_work_evidence:
        return topic_type, tags
    tags = [tag for tag in tags if tag != "work"]
    if topic_type == "work":
        topic_type = _align_topic_type_with_tags(topic_type="general_chat", tags=tags)
    return topic_type, tags


def _extract_participants(excerpt: str) -> set[str]:
    names = set()
    for match in re.finditer(r"\[[^\]]+\]\s+([^:\n]{1,40}):", excerpt):
        name = _clean_text(match.group(1), limit=40)
        if name:
            names.add(name)
    return names


def _iso(value) -> str | None:
    return value.isoformat() if value else None
