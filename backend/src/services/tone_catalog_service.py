"""Read-through cached access to the writing-tone catalog."""

from typing import Any

from src.config.logging_config import get_logger
from src.models.repositories.tone_catalog_repository import ToneCatalogRepository
from src.models.schemas import ToneCatalogResponse, ToneOptionResponse

logger = get_logger(__name__)
TONE_CATALOG_CACHE_KEY = "catalog:tones:v1"
TONE_CATALOG_CACHE_TTL_SECONDS = 48 * 60 * 60


class ToneCatalogService:
    def __init__(self, session: Any, redis_client: Any) -> None:
        self._repository = ToneCatalogRepository(session)
        self._redis = redis_client

    async def list_tones(self) -> ToneCatalogResponse:
        try:
            cached = await self._redis.get(TONE_CATALOG_CACHE_KEY)
            if cached:
                return ToneCatalogResponse.model_validate_json(cached)
        except ValueError as exc:
            logger.warning("tone_catalog_cache_invalid", error=str(exc))
        except Exception as exc:
            logger.warning("tone_catalog_cache_read_failed", error=str(exc))

        response = ToneCatalogResponse(
            items=[
                ToneOptionResponse(
                    value=tone.value.value,
                    label=tone.label,
                    description=tone.description,
                )
                for tone in await self._repository.list_tones()
            ]
        )
        try:
            await self._redis.set(
                TONE_CATALOG_CACHE_KEY,
                response.model_dump_json(),
                ex=TONE_CATALOG_CACHE_TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning("tone_catalog_cache_write_failed", error=str(exc))
        return response
