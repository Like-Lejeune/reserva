"""Tables. Les identifiants sont des UUID générés côté client : une réserve créée hors ligne
garde le même id une fois synchronisée, et rejouer un envoi ne crée jamais de doublon."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlmodel import Field, SQLModel


def as_utc(value: datetime | None) -> datetime | None:
    """Une date sans fuseau est considérée comme UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.utcoffset() is None else value.astimezone(UTC)


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


ROLES = {"lecteur": 0, "technicien": 1, "ingenieur": 2, "admin": 3}


class Organization(SQLModel, table=True):
    """Un espace de travail. Par défaut c'est l'espace personnel d'un utilisateur seul, créé
    automatiquement à l'inscription ; il devient un espace d'équipe dès qu'on y invite quelqu'un."""

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    address: str = ""
    phone: str = ""
    email: str = ""
    registration_no: str = ""  # numéro d'inscription à l'ordre / agrément
    logo_filename: str = ""
    plan: str = "gratuit"  # gratuit | pro | equipe (voir app/plans.py)
    plan_until: datetime | None = None  # échéance de l'offre payante ; None = sans échéance
    trial_used: bool = False  # l'essai gratuit n'est offert qu'une fois
    suspended: bool = False  # compte bloqué par l'administration
    balance_mfcfa: int = 0  # crédit IA en millièmes de FCFA (un appel coûte souvent moins d'1 FCFA)
    created_at: datetime = Field(default_factory=now)


class User(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    org_id: str = Field(foreign_key="organization.id", index=True)
    login: str = Field(unique=True, index=True)  # numéro de téléphone (chiffres) ou e-mail
    name: str = ""
    password_hash: str = ""
    role: str = "technicien"  # lecteur | technicien | ingenieur | admin
    active: bool = True
    created_at: datetime = Field(default_factory=now)


class UsageLog(SQLModel, table=True):
    """Un appel IA facturé : ce que le cabinet voit dans son relevé de consommation."""

    id: str = Field(default_factory=new_id, primary_key=True)
    org_id: str = Field(foreign_key="organization.id", index=True)
    user_id: str = ""
    kind: str = ""  # structure | transcribe
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: float = 0
    cost_mfcfa: int = 0  # prix payé au fournisseur
    charged_mfcfa: int = 0  # prix débité au cabinet (coût + marge)
    created_at: datetime = Field(default_factory=now, index=True)


class WalletTx(SQLModel, table=True):
    """Entrée de crédit : recharge Mobile Money, bonus de bienvenue, geste commercial."""

    id: str = Field(default_factory=new_id, primary_key=True)
    org_id: str = Field(foreign_key="organization.id", index=True)
    kind: str = "recharge"  # recharge | bonus
    amount_mfcfa: int = 0
    reference: str = Field(default="", index=True)  # référence du paiement : empêche le double crédit
    balance_after_mfcfa: int = 0
    created_at: datetime = Field(default_factory=now)


class Project(SQLModel, table=True):
    """Un chantier."""

    id: str = Field(default_factory=new_id, primary_key=True)
    org_id: str = Field(foreign_key="organization.id", index=True)
    name: str
    client: str = ""  # maître d'ouvrage
    location: str = ""
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now, index=True)


class Company(SQLModel, table=True):
    """Entreprise ou artisan titulaire d'un lot sur un chantier."""

    id: str = Field(default_factory=new_id, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    name: str
    lot: str = "autre"
    contact_name: str = ""
    phone: str = ""  # format international sans +, ex. 237690000000
    updated_at: datetime = Field(default_factory=now, index=True)


class Visit(SQLModel, table=True):
    """Une visite de chantier (OPR, réception, levée de réserves)."""

    id: str = Field(default_factory=new_id, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    kind: str = "opr"
    visit_date: date = Field(default_factory=date.today)
    inspector: str = ""
    notes: str = ""
    updated_at: datetime = Field(default_factory=now, index=True)


class Reserve(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    visit_id: str | None = Field(default=None, foreign_key="visit.id")
    company_id: str | None = Field(default=None, foreign_key="company.id")
    number: int = 0  # numéro d'ordre dans le chantier, attribué par le serveur
    location: str = ""  # pièce / zone / niveau
    lot: str = "autre"
    description: str = ""
    action: str = ""  # travail attendu
    severity: str = "mineure"
    status: str = Field(default="ouverte", index=True)
    transcript: str = ""  # texte brut de la note vocale
    due_date: date | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now, index=True)  # horloge serveur : curseur de synchro
    client_updated_at: datetime | None = None  # horloge du téléphone : arbitre les conflits
    deleted: bool = False  # suppression logique, pour la propager aux autres téléphones


class Media(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    reserve_id: str = Field(foreign_key="reserve.id", index=True)
    kind: str = "photo_avant"  # photo_avant | photo_apres | audio
    filename: str = ""
    content_type: str = ""
    size: int = 0
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now, index=True)


class DispatchLog(SQLModel, table=True):
    """Trace de chaque envoi de réserves à une entreprise."""

    id: str = Field(default_factory=new_id, primary_key=True)
    project_id: str = Field(index=True)
    company_id: str
    channel: str
    ok: bool
    detail: str = ""
    reserve_count: int = 0
    created_at: datetime = Field(default_factory=now)


class Subscription(SQLModel, table=True):
    """Une période d'abonnement. L'historique complet reste ; une seule ligne est « active » par espace."""

    id: str = Field(default_factory=new_id, primary_key=True)
    org_id: str = Field(foreign_key="organization.id", index=True)
    plan: str
    period: str = "mois"  # mois | an | essai
    source: str = "paiement"  # paiement | essai | admin
    status: str = Field(default="active", index=True)  # active | expiree | remplacee
    starts_at: datetime = Field(default_factory=now)
    ends_at: datetime | None = None
    amount_fcfa: int = 0  # ce qui a été payé pour cette période
    payment_id: str = ""
    created_at: datetime = Field(default_factory=now)


class Payment(SQLModel, table=True):
    """Une demande de paiement Mobile Money : abonnement ou recharge de crédit IA."""

    id: str = Field(default_factory=new_id, primary_key=True)
    org_id: str = Field(foreign_key="organization.id", index=True)
    user_id: str = ""
    kind: str = "abonnement"  # abonnement | credit
    plan: str = ""
    period: str = ""
    amount_fcfa: int = 0
    phone: str = ""
    operator: str = ""  # paymentCode de l'opérateur
    promo_code: str = ""
    status: str = Field(default="en_attente", index=True)  # en_attente | reussi | echoue
    external_reference: str = Field(default="", unique=True, index=True)  # notre référence, unique chez l'agrégateur
    provider_tx_id: str = Field(default="", index=True)
    message: str = ""
    created_at: datetime = Field(default_factory=now, index=True)
    updated_at: datetime = Field(default_factory=now)


class PromoCode(SQLModel, table=True):
    code: str = Field(primary_key=True)  # en majuscules
    percent_off: int = 0  # 1 à 100
    max_uses: int | None = None  # None = illimité
    used: int = 0
    expires_at: datetime | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=now)


class ResetCode(SQLModel, table=True):
    """Code à usage unique pour changer un mot de passe oublié. Seule son empreinte est gardée."""

    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    code_hash: str
    expires_at: datetime
    attempts: int = 0  # essais ratés ; le code est grillé au-delà de la limite
    used: bool = False
    created_at: datetime = Field(default_factory=now)
