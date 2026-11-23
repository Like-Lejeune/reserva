"""Couche IA interchangeable : ce qui aide l'ingénieur à écrire son rapport.

Quatre aides :
- `analyze(note)`       : une note dictée -> un ou plusieurs défauts, chacun avec lieu, corps de métier,
                          description propre, travail à faire, gravité et délai conseillé ;
- `describe_photo(...)` : une photo seule -> le défaut qu'elle montre (modèle de vision) ;
- `synthesize(faits)`   : l'état du chantier -> la synthèse rédigée en tête du rapport ;
- `transcribe(audio)`   : une note vocale -> du texte.

Deux fournisseurs, choisis par RESERVA_AI_PROVIDER :
- "rules"  : règles du métier, sans réseau ni clé. Gratuit, toujours disponible. Sépare les défauts,
             nettoie la phrase, propose le travail à faire et rédige une synthèse chiffrée.
- "openai" : n'importe quel serveur compatible OpenAI (OpenAI, Mistral, Groq, Gemini, Ollama local…).
             Reformule comme un ingénieur et lit les photos. En cas d'échec, on retombe sur "rules".

Chaque appel renvoie sa consommation (`Usage`) : c'est elle qui est facturée. Le reste de l'application
ne connaît que `get_provider()`.
"""

import base64
import json
import re
import unicodedata
from typing import Protocol

import httpx

from app.billing import Usage
from app.config import Settings, get_settings
from app.schemas import ReserveDraft
from app.vocab import LOT_KEYWORDS, LOTS, ROOM_KEYWORDS, SEVERITIES, SEVERITY_KEYWORDS

# Délai conseillé pour lever un défaut, selon sa gravité.
DUE_DAYS = {"bloquante": 2, "majeure": 7, "mineure": 15}


class AIUnavailable(RuntimeError):
    """La fonction demandée n'existe pas chez ce fournisseur, ou il est injoignable."""


class AIProvider(Protocol):
    name: str

    def transcribe(self, audio: bytes, filename: str, content_type: str, duration_s: float = 0) -> tuple[str, Usage]: ...

    def analyze(self, text: str) -> tuple[list[ReserveDraft], Usage]: ...

    def describe_photo(self, image: bytes, note: str = "") -> tuple[ReserveDraft, Usage]: ...

    def synthesize(self, facts: dict) -> tuple[str, Usage]: ...


