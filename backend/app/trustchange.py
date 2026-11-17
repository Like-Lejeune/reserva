"""Client de l'API TrustChange, l'agrégateur de paiement Mobile Money.

Adapté du client de Cashnut (services/trustchange_service.py) : même enveloppe, mêmes
exceptions, même vérification de webhook. Reserva n'encaisse que (collect) ; les
décaissements ne sont pas repris.

Ce module ne connaît rien du métier : il traduit l'API en appels Python et en exceptions.
La logique d'abonnement est dans app/subscriptions.py. Changer d'agrégateur = réécrire ce fichier.

Deux garde-fous portés par TrustChange et exploités ici :
  - `externalReference` est unique par compte : rejouer la même référence renvoie 409 sans
    rien créer. On peut donc relancer un appel incertain sans risque de double paiement.
  - les webhooks sont signés en HMAC-SHA256 sur `timestamp + "." + corps brut`.
"""

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.config import get_settings

API_PREFIX = "/api/Integrator"
WEBHOOK_MAX_AGE_SECONDS = 300  # au-delà, rejeu probable
HTTP_TIMEOUT_SECONDS = 20


class TrustChangeError(Exception):
    """Erreur renvoyée par TrustChange ou survenue en tentant de le joindre.

    `status_code` vaut None quand on n'a pas eu de réponse : on ignore alors si l'opération
    est partie, et il faut interroger par référence plutôt que rejouer.
    """

    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}


class AlreadySubmitted(TrustChangeError):
    """409 : référence déjà utilisée. Pas un échec : l'opération d'origine existe, il faut lire son état."""


class NotConfigured(TrustChangeError):
    """Aucune clé API renseignée : l'intégration est inactive."""


def is_enabled() -> bool:
    return bool(get_settings().trustchange_api_key)


def is_test_mode() -> bool:
    """Une clé `tc_test_…` opère sur un compte fictif aux opérations simulées."""
    return get_settings().trustchange_api_key.startswith("tc_test_")


def _request(method: str, path: str, *, json_body: dict | None = None) -> Any:
    """Appelle l'API et renvoie le contenu de `data`.

    Enveloppe commune : {"data": ..., "message": "...", "statut": "success"|"error", "statusCode": ...}
    """
    s = get_settings()
    if not is_enabled():
        raise NotConfigured("RESERVA_TRUSTCHANGE_API_KEY non configurée.")
    url = f"{s.trustchange_base_url.rstrip('/')}{API_PREFIX}{path}"
    headers = {"X-Api-Key": s.trustchange_api_key, "Accept": "application/json"}
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.request(method, url, json=json_body, headers=headers)
    except httpx.RequestError as exc:
        raise TrustChangeError(f"TrustChange injoignable : {exc}") from exc
    try:
        envelope = response.json()
    except ValueError:
        raise TrustChangeError(f"Réponse illisible de TrustChange (HTTP {response.status_code}).",
                               status_code=response.status_code) from None
    if not isinstance(envelope, dict):
        envelope = {"data": envelope}
    message = envelope.get("message") or f"HTTP {response.status_code}"
    data = envelope.get("data") or {}
    if response.status_code == 409:
        raise AlreadySubmitted(message, status_code=409, payload=data)
    if response.status_code == 401:
        raise TrustChangeError(f"Clé API refusée : {message} (clé révoquée, invalide, ou IP non autorisée).",
                               status_code=401, payload=data)
    if response.status_code >= 400 or envelope.get("statut") == "error":
        raise TrustChangeError(message, status_code=response.status_code, payload=data)
    return data


def national_phone_number(phone: str | None, country_prefix: str = "237") -> str:
    """TrustChange attend un numéro NATIONAL, sans indicatif (« 699000000 »)."""
    if not phone:
        raise TrustChangeError("Numéro de téléphone manquant.", status_code=400)
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith(country_prefix) and len(digits) > len(country_prefix):
        digits = digits[len(country_prefix):]
    if len(digits) < 8:
        raise TrustChangeError(f"Numéro de téléphone inexploitable : {phone}", status_code=400)
    return digits


def collect_mobile_money(*, payment_code: str, phone_number: str, amount: int, external_reference: str,
                         metadata: dict | None = None) -> dict:
    """Demande un paiement au client, qui valide sur son téléphone. La confirmation arrive par webhook.

    Réponse 202 : `transactionId`, `status` (PROCESSING), `fees`, `netAmount`.
    """
    body: dict[str, Any] = {
        "paymentMethod": "MOBILE_MONEY",
        "paymentCode": payment_code,
        "phoneNumber": national_phone_number(phone_number),
        "amount": int(amount),
        "externalReference": external_reference,
    }
    callback = get_settings().trustchange_callback_url
    if callback:
        body["callbackUrl"] = callback
    if metadata:
        body["metadata"] = json.dumps(metadata)
    data = _request("POST", "/collect", json_body=body)
    return data if isinstance(data, dict) else {}


def get_transaction(reference: str) -> dict:
    """État d'une transaction, par `transactionId` ou par notre référence externe."""
    data = _request("GET", f"/transaction/{reference}")
    return data if isinstance(data, dict) else {}


def get_operators() -> Any:
    """Opérateurs Mobile Money : code, pays, devise, bornes, format du numéro."""
    return _request("GET", "/operators")


def verify_webhook(raw_body: bytes, signature: str | None, timestamp: str | None) -> None:
    """Valide la signature d'un webhook ; lève TrustChangeError s'il doit être refusé.

    La signature porte sur le CORPS BRUT (avant désérialisation), la comparaison est en temps
    constant, et l'horodatage est vérifié pour qu'un message capté ne soit pas rejouable.
    """
    secret = get_settings().trustchange_webhook_secret
    if not secret:
        raise TrustChangeError("RESERVA_TRUSTCHANGE_WEBHOOK_SECRET non configuré : webhook refusé.")
    if not signature or not timestamp:
        raise TrustChangeError("Webhook sans signature ou sans horodatage.")
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        raise TrustChangeError(f"Horodatage de webhook invalide : {timestamp}") from None
    age = abs(int(time.time()) - sent_at)
    if age > WEBHOOK_MAX_AGE_SECONDS:
        raise TrustChangeError(f"Webhook périmé ({age} s, maximum {WEBHOOK_MAX_AGE_SECONDS} s) — rejeu probable.")
    expected = sign_webhook(raw_body, timestamp, secret)
    if not hmac.compare_digest(expected, signature.strip().lower()):
        raise TrustChangeError("Signature de webhook invalide.")


def sign_webhook(raw_body: bytes, timestamp: str, secret: str) -> str:
    """Signature d'un corps donné (même formule que verify_webhook) — sert aux tests."""
    return hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
