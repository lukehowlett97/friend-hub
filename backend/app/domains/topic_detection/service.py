from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domains.topic_detection.repository import (
    LABEL_SOURCE_KEYWORD_PLACEHOLDER,
    TopicDetectionRepository,
    TopicDraft,
    TopicDraftSegment,
    TopicEmbeddingBatch,
)

DEFAULT_LABEL = "Chat topic"
LABEL_MAX_KEYWORDS = 3
GENERATION_TYPE = "semantic_time_cluster"

STOPWORDS = {
    "a", "about", "after", "again", "all", "also", "am", "an", "and", "any", "are", "as", "at",
    "be", "been", "but", "by", "can", "could", "did", "do", "does", "doing", "for", "from",
    "get", "going", "got", "had", "has", "have", "he", "her", "here", "him", "his", "how",
    "i", "if", "in", "into", "is", "it", "its", "just", "like", "me", "my", "no", "not",
    "now", "of", "on", "or", "our", "out", "over", "she", "so", "that", "the", "their",
    "them", "then", "there", "they", "this", "to", "too", "up", "us", "was", "we", "were",
    "what", "when", "where", "who", "will", "with", "would", "you", "your",
}


@dataclass
class _Cluster:
    batches: list[TopicEmbeddingBatch] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)

    @property
    def centroid(self) -> list[float]:
        return _centroid([batch.embedding for batch in self.batches])


@dataclass(frozen=True)
class EffectiveTopicDetectionConfig:
    similarity_threshold: float
    hard_gap_minutes: int
    soft_gap_minutes: int
    max_topic_duration_hours: int

    def as_dict(self) -> dict:
        return {
            "similarity_threshold": self.similarity_threshold,
            "hard_gap_minutes": self.hard_gap_minutes,
            "soft_gap_minutes": self.soft_gap_minutes,
            "max_topic_duration_hours": self.max_topic_duration_hours,
        }


