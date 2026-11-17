"""Point d'entrée : uvicorn app.main:app --reload

Un seul serveur fait tout : l'API sous /api et l'application mobile compilée (web/dist).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.account import router as account_router
from app.admin import router as admin_router
from app.api import router
from app.config import get_settings
from app.db import init_db
from app.subscriptions import router as subscriptions_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def check_production_settings() -> None:
    """En production, on refuse de démarrer avec un réglage qui ouvrirait une faille."""
    s = get_settings()
    if s.env != "production":
        return
    problems = []
    if s.secret_key == "a-changer-en-production" or len(s.secret_key) < 32:
        problems.append("RESERVA_SECRET_KEY doit être une valeur aléatoire d'au moins 32 caractères")
    if s.payment_simulation:
        problems.append("RESERVA_PAYMENT_SIMULATION doit être false (sinon tout paiement réussit sans débit)")
    if s.trustchange_api_key and not s.trustchange_webhook_secret:
        problems.append("RESERVA_TRUSTCHANGE_WEBHOOK_SECRET manque alors que le paiement est activé")
    if not s.public_base_url.startswith("https://"):
        problems.append("RESERVA_PUBLIC_BASE_URL doit commencer par https://")
    if problems:
        raise RuntimeError("Configuration de production refusée :\n- " + "\n- ".join(problems))


def create_app() -> FastAPI:
    check_production_settings()
    app = FastAPI(title="Reserva — rapports de finition", version="0.2.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins,
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(account_router)
    app.include_router(admin_router)
    app.include_router(subscriptions_router)
    app.include_router(router)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    web = get_settings().web_dir.resolve()
    if (web / "index.html").exists():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404, "Route inconnue")
            target = (web / path).resolve()
            if path and target.is_file() and web in target.parents:
                return FileResponse(target)
            return FileResponse(web / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