def _norm(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn")


# ---------- règles du métier ----------

# Mots qui signalent un défaut : une phrase sans aucun d'eux complète la précédente.
DEFECT_TERMS = [
    "fuite", "fissure", "fele", "casse", "manquant", "manque", "absent", "abime", "endommage", "raye",
    "coulure", "tache", "ecaill", "cloque", "decolle", "bouche", "infiltration", "humidite", "ne ferme",
    "ne fonctionne", "hors service", "pas de courant", "denude", "frotte", "coince", "de travers", "mal ",
    "non pose", "pas pose", "a reprendre", "defaut", "sale", "gravats", "sonne creux", "affaisse", "rouille",
    "trou", "eclat", "goutte", "a refaire", "pas termine", "inacheve", "bavure", "malfacon", "desaffleur", "jeu ", "branle", "instable", "pas fixe", "oxyd",
]

# (mots qui doivent tous figurer, mots dont l'un doit figurer, travail à faire, gravité minimale, corps de métier)
# Le corps de métier de la règle l'emporte sur les mots-clés : « fissure au-dessus de la fenêtre » est de la
# maçonnerie, pas de la menuiserie.
ACTION_RULES: list[tuple[list[str], list[str], str, str | None, str | None]] = [
    ([], ["fil denude", "fils denude", "cable apparent", "fils apparents", "court-circuit"],
     "Isoler les conducteurs sans délai, puis reprendre le raccordement dans une boîte de dérivation", "bloquante", "electricite"),
    ([], ["garde-corps", "garde corps", "rampe"],
     "Fixer ou compléter le garde-corps conformément aux règles de sécurité", "bloquante", "ferronnerie"),
    ([], ["fuite"], "Rechercher l'origine de la fuite, reprendre le raccord ou le joint, puis contrôler l'étanchéité", "majeure", None),
    ([], ["infiltration", "humidite", "trace d'eau", "traces d'eau"],
     "Rechercher et traiter l'origine de l'infiltration, puis reprendre les finitions", "majeure", "etancheite"),
    (["carreau"], ["casse", "fissure", "fele", "sonne creux", "decolle", "eclat"],
     "Déposer et remplacer le carreau, puis refaire les joints", None, "carrelage"),
    ([], ["fissure", "lezarde"], "Ouvrir et traiter la fissure, reboucher, puis reprendre l'enduit et la peinture", None, "maconnerie"),
    (["vitr"], ["casse", "fele", "raye", "fissure"], "Remplacer le vitrage", "majeure", "menuiserie_alu"),
    ([], ["ne ferme pas", "ferme mal", "mal ferme", "frotte", "coince", "ne s'ouvre pas"],
     "Régler les paumelles, la quincaillerie et la serrure jusqu'à une fermeture correcte", None, None),
    ([], ["poignee", "serrure", "cylindre", "verrou"], "Poser ou remplacer la quincaillerie", None, None),
    ([], ["ne fonctionne pas", "hors service", "pas de courant", "ne s'allume pas"],
     "Contrôler l'alimentation et remplacer l'appareil défectueux", "majeure", None),
    ([], ["prise", "interrupteur", "luminaire", "applique", "spot", "douille"],
     "Poser l'appareillage manquant ou défectueux et vérifier le circuit", None, "electricite"),
    ([], ["bouche", "s'evacue mal", "evacue mal", "stagne"], "Déboucher l'évacuation et contrôler sa pente", "majeure", "plomberie"),
    ([], ["chasse"], "Régler ou remplacer le mécanisme de chasse d'eau", None, "plomberie"),
    ([], ["robinet", "mitigeur"], "Régler, refixer ou remplacer la robinetterie", None, "plomberie"),
    ([], ["coulure", "bavure"], "Poncer les coulures et reprendre la peinture sur l'ensemble du pan concerné", None, "peinture"),
    ([], ["ecaill", "cloque"], "Gratter, préparer le support, puis reprendre la peinture", None, "peinture"),
    ([], ["decolle"], "Gratter, préparer le support, puis reprendre la finition", None, None),
    ([], ["tache", "sale", "trace"], "Nettoyer, ou reprendre la finition si la tache persiste", None, None),
    ([], ["joint"], "Refaire les joints sur la zone concernée", None, "carrelage"),
    ([], ["plinthe"], "Poser ou refixer les plinthes", None, "carrelage"),
    ([], ["affaisse", "plafond"], "Reprendre le faux plafond sur la zone", None, "faux_plafond"),
    ([], ["rouille", "oxyd"], "Brosser, traiter contre la corrosion et repeindre", None, "ferronnerie"),
    ([], ["gravats", "dechets", "poussiere", "nettoy"], "Évacuer les gravats et nettoyer la zone", None, "nettoyage"),
    ([], ["manquant", "manque", "absent", "non pose", "pas pose"], "Fournir et poser l'élément manquant", None, None),
    ([], ["casse", "abime", "endommage", "eclat", "trou"], "Réparer ou remplacer l'élément endommagé", None, None),
    ([], ["de travers", "desaffleur", "pas d'aplomb", "pas droit"], "Reprendre la pose pour obtenir un ouvrage d'aplomb et aligné", None, None),
    ([], ["instable", "branle", "pas fixe", "jeu "], "Refixer solidement l'élément", None, None),
]

FILLERS = r"^(?:(?:euh|alors|donc|bon|bah|ok|aussi|ensuite|puis|et|egalement|de plus|en plus|autre chose|" \
          r"il y a|il y avait|y a|ya|on a|on note|on constate|je constate|je note|j'ai vu|j'ai note|" \
          r"je vois|il faut signaler|a signaler|noter)[\s,:]*)+"
SPLIT = re.compile(r"(?:[.;!?\n]+|\s+(?:et aussi|ensuite|puis|egalement|de plus|en plus|autre chose|"
                   r"par ailleurs|ainsi que)\s+)", re.I)


def _has(n: str, words: list[str]) -> bool:
    return any(w in n for w in words)


def _location(n: str) -> str:
    for room in sorted(ROOM_KEYWORDS, key=len, reverse=True):
        m = re.search(rf"\b{re.escape(room)}(\s+(n°\s*)?\d+)?\b", n)
        if m:
            return m.group(0).strip().capitalize()
    return ""


def _clean(fragment: str, location: str) -> str:
    """Retire les mots de remplissage et le lieu (il a son propre champ), met une majuscule."""
    text = fragment.strip(" ,:-")
    # On travaille sur la version sans accents pour trouver les positions, mais on garde le texte d'origine.
    n = _norm(text)
    m = re.match(FILLERS, n)
    if m:
        text, n = text[m.end():], n[m.end():]
    if location:
        loc = _norm(location)
        m = re.match(rf"(?:dans|au|a|sur|en)\s+(?:le|la|les|l')?\s*{re.escape(loc)}[\s,:]*", n)
        if m:
            text, n = text[m.end():], n[m.end():]
        m = re.match(rf"{re.escape(loc)}\b[\s,:-]*", n)
        if m:
            text, n = text[m.end():], n[m.end():]
        m = re.search(rf"[\s,]+(?:dans|au|a|sur|en)\s+(?:le|la|les|l')?\s*{re.escape(loc)}\s*$", n)
        if m:
            text = text[:m.start()]
    text = text.strip(" ,:-")
    m = re.match(FILLERS, _norm(text))
    if m:
        text = text[m.end():].strip(" ,:-")
    text = re.sub(r"^(?:un|une|des|du)\s+", "", text, flags=re.I)  # « une fuite » -> « Fuite »
    return text[:1].upper() + text[1:] if text else ""


def rules_draft(fragment: str, inherited_location: str = "") -> ReserveDraft:
    """Un défaut décrit par une phrase -> proposition complète, par les règles du métier."""
    n = _norm(fragment)
    scores = {lot: sum(n.count(k) for k in kws) for lot, kws in LOT_KEYWORDS.items()}
    lot = max(scores, key=scores.get) if any(scores.values()) else "autre"
    severity = "mineure"
    for level in ("bloquante", "majeure"):
        if any(k in n for k in SEVERITY_KEYWORDS[level]):
            severity = level
            break
    action = ""
    for required, any_of, text, min_sev, rule_lot in ACTION_RULES:
        if all(w in n for w in required) and _has(n, any_of):
            action = text
            lot = rule_lot or lot
            if min_sev == "bloquante" or (min_sev == "majeure" and severity == "mineure"):
                severity = min_sev
            break
    if not action and lot != "autre":
        action = f"Reprendre l'ouvrage ({LOTS[lot].lower()}) sur la zone concernée"
    location = _location(n) or inherited_location
    return ReserveDraft(location=location, lot=lot, description=_clean(fragment, location), action=action,
                        severity=severity, due_in_days=DUE_DAYS[severity], provider="rules")


def split_note(text: str) -> list[str]:
    """Une dictée de visite -> une phrase par défaut. Une phrase sans défaut complète la précédente."""
    parts: list[str] = []
    for piece in SPLIT.split(_join_marks(text)):
        piece = piece.strip(" ,")
        if not piece:
            continue
        # « … et un carreau cassé » : on coupe sur « et » seulement si chaque côté décrit un défaut.
        sub = re.split(r",?\s+et\s+(?=(?:un|une|des|le|la|les|l')\s)", piece)
        if len(sub) > 1 and all(_has(_norm(s), DEFECT_TERMS) for s in sub):
            candidates = sub
        else:
            candidates = [piece]
        if len(candidates) == 1 and "," in piece:
            chunks = [x.strip() for x in piece.split(",") if x.strip()]
            if len(chunks) > 1 and all(_has(_norm(x), DEFECT_TERMS) for x in chunks) \
                    and len({rules_draft(x).lot for x in chunks}) == len(chunks):
                candidates = chunks
        for c in candidates:
            if parts and not _has(_norm(c), DEFECT_TERMS):
                parts[-1] = f"{parts[-1]}, {c}"
            else:
                parts.append(c)
    return parts or ([text.strip()] if text.strip() else [])


def _join_marks(text: str) -> str:
    """« n° 2 » et les nombres décimaux ne doivent pas être coupés par la ponctuation."""
    return re.sub(r"(\d)[.,](\d)", r"\1‚\2", text)


def _restore(text: str) -> str:
    return text.replace("‚", ",")


def rules_synthesis(facts: dict) -> str:
    """Synthèse chiffrée, sans IA : état, urgences, corps de métier, proposition."""
    total, done, left = facts["total"], facts["done"], facts["open"]
    lines = []
    if total == 0:
        return "Aucun défaut n'a été relevé lors de la visite."
    pct = round(100 * done / total)
    lines.append(f"{total} défaut{'s' if total > 1 else ''} relevé{'s' if total > 1 else ''} sur le chantier "
                 f"{facts['project']}. {done} corrigé{'s' if done > 1 else ''} ({pct} %), "
                 f"{left} reste{'nt' if left > 1 else ''} à corriger.")
    urgent = facts["urgent_open"]
    if urgent:
        items = "; ".join(f"n° {u['number']} {u['description'].rstrip('.')}" + (f" ({u['location']})" if u["location"] else "")
                          for u in urgent[:5])
        lines.append(f"Points urgents : {len(urgent)} défaut{'s' if len(urgent) > 1 else ''} touchant à la sécurité "
                     f"ou à l'usage {'restent ouverts' if len(urgent) > 1 else 'reste ouvert'} : {items}.")
    if facts["by_lot_open"]:
        lots = ", ".join(f"{name} ({count})" for name, count in facts["by_lot_open"][:4])
        lines.append(f"Corps de métier les plus concernés : {lots}.")
    if facts["late"]:
        lines.append(f"{facts['late']} défaut{'s ont' if facts['late'] > 1 else ' a'} dépassé le délai de correction fixé.")
    if left == 0:
        lines.append("Proposition : réception sans réserve, tous les défauts relevés étant levés.")
    elif urgent:
        lines.append("Proposition : différer la réception tant que les points urgents ne sont pas levés.")
    else:
        lines.append(f"Proposition : réception avec réserves, les {left} défaut{'s' if left > 1 else ''} restant"
                     f"{'s' if left > 1 else ''} à lever dans les délais indiqués.")
    lines.append("Cette proposition est à valider par l'ingénieur.")
    return "\n\n".join(lines)


class RulesProvider:
    name = "rules"

    def transcribe(self, audio: bytes, filename: str, content_type: str, duration_s: float = 0) -> tuple[str, Usage]:
        raise AIUnavailable("La transcription vocale demande l'IA en ligne.")

    def analyze(self, text: str) -> tuple[list[ReserveDraft], Usage]:
        drafts: list[ReserveDraft] = []
        for fragment in split_note(text):
            d = rules_draft(_restore(fragment), drafts[-1].location if drafts else "")
            if d.description:
                drafts.append(d)
        return drafts or [rules_draft(text)], Usage()

    def structure(self, text: str) -> tuple[ReserveDraft, Usage]:
        drafts, usage = self.analyze(text)
        return drafts[0], usage

    def describe_photo(self, image: bytes, note: str = "") -> tuple[ReserveDraft, Usage]:
        raise AIUnavailable("La lecture des photos demande l'IA en ligne avec un modèle de vision.")

    def synthesize(self, facts: dict) -> tuple[str, Usage]:
        return rules_synthesis(facts), Usage()


# ---------- fournisseur en ligne ----------

_ANALYZE = (
    "Tu es ingénieur en génie civil et tu rédiges un rapport de finition (réserves) en Afrique francophone. "
    "On te donne la note dictée pendant la visite. Elle peut décrire un ou plusieurs défauts. "
    "Renvoie UNIQUEMENT un objet JSON de la forme {{\"reserves\": [ ... ]}}, un objet par défaut, avec : "
    '"location" (pièce ou zone ; reprends celle du défaut précédent si la note ne la répète pas ; chaîne vide si inconnue), '
    '"lot" (une valeur parmi : {lots}), '
    '"description" (le défaut constaté, en une phrase courte et professionnelle, sans le lieu), '
    '"action" (le travail précis attendu de l\'entreprise, à l\'infinitif, en une phrase), '
    '"severity" (une valeur parmi : {sev} ; bloquante = sécurité ou usage empêché, majeure = fonctionnement '
    'dégradé ou risque d\'aggravation, mineure = aspect). '
    "N'invente aucun défaut qui ne soit pas dans la note, et n'ajoute aucune cote ni marque."
)

_PHOTO = (
    "Tu es ingénieur en génie civil et tu relèves les défauts de finition d'un bâtiment. Décris le défaut "
    "principal visible sur la photo. Renvoie UNIQUEMENT un objet JSON avec : "
    '"location" (chaîne vide si la photo ne permet pas de le dire), "lot" (une valeur parmi : {lots}), '
    '"description" (une phrase courte et professionnelle), "action" (le travail attendu, à l\'infinitif), '
    '"severity" (une valeur parmi : {sev}). Si aucun défaut n\'est visible, mets "description" à "". '
    "Ne décris que ce qui est réellement visible."
)

_SYNTHESIS = (
    "Tu es ingénieur en génie civil. Rédige la synthèse d'un rapport de finition à partir des données JSON "
    "fournies, en français professionnel, en 4 à 6 paragraphes courts séparés par une ligne vide : état général "
    "chiffré ; points urgents (avec leur numéro) ; corps de métier les plus concernés et priorités ; délais ; "
    "proposition sur la réception (sans réserve, avec réserves, ou à différer), présentée comme une proposition "
    "à valider par l'ingénieur. N'utilise que les données fournies, sans titre ni liste à puces, sans markdown."
)


class OpenAICompatProvider:
    name = "openai"

    def __init__(self, settings: Settings):
        self.s = settings
        self._fallback = RulesProvider()

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.s.ai_base_url, timeout=90,
                            headers={"Authorization": f"Bearer {self.s.ai_api_key}"})

    def _chat(self, model: str, messages: list[dict], json_mode: bool = True, temperature: float = 0) -> tuple[str, Usage]:
        body: dict = {"model": model, "temperature": temperature, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        with self._client() as c:
            r = c.post("/chat/completions", json=body)
            r.raise_for_status()
            data = r.json()
        tokens = data.get("usage") or {}
        usage = Usage(provider=self.name, model=model, input_tokens=int(tokens.get("prompt_tokens", 0)),
                      output_tokens=int(tokens.get("completion_tokens", 0)))
        return str(data["choices"][0]["message"]["content"]), usage

    @staticmethod
    def _to_draft(item: dict, base: ReserveDraft, provider: str) -> ReserveDraft:
        lot = item.get("lot") if item.get("lot") in LOTS else base.lot
        severity = item.get("severity") if item.get("severity") in SEVERITIES else base.severity
        return ReserveDraft(location=str(item.get("location") or base.location), lot=lot, severity=severity,
                            description=str(item.get("description") or base.description).strip(),
                            action=str(item.get("action") or base.action).strip(),
                            due_in_days=DUE_DAYS[severity], provider=provider)

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
        seconds = float(data.get("duration") or duration_s or 0)
        usage = Usage(provider=self.name, model=self.s.ai_asr_model, audio_seconds=seconds)
        return str(data.get("text", "")).strip(), usage

    def analyze(self, text: str) -> tuple[list[ReserveDraft], Usage]:
        base_drafts, _ = self._fallback.analyze(text)
        prompt = _ANALYZE.format(lots=", ".join(LOTS), sev=", ".join(SEVERITIES))
        try:
            content, usage = self._chat(self.s.ai_llm_model, [{"role": "system", "content": prompt},
                                                              {"role": "user", "content": text}])
            items = json.loads(content).get("reserves")
            if not isinstance(items, list) or not items:
                raise ValueError("pas de réserve")
        except (httpx.HTTPError, KeyError, IndexError, ValueError, AttributeError):
            for d in base_drafts:
                d.provider = "rules (repli)"
            return base_drafts, Usage()  # l'appel a échoué : rien n'est facturé
        drafts = []
        for i, item in enumerate(i for i in items if isinstance(i, dict)):
            base = base_drafts[min(i, len(base_drafts) - 1)]
            draft = self._to_draft(item, base, self.name)
            if draft.description:
                drafts.append(draft)
        return drafts or base_drafts, usage

    def structure(self, text: str) -> tuple[ReserveDraft, Usage]:
        drafts, usage = self.analyze(text)
        return drafts[0], usage

    def describe_photo(self, image: bytes, note: str = "") -> tuple[ReserveDraft, Usage]:
        if not self.s.ai_vision_model:
            raise AIUnavailable("Aucun modèle de vision configuré (RESERVA_AI_VISION_MODEL).")
        prompt = _PHOTO.format(lots=", ".join(LOTS), sev=", ".join(SEVERITIES))
        url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
        user: list[dict] = [{"type": "image_url", "image_url": {"url": url}}]
        if note.strip():
            user.insert(0, {"type": "text", "text": f"Note de l'ingénieur : {note.strip()}"})
        try:
            content, usage = self._chat(self.s.ai_vision_model, [{"role": "system", "content": prompt},
                                                                 {"role": "user", "content": user}])
            item = json.loads(content)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise AIUnavailable(f"Lecture de la photo indisponible : {e}") from e
        base = rules_draft(str(item.get("description") or note or ""))
        return self._to_draft(item, base, self.name), usage

    def synthesize(self, facts: dict) -> tuple[str, Usage]:
        try:
            content, usage = self._chat(self.s.ai_llm_model, [
                {"role": "system", "content": _SYNTHESIS},
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False, default=str)}],
                json_mode=False, temperature=0.2)
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            return rules_synthesis(facts), Usage()
        text = re.sub(r"[*#`]", "", content).strip()
        return text or rules_synthesis(facts), usage


def get_provider(settings: Settings | None = None) -> AIProvider:
    s = settings or get_settings()
    if s.ai_provider == "openai" and s.ai_api_key:
        return OpenAICompatProvider(s)
    return RulesProvider()
