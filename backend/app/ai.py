"""Couche IA interchangeable.

Deux fournisseurs, choisis par RESERVA_AI_PROVIDER :
- "rules"  : classement par mots-clés, sans réseau ni clé. Gratuit, toujours disponible.
- "openai" : n'importe quel serveur compatible OpenAI (OpenAI, Groq, Mistral, Ollama local...).
             En cas de panne réseau, on retombe sur "rules" au lieu d'échouer.

Chaque appel renvoie aussi sa consommation (`Usage`) : c'est elle qui est facturée au cabinet.
Tout le reste de l'application ne connaît que `get_provider()`.
"""

import json
import re
import unicodedata
from typing import Protocol

import httpx

from app.billing import Usage
from app.config import Settings, get_settings
from app.schemas import ReserveDraft
from app.vocab import LOT_KEYWORDS, LOTS, ROOM_KEYWORDS, SEVERITIES, SEVERITY_KEYWORDS


class AIUnavailable(RuntimeError):
    """La fonction demandée n'existe pas chez ce fournisseur, ou il est injoignable."""


class AIProvider(Protocol):
    name: str

    def transcribe(self, audio: bytes, filename: str, content_type: str, duration_s: float = 0) -> tuple[str, Usage]: ...

    def structure(self, text: str) -> tuple[ReserveDraft, Usage]: ...


def _norm(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn")


class RulesProvider:
    name = "rules"

    def transcribe(self, audio: bytes, filename: str, content_type: str, duration_s: float = 0) -> tuple[str, Usage]:
        raise AIUnavailable("La transcription vocale demande l'IA en ligne.")

    def structure(self, text: str) -> tuple[ReserveDraft, Usage]:
        n = _norm(text)
        scores = {lot: sum(n.count(k) for k in kws) for lot, kws in LOT_KEYWORDS.items()}
        lot = max(scores, key=scores.get) if any(scores.values()) else "autre"
        severity = "mineure"
        for level in ("bloquante", "majeure"):
            if any(k in n for k in SEVERITY_KEYWORDS[level]):
                severity = level
                break
        location = ""
        for room in sorted(ROOM_KEYWORDS, key=len, reverse=True):
            m = re.search(rf"\b{re.escape(room)}(\s+(n°\s*)?\d+)?", n)
            if m:
                location = m.group(0).strip().capitalize()
                break
        description = text.strip()
        description = description[0].upper() + description[1:] if description else ""
        draft = ReserveDraft(location=location, lot=lot, description=description, severity=severity,
                             provider=self.name)
        return draft, Usage()


_SYSTEM = (
    "Tu es conducteur de travaux en Afrique francophone. À partir de la note dictée lors d'une visite "
    "de chantier, renvoie UNIQUEMENT un objet JSON avec les clés : "
    '"location" (pièce ou zone, chaîne vide si inconnue), '
    '"lot" (une valeur parmi : {lots}), '
    '"description" (le défaut constaté, une phrase claire), '
    '"action" (le travail attendu de l\'entreprise, à l\'infinitif), '
    '"severity" (une valeur parmi : {sev}). '
    "N'invente rien qui ne soit pas dans la note."
)


class OpenAICompatProvider:
    name = "openai"

    def __init__(self, settings: Settings):
        self.s = settings
        self._fallback = RulesProvider()

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.s.ai_base_url, timeout=60,
                            headers={"Authorization": f"Bearer {self.s.ai_api_key}"})

    def transcribe(self, audio: bytes, filename: str, content_type: str, duration_s: float = 0) -> tuple[str, Usage]:
        try:
            with self._client() as c:
                r = c.post("/audio/transcriptions",
                           data={"model": self.s.ai_asr_model, "language": "fr", "response_format": "verbose_json"},
                           files={"file": (filename, audio, content_type or "audio/webm")})
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise AIUnavailable(f"Transcription indisponible : {e}") from e
        # Durée mesurée par le fournisseur si disponible, sinon celle annoncée par le téléphone.
        seconds = float(data.get("duration") or duration_s or 0)
        usage = Usage(provider=self.name, model=self.s.ai_asr_model, audio_seconds=seconds)
        return str(data.get("text", "")).strip(), usage

    def structure(self, text: str) -> tuple[ReserveDraft, Usage]:
        prompt = _SYSTEM.format(lots=", ".join(LOTS), sev=", ".join(SEVERITIES))
        base, _ = self._fallback.structure(text)
        try:
            with self._client() as c:
                r = c.post("/chat/completions", json={
                    "model": self.s.ai_llm_model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
                })
                r.raise_for_status()
                body = r.json()
                data = json.loads(body["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            base.provider = "rules (repli)"
            return base, Usage()  # l'appel a échoué : rien n'est facturé
        tokens = body.get("usage") or {}
        usage = Usage(provider=self.name, model=self.s.ai_llm_model,
                      input_tokens=int(tokens.get("prompt_tokens", 0)),
                      output_tokens=int(tokens.get("completion_tokens", 0)))
        lot = data.get("lot") if data.get("lot") in LOTS else base.lot
        severity = data.get("severity") if data.get("severity") in SEVERITIES else base.severity
        draft = ReserveDraft(location=str(data.get("location") or base.location), lot=lot, severity=severity,
                             description=str(data.get("description") or base.description),
                             action=str(data.get("action") or ""), provider=self.name)
        return draft, usage


def get_provider(settings: Settings | None = None) -> AIProvider:
    s = settings or get_settings()
    if s.ai_provider == "openai" and s.ai_api_key:
        return OpenAICompatProvider(s)
    return RulesProvider()
