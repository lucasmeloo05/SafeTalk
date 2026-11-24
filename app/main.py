
import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine
from app.routers.users import router as users_router
from app.routers.social import router as social_router
from app.routers.conversations import router as conversations_router
from app.routers.messages import router as messages_router
from app.routers.servers import router as servers_router
from app.routers.server_channels import router as server_channels_router
from app.routers.server_members import router as server_members_router
from app.routers.server_roles import router as server_roles_router
from app.routers.server_moderation import router as server_moderation_router
from app.routers.server_invites import router as server_invites_router
from app.routers.reports import router as reports_router
from app.routers.official_reports import router as official_reports_router
from app.routers.official_sanctions import router as official_sanctions_router
from app.services.moderation_analysis_service import create_openai_client
from app.services.moderation_worker import run_moderation_worker
from app.settings import settings


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker_task = None
    openai_client = None
    worker_enabled = settings.moderation_worker_enabled
    api_key_configured = bool(os.environ.get("OPENAI_API_KEY"))
    if not worker_enabled:
        logger.info("Moderation worker disabled; MODERATION_WORKER_ENABLED is not true.")
    if not api_key_configured:
        logger.warning("Moderation worker not started; OPENAI_API_KEY is not configured.")
    if worker_enabled and api_key_configured:
        openai_client = create_openai_client()
        worker_task = asyncio.create_task(
            run_moderation_worker(
                openai_client,
                settings.moderation_worker_poll_seconds,
            )
        )
        logger.info("Moderation worker task created by FastAPI lifespan.")
    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
        if openai_client is not None:
            openai_client.close()


app = FastAPI(
    title="Plataforma TCC API",
    description="API da plataforma de comunicação com foco em segurança.",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Expected-Permissions", "X-Expected-Channel-Grants"],
)

app.include_router(users_router)
app.include_router(social_router)
app.include_router(conversations_router)
app.include_router(messages_router)
app.include_router(servers_router)
app.include_router(server_channels_router)
app.include_router(server_members_router)
app.include_router(server_roles_router)
app.include_router(server_moderation_router)
app.include_router(server_invites_router)
app.include_router(reports_router)
app.include_router(official_reports_router)
app.include_router(official_sanctions_router)


@app.get("/")
def home():
    return {
        "mensagem": "API da Plataforma TCC funcionando!",
        "status": "online",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/health/database")
def database_health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected",
        }

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível conectar ao banco de dados.",
        )

from app.routers.two_factor import router as two_factor_router
app.include_router(two_factor_router)

from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def safe_two_factor_validation(request, exc):
    if request.url.path.startswith("/users/me/2fa") or request.url.path == "/users/login/2fa":
        return JSONResponse(status_code=422, content={"detail": "Confira os campos de autenticação informados."})
    return await request_validation_exception_handler(request, exc)
