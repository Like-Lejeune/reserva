"""Crédits IA : tarification à l'usage, débit du cabinet, recharges.

Le cabinet ne paie que ce qu'il consomme. Prix débité = coût du fournisseur (tokens ou minutes
audio, converti en FCFA) + marge. Les montants sont en millièmes de FCFA (mFCFA) car un appel
coûte souvent moins d'un franc.
"""

import math
from dataclasses import dataclass

from sqlalchemy import update
from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.models import Organization, UsageLog, User, WalletTx


@dataclass
class Usage:
    """Ce qu'un appel IA a consommé. Tout à zéro = gratuit (mode mots-clés)."""

    provider: str = "rules"
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: float = 0

    @property
    def billable(self) -> bool:
        return bool(self.input_tokens or self.output_tokens or self.audio_seconds)


def price(usage: Usage, s: Settings | None = None) -> tuple[int, int]:
    """Renvoie (coût fournisseur, prix débité) en mFCFA."""
    s = s or get_settings()
    usd = (usage.input_tokens * s.ai_usd_per_mtok_in + usage.output_tokens * s.ai_usd_per_mtok_out) / 1_000_000
    usd += usage.audio_seconds / 60 * s.ai_usd_per_audio_min
    cost = usd * s.usd_to_fcfa * 1000
    return math.ceil(cost), math.ceil(cost * (1 + s.ai_margin_pct / 100))


def charge(db: Session, org: Organization, user: User, kind: str, usage: Usage) -> int:
    """Journalise l'appel et débite le cabinet. Renvoie le montant débité en mFCFA."""
    if not usage.billable:
        return 0
    cost, charged = price(usage)
    db.add(UsageLog(org_id=org.id, user_id=user.id, kind=kind, provider=usage.provider, model=usage.model,
                    input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                    audio_seconds=usage.audio_seconds, cost_mfcfa=cost, charged_mfcfa=charged))
    # Débit fait en SQL : deux téléphones du même cabinet ne s'écrasent pas le solde.
    db.exec(update(Organization).where(Organization.id == org.id)
            .values(balance_mfcfa=Organization.balance_mfcfa - charged))
    db.commit()
    db.refresh(org)
    return charged


def credit(db: Session, org: Organization, amount_mfcfa: int, kind: str, reference: str) -> WalletTx:
    """Crédite le cabinet. Une même référence de paiement n'est jamais créditée deux fois."""
    if reference and (done := db.exec(select(WalletTx).where(WalletTx.reference == reference)).first()):
        return done
    db.exec(update(Organization).where(Organization.id == org.id)
            .values(balance_mfcfa=Organization.balance_mfcfa + amount_mfcfa))
    db.flush()
    db.refresh(org)
    tx = WalletTx(org_id=org.id, kind=kind, amount_mfcfa=amount_mfcfa, reference=reference,
                  balance_after_mfcfa=org.balance_mfcfa)
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def fcfa(mfcfa: int) -> float:
    return round(mfcfa / 1000, 3)