class TopicDetectionService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        settings=None,
        repository: TopicDetectionRepository | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.repository = repository or TopicDetectionRepository(db)

    async def status(self, *, room_id: uuid.UUID) -> dict:
        count = await self.repository.count_current_topics(
            room_id=room_id,
            model_name=self.settings.ai_embedding_model,
            model_version=self.settings.ai_embedding_provider,
            detection_version=self.settings.ai_topic_detection_version,
        )
        return {
            "enabled": bool(self.settings.ai_topic_detection_enabled),
            "generation_type": GENERATION_TYPE,
            "label_source": LABEL_SOURCE_KEYWORD_PLACEHOLDER,
            "model": self.settings.ai_embedding_model,
            "model_version": self.settings.ai_embedding_provider,
            "detection_version": self.settings.ai_topic_detection_version,
            "topic_count": count,
        }

    async def effective_config(
        self,
        *,
        room_id: uuid.UUID,
        similarity_threshold: float | None = None,
        hard_gap_minutes: int | None = None,
        soft_gap_minutes: int | None = None,
        max_topic_duration_hours: int | None = None,
    ) -> EffectiveTopicDetectionConfig:
        room_settings = await self.repository.get_room_settings(room_id=room_id)
        return EffectiveTopicDetectionConfig(
            similarity_threshold=_first_set(
                similarity_threshold,
                getattr(room_settings, "similarity_threshold", None),
                self.settings.ai_topic_similarity_threshold,
            ),
            hard_gap_minutes=int(_first_set(
                hard_gap_minutes,
                getattr(room_settings, "hard_gap_minutes", None),
                self.settings.ai_topic_hard_gap_minutes,
            )),
            soft_gap_minutes=int(_first_set(
                soft_gap_minutes,
                getattr(room_settings, "soft_gap_minutes", None),
                self.settings.ai_topic_soft_gap_minutes,
            )),
            max_topic_duration_hours=int(_first_set(
                max_topic_duration_hours,
                getattr(room_settings, "max_topic_duration_hours", None),
                self.settings.ai_topic_max_topic_duration_hours,
            )),
        )

    async def generate_topics(
        self,
        *,
        room_id: uuid.UUID,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit_batches: int | None = None,
        dry_run: bool = False,
        similarity_threshold: float | None = None,
        hard_gap_minutes: int | None = None,
        soft_gap_minutes: int | None = None,
        max_topic_duration_hours: int | None = None,
    ) -> dict:
        if not self.settings.ai_topic_detection_enabled:
            return {
                "status": "disabled",
                "room_id": str(room_id),
                "topics_detected": 0,
                "topics_written": 0,
                "batches_scanned": 0,
                "dry_run": dry_run,
            }

        effective_config = await self.effective_config(
            room_id=room_id,
            similarity_threshold=similarity_threshold,
            hard_gap_minutes=hard_gap_minutes,
            soft_gap_minutes=soft_gap_minutes,
            max_topic_duration_hours=max_topic_duration_hours,
        )
        limit = limit_batches or self.settings.ai_topic_max_batches_per_run
        batches = await self.repository.list_embedding_batches(
            room_id=room_id,
            model_name=self.settings.ai_embedding_model,
            model_version=self.settings.ai_embedding_provider,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        if not batches:
            return {
                "status": "embeddings_required",
                "room_id": str(room_id),
                "topics_detected": 0,
                "topics_written": 0,
                "batches_scanned": 0,
                "dry_run": dry_run,
                "generation_type": GENERATION_TYPE,
                "label_source": LABEL_SOURCE_KEYWORD_PLACEHOLDER,
            }

        stored_batches = self._stored_batches_for_window(
            batches,
            date_from=date_from,
            date_to=date_to,
        )
        drafts = self.detect_topic_drafts(
            stored_batches,
            topic_date=date_from.date() if date_from and date_to else None,
            effective_config=effective_config,
        )
        written = 0
        if not dry_run:
            written = await self.repository.replace_generated_topics(
                room_id=room_id,
                model_name=self.settings.ai_embedding_model,
                model_version=self.settings.ai_embedding_provider,
                detection_version=self.settings.ai_topic_detection_version,
                topics=drafts,
                date_from=date_from,
                date_to=date_to,
            )
        return {
            "status": "ok",
            "room_id": str(room_id),
            "topics_detected": len(drafts),
            "topics_written": written,
            "batches_scanned": len(batches),
            "dry_run": dry_run,
            "generation_type": GENERATION_TYPE,
            "label_source": LABEL_SOURCE_KEYWORD_PLACEHOLDER,
            "detection_version": self.settings.ai_topic_detection_version,
            "effective_config": effective_config.as_dict(),
            "topics": summarize_topic_drafts(drafts),
        }

    def detect_topic_drafts(
        self,
        batches: list[TopicEmbeddingBatch],
        *,
        topic_date=None,
        similarity_threshold: float | None = None,
        effective_config: EffectiveTopicDetectionConfig | None = None,
    ) -> list[TopicDraft]:
        config = effective_config or self._global_effective_config(similarity_threshold=similarity_threshold)
        clusters = self._cluster_batches(batches, effective_config=config)
        drafts: list[TopicDraft] = []
        min_batches = max(1, self.settings.ai_topic_min_cluster_batches)
        for cluster in clusters:
            if len(cluster.batches) < min_batches:
                continue
            ordered = sorted(
                cluster.batches,
                key=lambda b: (b.first_message_at or datetime.min, b.message_start_id),
            )
            label, keywords = placeholder_label(batch.content_preview or "" for batch in ordered)
            first_at = ordered[0].first_message_at
            last_at = max((b.last_message_at for b in ordered if b.last_message_at), default=first_at)
            message_start = min(b.message_start_id for b in ordered)
            message_end = max(b.message_end_id for b in ordered)
            scores = cluster.scores or [1.0]
            confidence = round(max(0.0, min(1.0, sum(scores) / len(scores))), 4)
            drafts.append(
                TopicDraft(
                    label=label,
                    keywords=keywords,
                    description=None,
                    confidence=confidence,
                    topic_date=topic_date or (first_at.date() if first_at else None),
                    bucket_start_at=first_at,
                    bucket_end_at=last_at,
                    message_start_id=message_start,
                    message_end_id=message_end,
                    first_message_at=first_at,
                    last_message_at=last_at,
                    batch_count=len(ordered),
                    segments=[
                        TopicDraftSegment(
                            embedding_source_id=batch.source_id,
                            message_start_id=batch.message_start_id,
                            message_end_id=batch.message_end_id,
                            score=round(score, 4),
                            excerpt=batch.content_preview,
                            started_at=batch.first_message_at,
                            ended_at=batch.last_message_at,
                        )
                        for batch, score in sorted(
                            zip(cluster.batches, scores),
                            key=lambda item: (item[0].first_message_at or datetime.min, item[0].message_start_id),
                        )
                    ],
                )
            )
        drafts.sort(key=lambda d: (d.bucket_start_at or datetime.min, d.message_start_id or 0))
        return drafts

    def _cluster_batches(
        self,
        batches: list[TopicEmbeddingBatch],
        *,
        effective_config: EffectiveTopicDetectionConfig,
    ) -> list[_Cluster]:
        clusters: list[_Cluster] = []
        threshold = effective_config.similarity_threshold
        ordered_batches = sorted(
            batches,
            key=lambda b: (b.first_message_at or datetime.min, b.message_start_id),
        )
        for batch in ordered_batches:
            if not batch.embedding:
                continue
            best_cluster = None
            best_score = -1.0
            for cluster in clusters:
                if not self._can_merge_by_time(cluster, batch, effective_config=effective_config):
                    continue
                score = cosine_similarity(batch.embedding, cluster.centroid)
                if self._exceeds_soft_gap(cluster, batch, effective_config=effective_config):
                    score -= 0.08
                if score > best_score:
                    best_score = score
                    best_cluster = cluster
            if best_cluster is not None and best_score >= threshold:
                best_cluster.batches.append(batch)
                best_cluster.scores.append(best_score)
            else:
                clusters.append(_Cluster(batches=[batch], scores=[1.0]))
        return clusters

    def _stored_batches_for_window(
        self,
        batches: list[TopicEmbeddingBatch],
        *,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list[TopicEmbeddingBatch]:
        if date_from is None or date_to is None:
            return batches
        return [
            batch
            for batch in batches
            if batch.first_message_at is not None
            and batch.first_message_at >= date_from
            and batch.first_message_at < date_to
        ]

    def _can_merge_by_time(
        self,
        cluster: _Cluster,
        batch: TopicEmbeddingBatch,
        *,
        effective_config: EffectiveTopicDetectionConfig,
    ) -> bool:
        cluster_start, cluster_end = _cluster_bounds(cluster)
        batch_start = batch.first_message_at
        batch_end = batch.last_message_at or batch_start
        if not cluster_start or not cluster_end or not batch_start:
            return True

        gap = (batch_start - cluster_end).total_seconds() / 60
        hard_gap = max(0, effective_config.hard_gap_minutes)
        if gap > hard_gap:
            return False

        max_duration_hours = max(0, effective_config.max_topic_duration_hours)
        if max_duration_hours:
            merged_end = max(cluster_end, batch_end or batch_start)
            duration_hours = (merged_end - min(cluster_start, batch_start)).total_seconds() / 3600
            if duration_hours > max_duration_hours:
                return False
        return True

    def _exceeds_soft_gap(
        self,
        cluster: _Cluster,
        batch: TopicEmbeddingBatch,
        *,
        effective_config: EffectiveTopicDetectionConfig,
    ) -> bool:
        _, cluster_end = _cluster_bounds(cluster)
        if not cluster_end or not batch.first_message_at:
            return False
        gap = (batch.first_message_at - cluster_end).total_seconds() / 60
        return gap > max(0, effective_config.soft_gap_minutes)

    def _global_effective_config(
        self,
        *,
        similarity_threshold: float | None = None,
    ) -> EffectiveTopicDetectionConfig:
        return EffectiveTopicDetectionConfig(
            similarity_threshold=_first_set(
                similarity_threshold,
                self.settings.ai_topic_similarity_threshold,
            ),
            hard_gap_minutes=int(self.settings.ai_topic_hard_gap_minutes),
            soft_gap_minutes=int(self.settings.ai_topic_soft_gap_minutes),
            max_topic_duration_hours=int(self.settings.ai_topic_max_topic_duration_hours),
        )


def summarize_topic_drafts(drafts: list[TopicDraft]) -> list[dict]:
    return [
        {
            "label": draft.label,
            "confidence": draft.confidence,
            "batch_count": draft.batch_count,
            "topic_date": draft.topic_date.isoformat() if draft.topic_date else None,
            "first_message_at": draft.first_message_at.isoformat() if draft.first_message_at else None,
            "last_message_at": draft.last_message_at.isoformat() if draft.last_message_at else None,
            "keywords": draft.keywords,
        }
        for draft in drafts
    ]


def _cluster_bounds(cluster: _Cluster) -> tuple[datetime | None, datetime | None]:
    starts = [batch.first_message_at for batch in cluster.batches if batch.first_message_at]
    ends = [batch.last_message_at or batch.first_message_at for batch in cluster.batches if batch.last_message_at or batch.first_message_at]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _first_set(*values):
    for value in values:
        if value is not None:
            return value
    return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if denom == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / denom


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dims = len(vectors[0])
    if dims == 0:
        return []
    summed = [0.0] * dims
    count = 0
    for vector in vectors:
        if len(vector) != dims:
            continue
        count += 1
        for idx, value in enumerate(vector):
            summed[idx] += value
    if count == 0:
        return []
    return [value / count for value in summed]


def placeholder_label(texts: Iterable[str]) -> tuple[str, list[str]]:
    tokens: list[str] = []
    for text in texts:
        tokens.extend(_tokenize(text))
    if not tokens:
        return DEFAULT_LABEL, []

    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    for left, right in zip(tokens, tokens[1:]):
        phrase = f"{left} {right}"
        counts[phrase] = counts.get(phrase, 0) + 2

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    keywords: list[str] = []
    for word, _ in ranked:
        if any(word in chosen or chosen in word for chosen in keywords):
            continue
        keywords.append(word)
        if len(keywords) >= LABEL_MAX_KEYWORDS:
            break
    label = " / ".join(part.title() for part in keywords) if keywords else DEFAULT_LABEL
    return label, keywords


def _tokenize(text: str) -> list[str]:
    raw = re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", text.lower())
    return [token.strip("'-") for token in raw if token.strip("'-") and token not in STOPWORDS]
