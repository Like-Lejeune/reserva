"""Abonnements et paiements Mobile Money.

Règles :
- Un abonnement a une période (mois ou an) et une échéance. À l'échéance, l'espace repasse
  en Gratuit tout seul (app/plans.py : refresh_plan). Rien n'est supprimé.
- Le Mobile Money ne permet pas de prélèvement automatique : renouveler = payer de nouveau.
  Renouveler avant l'échéance prolonge à partir de l'échéance, aucun jour n'est perdu.
- Passer à une offre supérieure en cours de période : les jours restants déjà payés sont déduits.
- Un essai gratuit par espace. Les codes promo réduisent le premier paiement comme les suivants.
- Un paiement n'est jamais compté deux fois : `settle` ne fait rien sur un paiement déjà réglé.

Le serveur de paiement nous prévient par webhook ; l'application interroge aussi l'état du
paiement pendant que l'utilisateur valide sur son téléphone. Les deux chemins aboutissent à `settle`.
"""

import calendar
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app import trustchange
from app.auth import current_user, min_role
from app.billing import credit
from app.config import get_settings
from app.db import get_session
from app.models import Organization, Payment, PromoCode, Subscription, User, new_id, now
from app.plans import PLANS, plan_of

router = APIRouter(prefix="/api")

PERIODS = {"mois": (1, "price_fcfa", "1 mois"), "an": (12, "price_year_fcfa", "1 an")}
MIN_AMOUNT_FCFA = 100
SUCCESS = {"SUCCESS", "SUCCESSFUL", "SUCCEEDED", "COMPLETED", "COMPLETE", "PAID", "CONFIRMED"}
FAILURE = {"FAILED", "FAILURE", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED", "REFUSED", "ERROR", "REVERSED"}


class CheckoutIn(BaseModel):
    plan: str
    period: str = "mois"
    phone: str = ""
    operator: str = ""
    promo_code: str = ""


class TopupIn(BaseModel):
    amount_fcfa: int = Field(gt=0, le=500_000)
    phone: str
    operator: str


class TrialIn(BaseModel):
    plan: str = "pro"


# ---------- calculs ----------

def add_months(start: datetime, months: int) -> datetime:
    """Même jour du mois, N mois plus tard (le 31 janvier + 1 mois = fin février)."""
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


def active_subscription(db: Session, org: Organization) -> Subscription | None:
    return db.exec(select(Subscription).where(Subscription.org_id == org.id, Subscription.status == "active")
                   .order_by(Subscription.created_at.desc())).first()


def _promo(db: Session, code: str) -> PromoCode | None:
    """Code promo utilisable, ou None s'il est vide. Lève 422 s'il est inconnu, épuisé ou expiré."""
    code = code.strip().upper()
    if not code:
        return None
    promo = db.get(PromoCode, code)
    if (promo is None or not promo.active or (promo.expires_at and promo.expires_at <= now())
            or (promo.max_uses is not None and promo.used >= promo.max_uses)):
        raise HTTPException(422, "Ce code promo n'est pas valable")
    return promo


def quote(db: Session, org: Organization, plan: str, period: str, promo_code: str = "") -> dict:
    """Ce que coûtera ce choix, détail compris : prix, remise, déduction des jours déjà payés."""
    if plan not in PLANS or PLANS[plan]["price_fcfa"] == 0:
        raise HTTPException(422, "Choisissez une offre payante")
    if period not in PERIODS:
        raise HTTPException(422, "Période inconnue : mois ou an")
    months, price_key, period_label = PERIODS[period]
    base = PLANS[plan][price_key]
    promo = _promo(db, promo_code)
    discount = base * promo.percent_off // 100 if promo else 0

    # Changement vers une offre plus chère en cours de période payée : on déduit ce qui reste.
    prorata = 0
    current = active_subscription(db, org)
    renewing = org.plan == plan and org.plan_until is not None and org.plan_until > now()
    if (current and current.source == "paiement" and current.ends_at and current.ends_at > now()
            and org.plan != plan and PLANS[plan]["price_fcfa"] > plan_of(org)["price_fcfa"]):
        total = (current.ends_at - current.starts_at).total_seconds()
        # La période payée peut ne pas avoir commencé (payée pendant un essai) : elle est alors due en entier.
        left = (current.ends_at - max(now(), current.starts_at)).total_seconds()
        prorata = int(current.amount_fcfa * min(1.0, left / total)) if total > 0 else 0

    amount = max(MIN_AMOUNT_FCFA, base - discount - prorata)
    starts = org.plan_until if renewing else now()
    return {"plan": plan, "plan_label": PLANS[plan]["label"], "period": period, "period_label": period_label,
            "base_fcfa": base, "discount_fcfa": discount, "promo_code": promo.code if promo else "",
            "prorata_fcfa": prorata, "amount_fcfa": amount, "renewal": renewing,
            "starts_at": starts, "ends_at": add_months(starts, months)}


def activate(db: Session, org: Organization, plan: str, period: str, source: str, amount_fcfa: int = 0,
             payment_id: str = "", ends_at: datetime | None = None, open_ended: bool = False) -> Subscription:
    """Ouvre la période d'abonnement et met l'espace sur l'offre. Renouvellement = prolongation."""
    renewing = org.plan == plan and org.plan_until is not None and org.plan_until > now()
    starts = org.plan_until if renewing else now()
    if open_ended:
        ends = None
    elif ends_at is not None:
        ends = ends_at
    else:
        ends = add_months(starts, PERIODS[period][0])
    for old in db.exec(select(Subscription).where(Subscription.org_id == org.id, Subscription.status == "active")).all():
        if renewing and old.ends_at:
            continue  # la période en cours va jusqu'à son terme, la nouvelle prend la suite
        old.status = "remplacee"
        db.add(old)
    sub = Subscription(org_id=org.id, plan=plan, period=period, source=source, starts_at=starts, ends_at=ends,
                       amount_fcfa=amount_fcfa, payment_id=payment_id)
    db.add(sub)
    org.plan = plan
    org.plan_until = ends
    db.add(org)
    db.commit()
    db.refresh(sub)
    db.refresh(org)
    return sub


# ---------- règlement d'un paiement ----------

def settle(db: Session, payment: Payment, success: bool, message: str = "") -> Payment:
    """Applique l'issue d'un paiement, une seule fois. Appelé par le webhook ou par l'interrogation."""
    db.refresh(payment)
    if payment.status != "en_attente":
        return payment
    payment.status = "reussi" if success else "echoue"
    payment.message = message[:300]
    payment.updated_at = now()
    db.add(payment)
    db.commit()
    if success:
        org = db.get(Organization, payment.org_id)
        if payment.kind == "credit":
            credit(db, org, payment.amount_fcfa * 1000, "recharge", payment.external_reference)
        else:
            activate(db, org, payment.plan, payment.period, "paiement", payment.amount_fcfa, payment.id)
            # Crédit IA compris dans l'offre : versé d'un coup pour toute la période payée.
            included = PLANS[payment.plan].get("ai_credit_month_fcfa", 0) * PERIODS[payment.period][0]
            if included:
                credit(db, org, included * 1000, "inclus", f"inclus:{payment.id}")
            if payment.promo_code and (promo := db.get(PromoCode, payment.promo_code)):
                promo.used += 1
                db.add(promo)
                db.commit()
    db.refresh(payment)
    return payment


def _outcome(status: object) -> bool | None:
    """Statut TrustChange -> True (payé), False (échec), None (encore en cours ou inconnu)."""
    value = str(status or "").strip().upper()
    return True if value in SUCCESS else False if value in FAILURE else None


def refresh_payment(db: Session, payment: Payment) -> Payment:
    """Demande à TrustChange où en est un paiement en attente. Sans effet s'il est déjà réglé."""
    if payment.status != "en_attente" or not trustchange.is_enabled():
        return payment
    age = now() - payment.created_at
    try:
        data = trustchange.get_transaction(payment.external_reference)
    except trustchange.TrustChangeError as e:
        # Introuvable après quelques minutes : la demande n'est jamais partie.
        if e.status_code == 404 and age > timedelta(minutes=3):
            return settle(db, payment, False, "La demande de paiement n'a pas abouti. Réessayez.")
        return payment
    outcome = _outcome(data.get("status"))
    if outcome is True and "amount" in data and int(float(data["amount"])) != payment.amount_fcfa:
        # On n'active rien sur un montant qui ne correspond pas, et on n'annule rien non plus :
        # le paiement reste en attente, à trancher depuis l'administration.
        payment.message = f"À vérifier : montant annoncé {data['amount']} FCFA au lieu de {payment.amount_fcfa}"
        db.add(payment)
        db.commit()
        return payment
    if outcome is None:
        if age > timedelta(hours=24):
            return settle(db, payment, False, "Paiement non validé à temps.")
        return payment
    return settle(db, payment, outcome, str(data.get("message") or data.get("failureReason") or ""))


def _start_payment(db: Session, user: User, payment: Payment) -> Payment:
    """Enregistre la demande puis l'envoie à TrustChange. Le client valide ensuite sur son téléphone."""
    payment.external_reference = f"rsv-{payment.id}"
    db.add(payment)
    db.commit()
    db.refresh(payment)
    s = get_settings()
    if not trustchange.is_enabled():
        if s.payment_simulation:
            return settle(db, payment, True, "Paiement simulé (aucun débit réel)")
        settle(db, payment, False, "Paiement en ligne non configuré")
        raise HTTPException(503, "Le paiement en ligne n'est pas encore disponible. Contactez-nous pour activer votre offre.")
    try:
        data = trustchange.collect_mobile_money(
            payment_code=payment.operator, phone_number=payment.phone, amount=payment.amount_fcfa,
            external_reference=payment.external_reference,
            metadata={"payment_id": payment.id, "kind": payment.kind, "plan": payment.plan, "period": payment.period})
    except trustchange.AlreadySubmitted:
        return refresh_payment(db, payment)
    except trustchange.TrustChangeError as e:
        if e.status_code is None:
            return payment  # réseau coupé : on ne sait pas si c'est parti, l'interrogation tranchera
        settle(db, payment, False, e.message)
        raise HTTPException(502 if e.status_code >= 500 or e.status_code == 401 else 400,
                            f"Paiement refusé : {e.message}") from e
    payment.provider_tx_id = str(data.get("transactionId") or "")
    db.add(payment)
    db.commit()
    outcome = _outcome(data.get("status"))
    return settle(db, payment, outcome, str(data.get("message") or "")) if outcome is not None else payment


def _payment_out(p: Payment) -> dict:
    label = "Recharge de crédit IA" if p.kind == "credit" else \
        f"Offre {PLANS.get(p.plan, {}).get('label', p.plan)}, {PERIODS.get(p.period, (0, '', p.period))[2]}"
    return {"id": p.id, "kind": p.kind, "label": label, "plan": p.plan, "period": p.period, "amount_fcfa": p.amount_fcfa,
            "status": p.status, "message": p.message, "created_at": p.created_at}


def subscription_view(db: Session, org: Organization) -> dict:
    """État de l'abonnement, tel qu'affiché dans « Mon compte »."""
    sub = active_subscription(db, org)
    until = org.plan_until
    days_left = max(0, (until - now()).days) if until else None
    plan = plan_of(org)
    return {
        "plan": org.plan if org.plan in PLANS else "gratuit", "plan_label": plan["label"],
        "paid": plan["price_fcfa"] > 0, "source": sub.source if sub else "", "period": sub.period if sub else "",
        "until": until, "days_left": days_left,
        "expires_soon": days_left is not None and days_left <= 7,
        "trial_available": not org.trial_used and org.plan == "gratuit", "trial_days": get_settings().trial_days,
        "payments_enabled": trustchange.is_enabled() or get_settings().payment_simulation,
    }


# ---------- routes ----------

@router.get("/subscription")
def get_subscription(user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict:
    org = db.get(Organization, user.org_id)
    history = db.exec(select(Subscription).where(Subscription.org_id == org.id).order_by(Subscription.created_at.desc()).limit(24)).all()
    payments = db.exec(select(Payment).where(Payment.org_id == org.id).order_by(Payment.created_at.desc()).limit(24)).all()
    return {**subscription_view(db, org),
            "history": [{"plan_label": PLANS.get(h.plan, {}).get("label", h.plan), "period": h.period, "source": h.source,
                         "status": h.status, "starts_at": h.starts_at, "ends_at": h.ends_at, "amount_fcfa": h.amount_fcfa}
                        for h in history],
            "payments": [_payment_out(p) for p in payments]}


@router.post("/subscription/quote")
def post_quote(body: CheckoutIn, user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict:
    return quote(db, db.get(Organization, user.org_id), body.plan, body.period, body.promo_code)


@router.post("/subscription/checkout")
def checkout(body: CheckoutIn, user: User = Depends(min_role("admin")), db: Session = Depends(get_session)) -> dict:
    """Lance le paiement d'un abonnement. L'utilisateur valide ensuite sur son téléphone."""
    org = db.get(Organization, user.org_id)
    q = quote(db, org, body.plan, body.period, body.promo_code)
    if not body.phone.strip() or not body.operator.strip():
        raise HTTPException(422, "Indiquez le numéro Mobile Money et l'opérateur")
    payment = Payment(id=new_id(), org_id=org.id, user_id=user.id, kind="abonnement", plan=body.plan, period=body.period,
                      amount_fcfa=q["amount_fcfa"], phone=body.phone.strip(), operator=body.operator.strip(),
                      promo_code=q["promo_code"])
    return _payment_out(_start_payment(db, user, payment))


@router.post("/subscription/trial")
def start_trial(body: TrialIn, user: User = Depends(min_role("admin")), db: Session = Depends(get_session)) -> dict:
    """Essai gratuit d'une offre payante, une seule fois par espace, sans moyen de paiement."""
    org = db.get(Organization, user.org_id)
    if body.plan not in PLANS or PLANS[body.plan]["price_fcfa"] == 0:
        raise HTTPException(422, "Choisissez une offre payante")
    if org.trial_used or org.plan != "gratuit":
        raise HTTPException(409, "L'essai gratuit a déjà été utilisé")
    org.trial_used = True
    activate(db, org, body.plan, "essai", "essai", ends_at=now() + timedelta(days=get_settings().trial_days))
    return subscription_view(db, org)


@router.post("/billing/topup")
def topup(body: TopupIn, user: User = Depends(min_role("admin")), db: Session = Depends(get_session)) -> dict:
    """Recharge du crédit IA par Mobile Money."""
    minimum = get_settings().topup_min_fcfa
    if body.amount_fcfa < minimum:
        raise HTTPException(422, f"Recharge minimale : {minimum} FCFA")
    payment = Payment(id=new_id(), org_id=user.org_id, user_id=user.id, kind="credit", amount_fcfa=body.amount_fcfa,
                      phone=body.phone.strip(), operator=body.operator.strip())
    return _payment_out(_start_payment(db, user, payment))


_operators_cache: tuple[datetime, list[dict]] | None = None


@router.get("/payments/operators")
def operators(_: User = Depends(current_user)) -> list[dict]:
    """Opérateurs Mobile Money proposés au paiement (liste fournie par TrustChange, gardée une heure)."""
    global _operators_cache
    if not trustchange.is_enabled():
        return [{"code": "SIMULATION", "name": "Paiement simulé (aucun débit)"}] if get_settings().payment_simulation else []
    if _operators_cache and now() - _operators_cache[0] < timedelta(hours=1):
        return _operators_cache[1]
    try:
        data = trustchange.get_operators()
    except trustchange.TrustChangeError as e:
        raise HTTPException(502, f"Liste des opérateurs indisponible : {e.message}") from e
    rows = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), []) if isinstance(data, dict) else []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = row.get("code") or row.get("paymentCode") or row.get("payment_code")
        if code:
            out.append({"code": str(code), "name": str(row.get("name") or row.get("label") or row.get("operator") or code),
                        "country": str(row.get("country") or row.get("countryCode") or "")})
    _operators_cache = (now(), out)
    return out


@router.get("/payments/{payment_id}")
def get_payment(payment_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict:
    """État d'un paiement. L'application l'appelle toutes les quelques secondes pendant la validation."""
    payment = db.get(Payment, payment_id)
    if not payment or payment.org_id != user.org_id:
        raise HTTPException(404, "Paiement introuvable")
    return _payment_out(refresh_payment(db, payment))


@router.post("/payments/webhook")
async def webhook(request: Request, db: Session = Depends(get_session)) -> dict:
    """Notification de TrustChange. Refusée sans signature valide ; sans effet si le paiement est déjà réglé."""
    s = get_settings()
    raw = await request.body()
    try:
        trustchange.verify_webhook(raw, request.headers.get(s.trustchange_signature_header),
                                   request.headers.get(s.trustchange_timestamp_header))
    except trustchange.TrustChangeError as e:
        raise HTTPException(401, e.message) from e
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Corps illisible") from None
    data = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else body
    if not isinstance(data, dict):
        return {"ok": True, "ignored": "format inattendu"}
    reference = str(data.get("externalReference") or data.get("external_reference") or "")
    tx_id = str(data.get("transactionId") or data.get("transaction_id") or "")
    payment = db.exec(select(Payment).where(Payment.external_reference == reference)).first() if reference else None
    if payment is None and tx_id:
        payment = db.exec(select(Payment).where(Payment.provider_tx_id == tx_id)).first()
    if payment is None:
        return {"ok": True, "ignored": "référence inconnue"}  # 200 : inutile que l'agrégateur réessaie
    if tx_id and not payment.provider_tx_id:
        payment.provider_tx_id = tx_id
        db.add(payment)
        db.commit()
    outcome = _outcome(data.get("status"))
    if outcome is True and "amount" in data and int(float(data["amount"])) != payment.amount_fcfa:
        outcome = None  # montant douteux : on demande l'état officiel plutôt que de croire le message
    if outcome is None:
        refresh_payment(db, payment)
    else:
        settle(db, payment, outcome, str(data.get("message") or ""))
    return {"ok": True, "status": payment.status}
