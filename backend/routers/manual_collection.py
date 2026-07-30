from fastapi import APIRouter
from pydantic import BaseModel

from services.manual_collection_settings import manual_collection_settings, save_manual_collection_settings


router = APIRouter()


class ManualCollectionSettingsRequest(BaseModel):
    auto_summarize: bool = True


@router.get("/manual-collection/settings")
def get_manual_collection_settings():
    return manual_collection_settings()


@router.put("/manual-collection/settings")
def put_manual_collection_settings(req: ManualCollectionSettingsRequest):
    return save_manual_collection_settings(auto_summarize=req.auto_summarize)
