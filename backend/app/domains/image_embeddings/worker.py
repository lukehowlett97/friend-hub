from __future__ import annotations

import argparse
import asyncio
import logging

from app.config import get_settings
from app.domains.image_embeddings.service import PhotoEmbeddingJobService
from app.models.database import async_session_factory


logger = logging.getLogger(__name__)


async def run_worker(
    *,
    once: bool,
    limit: int,
    sleep_seconds: float,
    device: str | None = None,
) -> None:
    settings = get_settings()
    if not settings.image_embeddings_enabled:
        logger.info("Image embedding worker is disabled. Set IMAGE_EMBEDDINGS_ENABLED=true to run it.")
        return
    if device:
        settings.image_embeddings_device = device

    while True:
        processed = await run_once(limit=limit)
        if once or processed == 0:
            return
        await asyncio.sleep(sleep_seconds)


async def run_once(*, limit: int) -> int:
    async with async_session_factory() as db:
        service = PhotoEmbeddingJobService(db)
        exhausted = await service.mark_exhausted_pending_jobs()
        if exhausted:
            await db.commit()
            logger.info("Marked %s exhausted embedding jobs as failed", exhausted)

        jobs = await service.claim_pending_jobs(limit=limit)
        if not jobs:
            await db.commit()
            logger.info("No pending image embedding jobs")
            return 0

        logger.info("Claimed %s image embedding jobs", len(jobs))
        processed = 0
        for job in jobs:
            try:
                await service.process_job(job)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                await service.repository.mark_failed(
                    job,
                    error=str(exc),
                    max_retries=service.settings.image_embeddings_max_retries,
                )
                await db.commit()
            processed += 1
            logger.info("Processed image embedding job %s with status=%s", job.id, job.status)
        return processed


def main() -> None:
    parser = argparse.ArgumentParser(prog="friend-hub-image-embeddings-worker")
    parser.add_argument("--once", action="store_true", help="Exit after one batch, or immediately when no jobs remain")
    parser.add_argument("--limit", type=int, default=100, help="Maximum jobs to process per batch")
    parser.add_argument("--sleep-seconds", type=float, default=5, help="Delay between batches in continuous mode")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default=None, help="Override IMAGE_EMBEDDINGS_DEVICE")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(
        run_worker(
            once=args.once,
            limit=args.limit,
            sleep_seconds=args.sleep_seconds,
            device=args.device,
        )
    )


if __name__ == "__main__":
    main()
