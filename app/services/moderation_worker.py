"""Poll the durable moderation outbox outside request and DB transactions."""

import asyncio
import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.services.moderation_analysis_service import process_next_analysis_job


logger = logging.getLogger(__name__)


async def run_moderation_worker(client: Any, poll_seconds: float) -> None:
    logger.info("Moderation worker loop started.")
    while True:
        try:
            processed = await asyncio.to_thread(
                process_next_analysis_job,
                SessionLocal,
                client,
            )
        except SQLAlchemyError:
            # Do not log exception text, SQL parameters, or private content.
            logger.warning("Moderation outbox database operation failed.")
            processed = False
        if not processed:
            await asyncio.sleep(poll_seconds)
