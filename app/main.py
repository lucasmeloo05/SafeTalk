from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine
from app.routers.users import router as users_router

app = FastAPI(
    title="Plataforma TCC API",
    description="API da plataforma de comunicação com foco em segurança.",
    version="0.1.0",
)

app.include_router(users_router)

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
