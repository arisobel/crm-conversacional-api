from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(tags=["Operational"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "crm-conversacional-api"}


@router.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        request.app.logger.warning("database readiness failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from error
    return {"status": "ok", "service": "crm-conversacional-api"}

