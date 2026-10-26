"""Tone catalog HTTP boundary."""

from fastapi import APIRouter, Depends

from src.api.dependencies import get_tone_catalog_service
from src.models.schemas import ToneCatalogResponse
from src.services.tone_catalog_service import ToneCatalogService

router = APIRouter(prefix="/tones", tags=["Tones"])


@router.get("", response_model=ToneCatalogResponse)
async def get_tones(
    service: ToneCatalogService = Depends(get_tone_catalog_service),
) -> ToneCatalogResponse:
    return await service.list_tones()
