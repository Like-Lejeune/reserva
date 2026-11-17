"""Administration de la plateforme (nous, pas les clients).

Accès : les identifiants listés dans RESERVA_ADMIN_LOGINS. Rien à voir avec le rôle « admin »
d'un espace, qui ne gère que son propre espace.
"""

from collections import Counter
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select

from app.auth import current_user
from app.billing import credit, fcfa
from app.config import get_settings
from app.db import get_session
from app.models import Media, Organization, Payment, Project, PromoCode, Reserve, UsageLog, User, WalletTx, now
from app.plans import PLANS, plan_of, refresh_plan, storage_used
from app.subscriptions import _payment_out, activate, active_subscription, settle

router = APIRouter(prefix="/api/admin")


def is_staff(user: User) -> bool:
    return user.login in get_settings().admin_logins


def staff(user: User = Depends(current_user)) -> User:
    if not is_staff(user):
        raise HTTPException(404, "Route inconnue")  # on ne révèle pas l'existence de l'administration
    return user


class AccountPatch(BaseModel):
    plan: str | None = None
    months: int | None = Field(default=1, ge=0, le=60)  # durée offerte ; 0 = sans échéance
    suspended: bool | None = None


class PromoIn(BaseModel):
    code: str = Field(min_length=3, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    percent_off: int = Field(ge=1, le=100)
    max_uses: int | None = Field(default=None, ge=1)
    valid_days: int | None = Field(default=None, ge=1, le=730)


class SettleIn(BaseModel):
    success: bool


class GrantIn(BaseModel):
    amount_fcfa: int = Field(gt=0, le=1_000_000)
    note: str = ""


def _months_from_now(months: int):
    from app.subscriptions import add_months

    return add_months(now(), months)


def _count(db: Session, model, *where) -> int:
    return db.exec(select(func.count()).select_from(model).where(*where)).one()


def _daily(dates: list, days: int) -> list[dict]:
    """Série continue des `days` derniers jours, zéros compris."""
    today = now().date()
    hits = Counter(d.date() for d in dates)
    return [{"date": (day := today - timedelta(days=i)).isoformat(), "count": hits.get(day, 0)}
            for i in range(days - 1, -1, -1)]


@router.get("/overview")
def overview(_: User = Depends(staff), db: Session = Depends(get_session)) -> dict:
    since = now() - timedelta(days=30)
    orgs = db.exec(select(Organization)).all()
    for org in orgs:
        refresh_plan(db, org)  # les abonnements échus sortent du décompte
    month_start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    paid = db.exec(select(Payment).where(Payment.status == "reussi")).all()
    paying = [o for o in orgs if not o.suspended and plan_of(o)["price_fcfa"] > 0
              and (sub := active_subscription(db, o)) is not None and sub.source == "paiement"]
    calls, charged, cost = db.exec(select(func.count(), func.coalesce(func.sum(UsageLog.charged_mfcfa), 0),
                                          func.coalesce(func.sum(UsageLog.cost_mfcfa), 0))).one()
    sold = db.exec(select(func.coalesce(func.sum(WalletTx.amount_mfcfa), 0)).where(WalletTx.kind == "recharge")).one()
    given = db.exec(select(func.coalesce(func.sum(WalletTx.amount_mfcfa), 0)).where(WalletTx.kind != "recharge")).one()
    signups = db.exec(select(Organization.created_at).where(Organization.created_at >= since)).all()
    ai_days = db.exec(select(UsageLog.created_at).where(UsageLog.created_at >= since)).all()
    return {
        "accounts": len(orgs),
        "users": _count(db, User),
        "reports": _count(db, Project),
        "defects": _count(db, Reserve, Reserve.deleted == False),  # noqa: E712
        "photos": _count(db, Media),
        "storage_bytes": int(db.exec(select(func.coalesce(func.sum(Media.size), 0))).one()),
        "by_plan": {key: sum(1 for o in orgs if (o.plan if o.plan in PLANS else "gratuit") == key) for key in PLANS},
        # Revenu mensuel récurrent : seulement les abonnements réellement payés (ni essais, ni offres offertes).
        "monthly_revenue_fcfa": sum(plan_of(o)["price_fcfa"] for o in paying),
        "paying_accounts": len(paying),
        "collected_month_fcfa": sum(p.amount_fcfa for p in paid if p.created_at >= month_start),
        "collected_total_fcfa": sum(p.amount_fcfa for p in paid),
        "pending_payments": _count(db, Payment, Payment.status == "en_attente"),
        "ai": {"calls": calls, "charged_fcfa": fcfa(charged), "cost_fcfa": fcfa(cost), "margin_fcfa": fcfa(charged - cost),
               "credit_sold_fcfa": fcfa(sold), "credit_given_fcfa": fcfa(given)},
        "signups_30d": _daily(signups, 30),
        "ai_calls_30d": _daily(ai_days, 30),
    }


def _account_out(db: Session, org: Organization) -> dict:
    refresh_plan(db, org)
    owner = db.exec(select(User).where(User.org_id == org.id).order_by(User.created_at)).first()
    plan = plan_of(org)
    sub = active_subscription(db, org)
    return {
        "id": org.id, "name": org.name, "owner": owner.name if owner else "", "login": owner.login if owner else "",
        "plan": org.plan if org.plan in PLANS else "gratuit", "plan_label": plan["label"], "suspended": org.suspended,
        "plan_until": org.plan_until, "plan_source": sub.source if sub else "",
        "balance_fcfa": fcfa(org.balance_mfcfa), "created_at": org.created_at,
        "members": _count(db, User, User.org_id == org.id, User.active == True),  # noqa: E712
        "reports": _count(db, Project, Project.org_id == org.id),
        "storage_bytes": storage_used(db, org.id),
        "storage_limit_bytes": plan["storage_mb"] * 1024 * 1024 if plan["storage_mb"] else None,
        "ai_spent_fcfa": fcfa(db.exec(select(func.coalesce(func.sum(UsageLog.charged_mfcfa), 0))
                                      .where(UsageLog.org_id == org.id)).one()),
    }


@router.get("/accounts")
def accounts(q: str = "", _: User = Depends(staff), db: Session = Depends(get_session)) -> list[dict]:
    rows = [_account_out(db, o) for o in db.exec(select(Organization).order_by(Organization.created_at.desc())).all()]
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows if needle in f"{r['name']} {r['owner']} {r['login']}".lower()]
    return rows[:500]


