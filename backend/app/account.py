"""Compte : inscription, connexion, membres, identité de l'espace, crédits IA, consommation, offres."""

import hashlib
import io
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from sqlmodel import Session, func, select

from app.auth import current_user, hash_password, make_token, min_role, verify_password
from app.billing import credit, fcfa
from app.config import get_settings
from app.db import get_session
from app import notify, ratelimit
from app.models import Media, Organization, Project, Reserve, ResetCode, UsageLog, User, WalletTx, now
from app.plans import MB, PLANS, check_can_add_member, plan_of, public_plans, storage_used
from app.subscriptions import subscription_view
from app.schemas import CreditIn, LoginIn, MemberIn, OrgUpdate, RegisterIn, normalize_login

router = APIRouter(prefix="/api")


def _org_out(org: Organization) -> dict:
    data = org.model_dump(exclude={"balance_mfcfa", "logo_filename"})
    plan = org.plan if org.plan in PLANS else "gratuit"
    return {**data, "plan": plan, "plan_label": PLANS[plan]["label"], "balance_fcfa": fcfa(org.balance_mfcfa),
            "has_logo": bool(org.logo_filename)}


def _user_out(u: User) -> dict:
    return {**u.model_dump(exclude={"password_hash"}), "is_staff": u.login in get_settings().admin_logins}


def _session(db: Session, user: User) -> dict:
    return {"token": make_token(user), "user": _user_out(user), "org": _org_out(db.get(Organization, user.org_id))}


# ---------- inscription et connexion ----------

MAX_FAILED_LOGINS = 8  # par identifiant, sur 15 minutes
MAX_CODE_ATTEMPTS = 5


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_session)) -> dict:
    """Crée le compte et son espace personnel, avec un crédit IA de bienvenue. Rien d'autre à configurer."""
    ratelimit.hit(f"register:{ratelimit.client_ip(request)}", 20, 3600)
    if db.exec(select(User).where(User.login == body.login)).first():
        raise HTTPException(409, "Un compte existe déjà avec cet identifiant")
    is_email = "@" in body.login
    org = Organization(name=body.cabinet.strip() or body.name.strip(),
                       email=body.login if is_email else "",
                       phone="" if is_email else f"+{notify.international(body.login, get_settings())}")
    db.add(org)
    db.flush()
    user = User(org_id=org.id, login=body.login, name=body.name.strip(), role="admin",
                password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    welcome = get_settings().welcome_credit_fcfa
    if welcome > 0:
        credit(db, org, welcome * 1000, "bonus", f"bienvenue:{org.id}")
    db.refresh(user)
    return _session(db, user)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_session)) -> dict:
    ratelimit.hit(f"login-ip:{ratelimit.client_ip(request)}", 30, 300)
    try:
        ident = normalize_login(body.login)
    except ValueError:
        ident = ""
    # Trop d'échecs sur ce compte : on bloque même le bon mot de passe pendant un quart d'heure.
    if ident and ratelimit.blocked(f"login-fail:{ident}", MAX_FAILED_LOGINS, 900):
        raise HTTPException(429, "Trop de tentatives sur ce compte. Réessayez dans 15 minutes ou utilisez « Mot de passe oublié ».")
    user = db.exec(select(User).where(User.login == ident)).first() if ident else None
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        if ident:
            ratelimit.record(f"login-fail:{ident}")
        raise HTTPException(401, "Identifiant ou mot de passe incorrect")
    ratelimit.clear(f"login-fail:{ident}")
    return _session(db, user)


# ---------- mot de passe oublié ----------

class ForgotIn(BaseModel):
    login: str


class ResetIn(BaseModel):
    login: str
    code: str
    password: str = Field(min_length=6)


def _hash_code(code: str) -> str:
    return hashlib.sha256(f"{get_settings().secret_key}:{code}".encode()).hexdigest()


def issue_reset_code(db: Session, user: User) -> str:
    """Crée un code à 6 chiffres pour ce compte ; les codes précédents sont annulés."""
    for old in db.exec(select(ResetCode).where(ResetCode.user_id == user.id, ResetCode.used == False)).all():  # noqa: E712
        old.used = True
        db.add(old)
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(ResetCode(user_id=user.id, code_hash=_hash_code(code),
                     expires_at=now() + timedelta(minutes=get_settings().reset_code_minutes)))
    db.commit()
    return code


@router.post("/auth/forgot")
def forgot(body: ForgotIn, request: Request, db: Session = Depends(get_session)) -> dict:
    """Envoie un code par SMS ou e-mail. La réponse est la même que le compte existe ou non."""
    ratelimit.hit(f"forgot-ip:{ratelimit.client_ip(request)}", 10, 3600)
    try:
        ident = normalize_login(body.login)
    except ValueError:
        raise HTTPException(422, "Entrez votre numéro de téléphone ou votre adresse e-mail") from None
    ratelimit.hit(f"forgot:{ident}", 3, 900)
    delivery = notify.delivery_for(ident)
    user = db.exec(select(User).where(User.login == ident, User.active == True)).first()  # noqa: E712
    if user:
        notify.send_code(ident, issue_reset_code(db, user))
    return {"ok": True, "delivery": delivery, "minutes": get_settings().reset_code_minutes}


