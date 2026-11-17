"""Offres et limites. Source unique : le site vitrine, l'application et l'administration lisent ceci.

Pour changer un prix ou une limite, modifier ce fichier et redémarrer. `None` = illimité.
"""

from fastapi import HTTPException
from sqlmodel import Session, func, select

from app.models import Media, Organization, Project, Reserve, Subscription, User, now

MB = 1024 * 1024

# Repères de prix (novembre 2026) : PlanRadar à partir de 26 € (17 000 FCFA) par utilisateur et par
# mois, Fieldwire à partir de 39 $ (23 000 FCFA), Archireport 39 € (25 600 FCFA). Les offres ci-dessous
# sont fixes par espace et non par utilisateur, et restent 3 à 5 fois moins chères.
PLANS: dict[str, dict] = {
    "gratuit": {
        "label": "Gratuit",
        "price_fcfa": 0,
        "tagline": "Pour essayer sur un vrai chantier",
        "storage_mb": 100,
        "max_reports": 3,
        "max_members": 1,
        "ai_credit_month_fcfa": 0,  # 500 FCFA offerts une fois, à l'inscription
        "features": ["3 rapports", "100 Mo de photos, environ 400", "PDF partagé par WhatsApp",
                     "Fonctionne sans connexion", "500 FCFA de crédit IA offerts"],
    },
    "pro": {
        "label": "Pro",
        "price_fcfa": 5000,
        "tagline": "Pour le technicien ou l'ingénieur indépendant",
        "storage_mb": 5 * 1024,
        "max_reports": None,
        "max_members": 1,
        "ai_credit_month_fcfa": 500,
        "recommended": True,
        "features": ["Rapports illimités", "5 Go de photos", "Votre logo et vos coordonnées sur le PDF",
                     "Envoi des défauts à chaque artisan", "500 FCFA de crédit IA chaque mois"],
    },
    "equipe": {
        "label": "Équipe",
        "price_fcfa": 15000,
        "tagline": "Pour le cabinet ou le bureau d'études",
        "storage_mb": 25 * 1024,
        "max_reports": None,
        "max_members": 5,
        "ai_credit_month_fcfa": 2000,
        "features": ["Tout ce qu'il y a dans Pro", "Jusqu'à 5 membres", "25 Go de photos partagés",
                     "L'ingénieur valide chaque correction", "2 000 FCFA de crédit IA chaque mois"],
    },
    "entreprise": {
        "label": "Entreprise",
        "price_fcfa": 40000,
        "tagline": "Pour l'entreprise de construction ou le promoteur",
        "storage_mb": 100 * 1024,
        "max_reports": None,
        "max_members": 20,
        "ai_credit_month_fcfa": 5000,
        "features": ["Tout ce qu'il y a dans Équipe", "Jusqu'à 20 membres", "100 Go de photos partagés",
                     "Prise en main de votre équipe", "5 000 FCFA de crédit IA chaque mois"],
    },
}

# Ce que chaque offre comprend, fonction par fonction : le tableau comparatif de la vitrine.
# True / False s'affichent en coche ou en tiret ; un texte s'affiche tel quel.
COMPARISON: list[tuple[str, dict[str, object]]] = [
    ("Rapports", {"gratuit": "3", "pro": "Illimités", "equipe": "Illimités", "entreprise": "Illimités"}),
    ("Photos stockées", {"gratuit": "100 Mo", "pro": "5 Go", "equipe": "25 Go", "entreprise": "100 Go"}),
    ("Utilisateurs", {"gratuit": "1", "pro": "1", "equipe": "5", "entreprise": "20"}),
    ("Application web et mobile, sans connexion", {"gratuit": True, "pro": True, "equipe": True, "entreprise": True}),
    ("Dictée vocale et classement automatique", {"gratuit": True, "pro": True, "equipe": True, "entreprise": True}),
    ("Rapport PDF partagé par WhatsApp", {"gratuit": True, "pro": True, "equipe": True, "entreprise": True}),
    ("Votre logo et vos coordonnées sur le PDF", {"gratuit": False, "pro": True, "equipe": True, "entreprise": True}),
    ("Envoi des défauts à chaque artisan", {"gratuit": False, "pro": True, "equipe": True, "entreprise": True}),
    ("Rôles et validation par l'ingénieur", {"gratuit": False, "pro": False, "equipe": True, "entreprise": True}),
    ("Crédit IA inclus", {"gratuit": "500 FCFA à l'inscription", "pro": "500 FCFA par mois",
                          "equipe": "2 000 FCFA par mois", "entreprise": "5 000 FCFA par mois"}),
    ("Assistance", {"gratuit": "Questions fréquentes", "pro": "WhatsApp", "equipe": "WhatsApp prioritaire",
                    "entreprise": "Interlocuteur dédié"}),
]

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
    return [{"key": key, **plan, "details": {label: row[key] for label, row in COMPARISON}} for key, plan in PLANS.items()]


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
