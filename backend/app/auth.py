"""Authentification, rôles et liens de partage signés.

- Session : jeton JWT dans l'en-tête Authorization: Bearer.
- Rôles ordonnés : lecteur < technicien < ingenieur < admin. `min_role("ingenieur")` laisse
  passer l'ingénieur et l'admin.
- Lien de partage : jeton signé, limité à un chantier (et une entreprise), sans compte.
"""

import hashlib
import hmac
import os
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from app.config import get_settings
from app.db import get_session
from app.models import ROLES, Organization, User, now
from app.plans import refresh_plan

_bearer = HTTPBearer(auto_error=False)
_ALGO = "HS256"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        check = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    except ValueError:
        return False
    return hmac.compare_digest(check.hex(), digest)


def _encode(payload: dict, days: int) -> str:
    return jwt.encode({**payload, "exp": now() + timedelta(days=days)}, get_settings().secret_key, algorithm=_ALGO)


def _decode(token: str, scope: str) -> dict:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=[_ALGO])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session ou lien invalide ou expiré") from None
    if data.get("scope") != scope:
        raise HTTPException(401, "Session ou lien invalide ou expiré")
    return data


def make_token(user: User) -> str:
    return _encode({"scope": "user", "sub": user.id}, get_settings().token_days)


def make_share_token(project_id: str, company_id: str | None) -> str:
    return _encode({"scope": "share", "project": project_id, "company": company_id}, get_settings().share_link_days)


def read_share_token(token: str) -> tuple[str, str | None]:
    data = _decode(token, "share")
    return data["project"], data.get("company")


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 db: Session = Depends(get_session)) -> User:
    if creds is None:
        raise HTTPException(401, "Connexion requise")
    user = db.get(User, _decode(creds.credentials, "user")["sub"])
    if not user or not user.active:
        raise HTTPException(401, "Compte introuvable ou désactivé")
    org = db.get(Organization, user.org_id)
    if org is None or org.suspended:
        raise HTTPException(403, "Ce compte est suspendu. Contactez-nous pour le réactiver.")
    refresh_plan(db, org)
    return user


def min_role(role: str):
    """Dépendance FastAPI : exige au moins ce rôle."""

    def dep(user: User = Depends(current_user)) -> User:
        if ROLES.get(user.role, -1) < ROLES[role]:
            raise HTTPException(403, f"Action réservée au rôle « {role} » ou supérieur")
        return user

    return dep
