from fastapi import APIRouter

from services.update_checker import check_for_update
from services.telemetry import record as record_telemetry


router = APIRouter()


@router.get("/updates/check")
def check_updates() -> dict[str, object]:
    """Return update availability; downloading always remains user initiated."""
    status = check_for_update()
    record_telemetry("update_check_completed", {"result": str(status.get("state") or "unknown")[:40]})
    return status
