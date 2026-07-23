"""Chat embeddings worker — sweep, claim, embed.

Cloned from the image embeddings worker. Each tick optionally runs the
idempotent sweep enqueuer (which is also the historical backfill), then
claims and processes pending jobs.

Usage:
    python -m app.domains.chat_embeddings.worker --backfill          # embed all history, resumable
    python -m app.domains.chat_embeddings.worker --sleep-seconds 30  # steady-state loop
    python -m app.domains.chat_embeddings.worker --once --limit 50
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid

from app.config import get_settings
from app.domains.chat_embeddings.repository import SOURCE_MESSAGE_BATCH
from app.domains.chat_embeddings.service import ChatEmbeddingJobService
from app.models.database import async_session_factory

logger = logging.getLogger(__name__)


async def run_worker(
    *,
    once: bool,
    limit: int,
    sleep_seconds: float,
    sweep: bool = True,
    backfill: bool = False,
    room_id: uuid.UUID | None = None,
) -> None:
    settings = get_settings()
    if not settings.ai_enable_chat_embeddings:
        logger.info("Chat embedding worker is disabled. Set AI_ENABLE_CHAT_EMBEDDINGS=true to run it.")
        return

    logger.info(
        "Chat embedding worker started (provider=%s model=%s mode=%s sleep=%ss limit=%s)",
        settings.ai_embedding_provider,
        settings.ai_embedding_model,
        "backfill" if backfill else ("once" if once else "continuous"),
        sleep_seconds,
        limit,
    )

    consecutive_errors = 0
    while True:
        try:
            enqueued, processed = await run_once(limit=limit, sweep=sweep, room_id=room_id)
            consecutive_errors = 0
        except Exception:
            # A tick-level failure (DB outage, provider down mid-claim) must not
            # kill a long-running worker. Back off and try again.
            consecutive_errors += 1
            backoff = min(sleep_seconds * (2 ** min(consecutive_errors, 5)), 600)
            logger.exception(
                "Worker tick failed (%s in a row); retrying in %.0fs", consecutive_errors, backoff
            )
            await asyncio.sleep(backoff)
            continue

        if backfill:
            if enqueued == 0 and processed == 0:
                logger.info("Backfill complete — nothing left to enqueue or process")
                return
            continue  # keep draining as fast as possible
        if once:
            return
        if not sweep and processed == 0:
            return  # no sweep means no new jobs can appear; drain and exit
        await asyncio.sleep(sleep_seconds)


async def run_once(
    *,
    limit: int,
    sweep: bool = True,
    room_id: uuid.UUID | None = None,
) -> tuple[int, int]:
    """One tick: sweep-enqueue, then claim and process. Returns (enqueued, processed)."""
    async with async_session_factory() as db:
        service = ChatEmbeddingJobService(db)

        enqueued = 0
        if sweep:
            enqueued = await service.enqueue_sweep(room_id=room_id)
            await db.commit()
            if enqueued:
                logger.info("Sweep enqueued %s chat embedding jobs", enqueued)

        jobs = await service.claim_pending_jobs(
            limit=limit,
            room_id=room_id,
            source_types=(SOURCE_MESSAGE_BATCH,) if room_id is not None else None,
        )
        if not jobs:
            await db.commit()
            return enqueued, 0

        logger.info("Claimed %s chat embedding jobs", len(jobs))
        processed = 0
        for job in jobs:
            try:
                await service.process_job(job)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                await service.job_repository.mark_failed(
                    job,
                    str(exc),
                    max_retries=service.max_retries,
                )
                await db.commit()
            processed += 1
            logger.info("Processed chat embedding job %s with status=%s", job.id, job.status)
        return enqueued, processed


def main() -> None:
    parser = argparse.ArgumentParser(prog="friend-hub-chat-embeddings-worker")
    parser.add_argument("--once", action="store_true", help="Run a single tick and exit")
    parser.add_argument("--limit", type=int, default=100, help="Maximum jobs to process per tick")
    parser.add_argument("--sleep-seconds", type=float, default=30, help="Delay between ticks in continuous mode")
    parser.add_argument("--no-sweep", action="store_true", help="Skip the enqueue sweep (process existing jobs only)")
    parser.add_argument("--backfill", action="store_true", help="Loop until all history is embedded, then exit (resumable)")
    parser.add_argument("--room-id", type=uuid.UUID, default=None, help="Restrict the sweep to one room")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(
        run_worker(
            once=args.once,
            limit=args.limit,
            sleep_seconds=args.sleep_seconds,
            sweep=not args.no_sweep,
            backfill=args.backfill,
            room_id=args.room_id,
        )
    )


if __name__ == "__main__":
    main()
