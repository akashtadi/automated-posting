"""FastAPI app & routes."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.platforms import ALL_PLATFORMS
from app.schemas import (
    PostingResponse,
    PostRequest,
    PostStatus,
    ValidationErrorDetail,
    ValidationErrorResponse,
)
from app.services.posting_service import PostingService


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx/httpcore log full request URLs at INFO; keep them quiet so nothing sensitive is logged.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


configure_logging(get_settings().log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.dry_run:
        logger.warning("DRY_RUN is enabled: posts are simulated and nothing is published")
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        app.state.http_client = client
        yield


app = FastAPI(
    title="Automated Multi-Platform Posting System",
    description="Posts a single message to LinkedIn, X, Facebook, Instagram and Reddit automatically.",
    version="1.1.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"] if p != "body") or "body"
        message = str(err["msg"]).removeprefix("Value error, ")
        errors.append(ValidationErrorDetail(field=field, message=message))
    return JSONResponse(status_code=422, content=ValidationErrorResponse(errors=errors).model_dump())


def get_posting_service(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> PostingService:
    client: httpx.AsyncClient = request.app.state.http_client
    platforms = [cls(settings, client) for cls in ALL_PLATFORMS]
    return PostingService(platforms, timeout_seconds=settings.request_timeout_seconds)


@app.get("/health")
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, object]:
    return {"status": "ok", "dry_run": settings.dry_run}


@app.post(
    "/posting",
    response_model=PostingResponse,
    responses={422: {"model": ValidationErrorResponse, "description": "Invalid message"}},
)
async def create_posting(
    payload: PostRequest,
    service: Annotated[PostingService, Depends(get_posting_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PostingResponse:
    results = await service.post_to_all(payload.message, payload.cta_link)
    return PostingResponse(
        success=any(r.status == PostStatus.SUCCESS for r in results),
        dry_run=settings.dry_run,
        results=results,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=4000, reload=True)