@router.patch("/accounts/{org_id}")
def patch_account(org_id: str, body: AccountPatch, _: User = Depends(staff), db: Session = Depends(get_session)) -> dict:
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Compte introuvable")
    if body.plan is not None:
        if body.plan not in PLANS:
            raise HTTPException(422, f"Offre inconnue : {body.plan}")
        if PLANS[body.plan]["price_fcfa"] == 0:
            org.plan_until = now()  # retour immédiat en Gratuit
            db.add(org)
            db.commit()
            refresh_plan(db, org)
            org.plan, org.plan_until = "gratuit", None
        else:
            # Offre accordée à la main (virement, geste commercial) : tracée comme telle, avec sa durée.
            months = body.months or 0
            org.plan_until = None  # repart d'aujourd'hui plutôt que de prolonger
            activate(db, org, body.plan, "mois", "admin", ends_at=None if months == 0 else _months_from_now(months),
                     open_ended=months == 0)
    if body.suspended is not None:
        org.suspended = body.suspended
    db.add(org)
    db.commit()
    db.refresh(org)
    return _account_out(db, org)


@router.post("/accounts/{org_id}/credit")
def grant_credit(org_id: str, body: GrantIn, user: User = Depends(staff), db: Session = Depends(get_session)) -> dict:
    """Crédit IA offert (geste commercial, correction). Tracé avec l'auteur et le motif."""
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Compte introuvable")
    credit(db, org, body.amount_fcfa * 1000, "geste", f"admin:{user.login}:{body.note[:60]}:{uuid4().hex[:8]}")
    db.refresh(org)
    return _account_out(db, org)


@router.post("/accounts/{org_id}/reset-code")
def reset_code(org_id: str, _: User = Depends(staff), db: Session = Depends(get_session)) -> dict:
    """Génère un code de réinitialisation pour le responsable du compte, à lui dicter au téléphone
    après avoir vérifié son identité. Sert quand ni SMS ni e-mail ne sont configurés, ou n'arrivent pas."""
    from app.account import issue_reset_code

    owner = db.exec(select(User).where(User.org_id == org_id, User.active == True).order_by(User.created_at)).first()  # noqa: E712
    if not owner:
        raise HTTPException(404, "Compte introuvable")
    return {"login": owner.login, "code": issue_reset_code(db, owner), "minutes": get_settings().reset_code_minutes}


# ---------- paiements ----------

@router.get("/payments")
def payments(status: str = "", _: User = Depends(staff), db: Session = Depends(get_session)) -> list[dict]:
    q = select(Payment).order_by(Payment.created_at.desc()).limit(300)
    if status:
        q = q.where(Payment.status == status)
    names = {o.id: o.name for o in db.exec(select(Organization)).all()}
    return [{**_payment_out(p), "account": names.get(p.org_id, ""), "phone": p.phone, "operator": p.operator,
             "reference": p.external_reference, "promo_code": p.promo_code} for p in db.exec(q).all()]


@router.post("/payments/{payment_id}/settle")
def settle_payment(payment_id: str, body: SettleIn, user: User = Depends(staff), db: Session = Depends(get_session)) -> dict:
    """Tranche à la main un paiement resté en attente, après vérification chez l'agrégateur."""
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(404, "Paiement introuvable")
    if payment.status != "en_attente":
        raise HTTPException(409, "Ce paiement est déjà réglé")
    return _payment_out(settle(db, payment, body.success, f"Tranché à la main par {user.login}"))


# ---------- codes promo ----------

def _promo_out(p: PromoCode) -> dict:
    usable = p.active and (p.expires_at is None or p.expires_at > now()) and (p.max_uses is None or p.used < p.max_uses)
    return {**p.model_dump(), "usable": usable}


@router.get("/promos")
def promos(_: User = Depends(staff), db: Session = Depends(get_session)) -> list[dict]:
    return [_promo_out(p) for p in db.exec(select(PromoCode).order_by(PromoCode.created_at.desc())).all()]


@router.post("/promos", status_code=201)
def create_promo(body: PromoIn, _: User = Depends(staff), db: Session = Depends(get_session)) -> dict:
    code = body.code.upper()
    if db.get(PromoCode, code):
        raise HTTPException(409, "Ce code existe déjà")
    promo = PromoCode(code=code, percent_off=body.percent_off, max_uses=body.max_uses,
                      expires_at=now() + timedelta(days=body.valid_days) if body.valid_days else None)
    db.add(promo)
    db.commit()
    db.refresh(promo)
    return _promo_out(promo)


@router.delete("/promos/{code}")
def disable_promo(code: str, _: User = Depends(staff), db: Session = Depends(get_session)) -> dict:
    promo = db.get(PromoCode, code.upper())
    if not promo:
        raise HTTPException(404, "Code introuvable")
    promo.active = False
    db.add(promo)
    db.commit()
    return _promo_out(promo)
