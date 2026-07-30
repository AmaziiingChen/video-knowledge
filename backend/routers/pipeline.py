from fastapi import APIRouter

from services.pipeline_runner import PipelineRequest, PipelineResponse, run_pipeline_sync


router = APIRouter()


@router.post("/pipeline/run", response_model=PipelineResponse)
def run_pipeline(req: PipelineRequest):
    payload = req.model_dump(
        exclude={
            "priority",
            "execution_mode",
            "local_document_path",
            "local_document_kind",
                "cover_title",
                "cover_digest",
                "cover_visual_brief",
                "source_sync_request",
            }
    )
    return run_pipeline_sync(**payload)