@router.post("/auth/reset")
def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_session)) -> dict:
    """Change le mot de passe avec le code reçu, puis connecte. Le code est grillé après 5 essais ratés."""
    ratelimit.hit(f"reset-ip:{ratelimit.client_ip(request)}", 30, 900)
    try:
        ident = normalize_login(body.login)
    except ValueError:
        ident = ""
    user = db.exec(select(User).where(User.login == ident, User.active == True)).first() if ident else None  # noqa: E712
    row = db.exec(select(ResetCode).where(ResetCode.user_id == user.id, ResetCode.used == False)  # noqa: E712
                  .order_by(ResetCode.created_at.desc())).first() if user else None
    invalid = HTTPException(400, "Code incorrect ou expiré. Demandez-en un nouveau.")
    if row is None or row.expires_at <= now() or row.attempts >= MAX_CODE_ATTEMPTS:
        raise invalid
    if not secrets.compare_digest(row.code_hash, _hash_code(body.code.strip())):
        row.attempts += 1
        db.add(row)
        db.commit()
        raise invalid
    row.used = True
    user.password_hash = hash_password(body.password)
    db.add(row)
    db.add(user)
    db.commit()
    ratelimit.clear(f"login-fail:{ident}")
    return _session(db, user)


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict:
    return {"user": _user_out(user), "org": _org_out(db.get(Organization, user.org_id))}


# ---------- identité du cabinet (reprise en en-tête des rapports) ----------

@router.patch("/org")
def update_org(body: OrgUpdate, user: User = Depends(min_role("admin")), db: Session = Depends(get_session)) -> dict:
    org = db.get(Organization, user.org_id)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(org, key, value)
    db.add(org)
    db.commit()
    db.refresh(org)
    return _org_out(org)


@router.put("/org/logo")
async def put_logo(file: UploadFile = File(...), user: User = Depends(min_role("admin")),
                   db: Session = Depends(get_session)) -> dict:
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(await file.read())).convert("RGBA")
    except Exception:
        raise HTTPException(422, "Image illisible") from None
    img.thumbnail((600, 600))
    org = db.get(Organization, user.org_id)
    org.logo_filename = f"logo-{org.id}.png"
    img.save(get_settings().media_dir / org.logo_filename, "PNG")
    db.add(org)
    db.commit()
    return _org_out(org)


@router.get("/org/logo")
def get_logo(user: User = Depends(current_user), db: Session = Depends(get_session)) -> FileResponse:
    org = db.get(Organization, user.org_id)
    if not org.logo_filename:
        raise HTTPException(404, "Aucun logo")
    return FileResponse(get_settings().media_dir / org.logo_filename, media_type="image/png")


# ---------- membres ----------

@router.get("/org/members")
def list_members(user: User = Depends(current_user), db: Session = Depends(get_session)) -> list[dict]:
    rows = db.exec(select(User).where(User.org_id == user.org_id).order_by(User.created_at)).all()
    return [_user_out(u) for u in rows]


@router.post("/org/members", status_code=201)
def add_member(body: MemberIn, user: User = Depends(min_role("admin")), db: Session = Depends(get_session)) -> dict:
    if db.exec(select(User).where(User.login == body.login)).first():
        raise HTTPException(409, "Un compte existe déjà avec cet identifiant")
    check_can_add_member(db, db.get(Organization, user.org_id))
    member = User(org_id=user.org_id, login=body.login, name=body.name.strip(), role=body.role,
                  password_hash=hash_password(body.password))
    db.add(member)
    db.commit()
    db.refresh(member)
    return _user_out(member)


@router.delete("/org/members/{member_id}")
def deactivate_member(member_id: str, user: User = Depends(min_role("admin")),
                      db: Session = Depends(get_session)) -> dict:
    member = db.get(User, member_id)
    if not member or member.org_id != user.org_id:
        raise HTTPException(404, "Membre introuvable")
    if member.id == user.id:
        raise HTTPException(409, "Vous ne pouvez pas désactiver votre propre compte")
    member.active = False
    db.add(member)
    db.commit()
    return _user_out(member)


# ---------- offres et consommation ----------

@router.get("/plans")
def plans() -> list[dict]:
    """Public : les offres affichées sur le site et dans l'application."""
    return public_plans()


