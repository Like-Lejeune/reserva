"""Envoi des réserves aux entreprises : WhatsApp d'abord, SMS en secours.

Chaque envoi produit aussi un lien wa.me : même sans compte WhatsApp Business, l'ingénieur
touche le lien et le message part de son propre WhatsApp.
"""

from typing import Protocol
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings
from app.models import Company, Project, Reserve
from app.vocab import LOTS, SEVERITIES


def clean_phone(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())


def build_message(project: Project, company: Company, reserves: list[Reserve], report_url: str) -> str:
    lines = [
        f"*{project.name}* — réserves à lever",
        f"Entreprise : {company.name} ({LOTS.get(company.lot, company.lot)})",
        f"{len(reserves)} réserve(s) ouverte(s) :",
        "",
    ]
    for r in reserves[:15]:
        where = f"{r.location} : " if r.location else ""
        lines.append(f"{r.number}. {where}{r.description} [{SEVERITIES.get(r.severity, r.severity)}]")
        if r.action:
            lines.append(f"   → {r.action}")
    if len(reserves) > 15:
        lines.append(f"… et {len(reserves) - 15} autre(s), voir le rapport.")
    lines += ["", f"Rapport PDF avec photos : {report_url}"]
    return "\n".join(lines)


def build_sms(project: Project, reserves: list[Reserve], report_url: str) -> str:
    return f"{project.name}: {len(reserves)} reserve(s) a lever. Detail: {report_url}"


def wa_link(phone: str, text: str) -> str:
    return f"https://wa.me/{clean_phone(phone)}?text={quote(text)}"


class Channel(Protocol):
    name: str

    def send(self, to: str, text: str) -> tuple[bool, str]: ...


class ConsoleChannel:
    """Développement : écrit le message dans le journal, n'envoie rien."""

    name = "console"

    def send(self, to: str, text: str) -> tuple[bool, str]:
        print(f"[envoi simulé] -> {to}\n{text}\n")
        return True, "simulé"


class WhatsAppCloudChannel:
    """API WhatsApp Cloud de Meta.

    Attention : un message texte libre n'est accepté que dans les 24 h suivant un message du
    destinataire. Pour écrire en premier, il faut un modèle de message approuvé par Meta.
    """

    name = "whatsapp"

    def __init__(self, s: Settings):
        self.url = f"https://graph.facebook.com/{s.whatsapp_api_version}/{s.whatsapp_phone_number_id}/messages"
        self.token = s.whatsapp_token

    def send(self, to: str, text: str) -> tuple[bool, str]:
        payload = {"messaging_product": "whatsapp", "to": clean_phone(to), "type": "text",
                   "text": {"preview_url": True, "body": text}}
        try:
            r = httpx.post(self.url, json=payload, timeout=30, headers={"Authorization": f"Bearer {self.token}"})
        except httpx.HTTPError as e:
            return False, f"réseau : {e}"
        return (True, "envoyé") if r.is_success else (False, f"HTTP {r.status_code} : {r.text[:300]}")


class SmsHttpChannel:
    """Passerelle SMS générique (POST JSON). Adapter les champs à l'opérateur retenu."""

    name = "sms"

    def __init__(self, s: Settings):
        self.s = s

    def send(self, to: str, text: str) -> tuple[bool, str]:
        try:
            r = httpx.post(self.s.sms_gateway_url, timeout=30,
                           headers={"Authorization": f"Bearer {self.s.sms_api_key}"},
                           json={"to": clean_phone(to), "from": self.s.sms_sender, "message": text})
        except httpx.HTTPError as e:
            return False, f"réseau : {e}"
        return (True, "envoyé") if r.is_success else (False, f"HTTP {r.status_code} : {r.text[:300]}")


def get_channel(settings: Settings | None = None) -> Channel:
    s = settings or get_settings()
    if s.dispatch_channel == "whatsapp" and s.whatsapp_token and s.whatsapp_phone_number_id:
        return WhatsAppCloudChannel(s)
    if s.dispatch_channel == "sms" and s.sms_gateway_url:
        return SmsHttpChannel(s)
    return ConsoleChannel()
