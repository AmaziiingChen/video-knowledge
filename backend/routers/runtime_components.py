from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.runtime_components import download_model, install_browser, remove_model, runtime_components_status


router = APIRouter()


class ModelDownloadRequest(BaseModel):
    model: str
    backend: str


@router.get("/runtime-components")
def get_runtime_components():
    return runtime_components_status()


@router.post("/runtime-components/browser/install")
def install_runtime_browser():
    return install_browser()


@router.post("/runtime-components/models/download")
def download_runtime_model(req: ModelDownloadRequest):
    try:
        return download_model(req.model, req.backend)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/runtime-components/models")
def remove_runtime_model(req: ModelDownloadRequest):
    try:
        return remove_model(req.model, req.backend)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