@router.get("/account/usage")
def account_usage(user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict:
    """Compteurs de consommation : stockage, rapports, membres, IA. Affichés dans « Mon compte »."""
    org = db.get(Organization, user.org_id)
    plan = plan_of(org)
    month_start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def ai(*where) -> dict:
        calls, spent, tok_in, tok_out, audio = db.exec(
            select(func.count(), func.coalesce(func.sum(UsageLog.charged_mfcfa), 0),
                   func.coalesce(func.sum(UsageLog.input_tokens), 0), func.coalesce(func.sum(UsageLog.output_tokens), 0),
                   func.coalesce(func.sum(UsageLog.audio_seconds), 0)).where(UsageLog.org_id == org.id, *where)).one()
        return {"calls": calls, "spent_fcfa": fcfa(spent), "tokens": tok_in + tok_out, "audio_minutes": round(audio / 60, 1)}

    in_org = select(func.count()).select_from(Reserve).join(Project, Project.id == Reserve.project_id).where(Project.org_id == org.id)
    photos = db.exec(select(func.count()).select_from(Media).join(Reserve, Reserve.id == Media.reserve_id)
                     .join(Project, Project.id == Reserve.project_id).where(Project.org_id == org.id)).one()
    return {
        "plan": {"key": org.plan if org.plan in PLANS else "gratuit", "label": plan["label"], "price_fcfa": plan["price_fcfa"]},
        "subscription": subscription_view(db, org),
        "storage": {"used_bytes": storage_used(db, org.id), "limit_bytes": plan["storage_mb"] * MB if plan["storage_mb"] else None},
        "reports": {"used": db.exec(select(func.count()).select_from(Project).where(Project.org_id == org.id)).one(),
                    "limit": plan["max_reports"]},
        "members": {"used": db.exec(select(func.count()).select_from(User).where(User.org_id == org.id, User.active == True)).one(),  # noqa: E712
                    "limit": plan["max_members"]},
        "defects": db.exec(in_org.where(Reserve.deleted == False)).one(),  # noqa: E712
        "defects_fixed": db.exec(in_org.where(Reserve.deleted == False, Reserve.status == "levee")).one(),  # noqa: E712
        "photos": photos,
        "ai": {"balance_fcfa": fcfa(org.balance_mfcfa), "month": ai(UsageLog.created_at >= month_start), "total": ai()},
    }


# ---------- crédits IA ----------

@router.get("/billing/wallet")
def wallet(user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict:
    """Solde, recharges, et consommation détaillée : le cabinet voit exactement ce qu'il paie."""
    org = db.get(Organization, user.org_id)
    calls, spent, tok_in, tok_out, audio = db.exec(
        select(func.count(), func.coalesce(func.sum(UsageLog.charged_mfcfa), 0),
               func.coalesce(func.sum(UsageLog.input_tokens), 0), func.coalesce(func.sum(UsageLog.output_tokens), 0),
               func.coalesce(func.sum(UsageLog.audio_seconds), 0)).where(UsageLog.org_id == org.id)).one()
    txs = db.exec(select(WalletTx).where(WalletTx.org_id == org.id).order_by(WalletTx.created_at.desc()).limit(50)).all()
    logs = db.exec(select(UsageLog).where(UsageLog.org_id == org.id).order_by(UsageLog.created_at.desc()).limit(100)).all()
    return {
        "balance_fcfa": fcfa(org.balance_mfcfa),
        "totals": {"calls": calls, "spent_fcfa": fcfa(spent), "input_tokens": tok_in, "output_tokens": tok_out,
                   "audio_minutes": round(audio / 60, 2)},
        "credits": [{"kind": t.kind, "amount_fcfa": fcfa(t.amount_mfcfa), "reference": t.reference,
                     "balance_after_fcfa": fcfa(t.balance_after_mfcfa), "created_at": t.created_at} for t in txs],
        "usage": [{"kind": u.kind, "model": u.model, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                   "audio_seconds": u.audio_seconds, "charged_fcfa": fcfa(u.charged_mfcfa),
                   "created_at": u.created_at} for u in logs],
    }


@router.post("/billing/credit")
def add_credit(body: CreditIn, x_billing_secret: str = Header(default=""), db: Session = Depends(get_session)) -> dict:
    """Recharge. Réservée au serveur de paiement : à appeler depuis le webhook Mobile Money,
    jamais depuis l'application. Rejouer la même référence ne crédite qu'une fois."""
    expected = get_settings().billing_secret
    if not expected or not secrets.compare_digest(x_billing_secret, expected):
        raise HTTPException(403, "Recharge non autorisée")
    org = db.get(Organization, body.org_id)
    if not org:
        raise HTTPException(404, "Cabinet introuvable")
    tx = credit(db, org, body.amount_fcfa * 1000, "recharge", body.reference)
    db.refresh(org)
    return {"balance_fcfa": fcfa(org.balance_mfcfa), "credited_fcfa": fcfa(tx.amount_mfcfa)}
