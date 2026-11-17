"""Schémas d'entrée/sortie de l'API."""

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models import as_utc

Severity = Literal["mineure", "majeure", "bloquante"]
Status = Literal["ouverte", "levee_declaree", "levee", "refusee"]
VisitKind = Literal["opr", "reception", "levee"]
Role = Literal["lecteur", "technicien", "ingenieur", "admin"]


def normalize_login(value: str) -> str:
    """Téléphone -> chiffres seuls ; e-mail -> minuscules. Refuse le reste."""
    v = value.strip()
    if "@" in v:
        v = v.lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError("Adresse e-mail invalide")
        return v
    digits = "".join(c for c in v if c.isdigit())
    if len(digits) < 8:
        raise ValueError("Entrez un numéro de téléphone ou une adresse e-mail")
    return digits


class RegisterIn(BaseModel):
    """Inscription en trois champs. Le nom d'entreprise est facultatif."""

    name: str = Field(min_length=1)
    login: str
    password: str = Field(min_length=6)
    cabinet: str = ""

    _login = field_validator("login")(normalize_login)


class LoginIn(BaseModel):
    login: str
    password: str


class MemberIn(BaseModel):
    name: str = Field(min_length=1)
    login: str
    password: str = Field(min_length=6)
    role: Role = "technicien"

    _login = field_validator("login")(normalize_login)


class OrgUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    registration_no: str | None = None


class CreditIn(BaseModel):
    """Appelé par le serveur de paiement (Mobile Money) une fois la recharge confirmée."""

    org_id: str
    amount_fcfa: int = Field(gt=0)
    reference: str = Field(min_length=1)


class ProjectIn(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1)
    client: str = ""
    location: str = ""


class CompanyIn(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1)
    lot: str = "autre"
    contact_name: str = ""
    phone: str = ""


class VisitIn(BaseModel):
    id: str | None = None
    kind: VisitKind = "opr"
    visit_date: date | None = None
    inspector: str = ""
    notes: str = ""


class ReserveIn(BaseModel):
    """Corps d'un PUT /reserves/{id} : création ou mise à jour, rejouable sans risque."""

    project_id: str
    visit_id: str | None = None
    company_id: str | None = None
    location: str = ""
    lot: str = "autre"
    description: str = ""
    action: str = ""
    severity: Severity = "mineure"
    status: Status = "ouverte"
    transcript: str = ""
    due_date: date | None = None
    updated_at: datetime | None = None  # horloge du téléphone, pour arbitrer les conflits
    deleted: bool = False

    @field_validator("updated_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return as_utc(v)


class SyncReserve(ReserveIn):
    id: str


class SyncPush(BaseModel):
    reserves: list[SyncReserve] = []


class StatusChange(BaseModel):
    status: Status


class StructureIn(BaseModel):
    text: str = Field(min_length=1)


class ReserveDraft(BaseModel):
    """Proposition de l'IA à partir d'une note vocale ; l'ingénieur valide toujours."""

    location: str = ""
    lot: str = "autre"
    description: str = ""
    action: str = ""
    severity: Severity = "mineure"
    provider: str = ""


class DispatchIn(BaseModel):
    company_ids: list[str] | None = None  # None = toutes les entreprises ayant des réserves ouvertes
    send: bool = True  # False = prévisualiser seulement (message + lien wa.me)
