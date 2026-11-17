"""Offres et limites. Source unique : le site vitrine, l'application et l'administration lisent ceci.

Pour changer un prix ou une limite, modifier ce fichier et redémarrer. `None` = illimité.
"""

from fastapi import HTTPException
from sqlmodel import Session, func, select

from app.models import Media, Organization, Project, Reserve, Subscription, User, now

MB = 1024 * 1024

PLANS: dict[str, dict] = {
    "gratuit": {
        "label": "Gratuit",
        "price_fcfa": 0,
        "tagline": "Pour essayer sur un vrai chantier",
        "storage_mb": 100,
        "max_reports": 3,
        "max_members": 1,
        "features": ["3 rapports", "100 Mo de photos (environ 400 photos)", "PDF et partage WhatsApp",
                     "Fonctionne sans connexion", "500 FCFA de crédit IA offerts"],
    },
    "pro": {
        "label": "Pro",
        "price_fcfa": 5000,
        "tagline": "Pour l'indépendant qui en fait son outil de travail",
        "storage_mb": 5 * 1024,
        "max_reports": None,
        "max_members": 1,
        "features": ["Rapports illimités", "5 Go de photos", "Votre logo et vos coordonnées sur le PDF",
                     "Envoi des défauts à chaque artisan", "Crédit IA rechargeable par Mobile Money"],
    },
    "equipe": {
        "label": "Équipe",
        "price_fcfa": 15000,
        "tagline": "Pour les cabinets et les entreprises",
        "storage_mb": 25 * 1024,
        "max_reports": None,
        "max_members": 10,
        "features": ["Tout ce qu'il y a dans Pro", "Jusqu'à 10 membres", "25 Go de photos partagés",
                     "Rôles : technicien, ingénieur, lecteur", "L'ingénieur valide les corrections"],
    },
}


# Abonnement annuel : 12 mois pour le prix de 10. Les offres payantes ouvrent le PDF à l'en-tête
# du client (logo, coordonnées) et l'envoi des défauts à chaque artisan.
for _plan in PLANS.values():
    _plan["price_year_fcfa"] = _plan["price_fcfa"] * 10
    _plan["branding"] = _plan["dispatch"] = _plan["price_fcfa"] > 0


def refresh_plan(db: Session, org: Organization) -> None:
    """Échéance dépassée : l'espace repasse en Gratuit. Rien n'est supprimé ; les limites du
    Gratuit s'appliquent seulement aux nouveaux ajouts. Appelé à chaque requête, donc sans tâche planifiée."""
    if org.plan == "gratuit" or org.plan_until is None or org.plan_until > now():
        return
    for sub in db.exec(select(Subscription).where(Subscription.org_id == org.id, Subscription.status == "active")).all():
        sub.status = "expiree"
        db.add(sub)
    org.plan = "gratuit"
    org.plan_until = None
    db.add(org)
    db.commit()
    db.refresh(org)


def plan_of(org: Organization) -> dict:
    return PLANS.get(org.plan, PLANS["gratuit"])


def public_plans() -> list[dict]:
    return [{"key": key, **plan} for key, plan in PLANS.items()]


def storage_used(db: Session, org_id: str) -> int:
    """Octets occupés par les photos et notes vocales de l'espace."""
    total = db.exec(select(func.coalesce(func.sum(Media.size), 0))
                    .join(Reserve, Reserve.id == Media.reserve_id)
                    .join(Project, Project.id == Reserve.project_id)
                    .where(Project.org_id == org_id)).one()
    return int(total)


def _blocked(org: Organization, what: str) -> HTTPException:
    plan = plan_of(org)
    # On propose l'offre juste au-dessus ; au sommet, il ne reste qu'à nous écrire.
    higher = sorted((p for p in PLANS.values() if p["price_fcfa"] > plan["price_fcfa"]), key=lambda p: p["price_fcfa"])
    hint = f" Passez à l'offre {higher[0]['label']} pour continuer." if higher else " Contactez-nous pour augmenter la limite."
    return HTTPException(402, f"Limite de l'offre {plan['label']} atteinte : {what}.{hint}")


def check_can_create_report(db: Session, org: Organization) -> None:
    limit = plan_of(org)["max_reports"]
    if limit is None:
        return
    count = db.exec(select(func.count()).select_from(Project).where(Project.org_id == org.id)).one()
    if count >= limit:
        raise _blocked(org, f"{limit} rapports. Supprimez un ancien rapport ou changez d'offre")


def check_can_store(db: Session, org: Organization, extra_bytes: int) -> None:
    limit = plan_of(org)["storage_mb"]
    if limit is not None and storage_used(db, org.id) + extra_bytes > limit * MB:
        raise _blocked(org, f"{limit} Mo de photos")


def check_can_add_member(db: Session, org: Organization) -> None:
    limit = plan_of(org)["max_members"]
    if limit is None:
        return
    count = db.exec(select(func.count()).select_from(User).where(User.org_id == org.id, User.active == True)).one()  # noqa: E712
    if count >= limit:
        raise _blocked(org, f"{limit} membre(s)")


def check_feature(org: Organization, feature: str, what: str) -> None:
    """Lève 402 si l'offre de l'espace n'inclut pas cette fonction."""
    if not plan_of(org).get(feature):
        raise HTTPException(402, f"{what} fait partie des offres payantes. Passez à l'offre Pro pour l'utiliser.")
