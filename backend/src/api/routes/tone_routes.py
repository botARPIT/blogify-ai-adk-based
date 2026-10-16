"""Tone catalog API routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.logging_config import get_logger
from src.core.database import get_db_session
from src.core.redis_pool import get_redis_client
from src.models.repositories.tone_catalog_repository import ToneCatalogRepository
from src.models.schemas import ToneCatalogResponse, ToneOptionResponse

router = APIRouter(prefix="/tones", tags=["Tones"])
logger = get_logger(__name__)

TONE_CATALOG_CACHE_KEY = "catalog:tones:v1"
TONE_CATALOG_CACHE_TTL_SECONDS = 48 * 60 * 60


@router.get("", response_model=ToneCatalogResponse)
async def get_tones(session: AsyncSession = Depends(get_db_session)) -> ToneCatalogResponse:
    """Return the curated writing tones, using Redis as a 48-hour read-through cache."""
    redis_client = None
    try:
        redis_client = get_redis_client()
        cached = await redis_client.get(TONE_CATALOG_CACHE_KEY)
        if cached:
            try:
                return ToneCatalogResponse.model_validate_json(cached)
            except ValueError as exc:
                logger.warning("tone_catalog_cache_invalid", error=str(exc))
    except Exception as exc:
        # The database remains authoritative; a cache outage must not hide tone options.
        logger.warning("tone_catalog_cache_read_failed", error=str(exc))

    records = await ToneCatalogRepository(session).list_tones()
    response = ToneCatalogResponse(
        items=[
            ToneOptionResponse(
                value=tone.value.value,
                label=tone.label,
                description=tone.description,
            )
            for tone in records
        ]
    )

    if redis_client is not None:
        try:
            await redis_client.set(
                TONE_CATALOG_CACHE_KEY,
                response.model_dump_json(),
                ex=TONE_CATALOG_CACHE_TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning("tone_catalog_cache_write_failed", error=str(exc))

    return response
