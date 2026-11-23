"""Routes métier : chantiers, réserves, médias, synchro, IA, rapport, envoi. Tout est sous /api.

Chaque route exige une session, et ne voit que les données du cabinet de l'utilisateur.
Rôles : lecteur (lecture) < technicien (saisie) < ingenieur (validation, envoi) < admin.
"""

import io
from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, func, select

from app import vocab
from app.ai import AIUnavailable, RulesProvider, get_provider
from app.auth import current_user, make_share_token, min_role, read_share_token
from app.billing import charge, fcfa
from app.config import get_settings
from app.db import get_session
from app.dispatch import build_message, build_sms, get_channel, wa_link
from app.models import (ROLES, Company, DispatchLog, Media, Organization, Project, Reserve, User, Visit,
                        as_utc, now)
from app.plans import check_can_create_report, check_can_store, check_feature, plan_of
from app.report import PdfUnavailable, render_report
from app.schemas import (CompanyIn, DispatchIn, ProjectIn, ProjectPatch, ReserveIn, StatusChange, StructureIn, SyncPush,
                         VisitIn)

router = APIRouter(prefix="/api")
OPEN_STATUSES = ("ouverte", "refusee")
VALIDATION_STATUSES = {"levee", "refusee"}  # décisions réservées à l'ingénieur
MEDIA_KINDS = {"photo_avant", "photo_apres", "audio"}
MAX_UPLOAD = 25 * 1024 * 1024

Reader = Depends(current_user)
Writer = Depends(min_role("technicien"))
Engineer = Depends(min_role("ingenieur"))


# ---------- utilitaires ----------

def _project(db: Session, project_id: str, user: User) -> Project:
    p = db.get(Project, project_id)
    if not p or p.org_id != user.org_id:  # même réponse qu'un chantier inexistant : rien ne fuit
        raise HTTPException(404, "Chantier introuvable")
    return p


def _reserve(db: Session, reserve_id: str, user: User) -> Reserve:
    r = db.get(Reserve, reserve_id)
    if not r or r.deleted:
        raise HTTPException(404, "Réserve introuvable")
    _project(db, r.project_id, user)
    return r


def _media_out(m: Media) -> dict:
    return {**m.model_dump(), "url": f"/api/media/{m.id}"}


def _reserve_out(db: Session, r: Reserve) -> dict:
    media = db.exec(select(Media).where(Media.reserve_id == r.id).order_by(Media.created_at)).all()
    return {**r.model_dump(), "media": [_media_out(m) for m in media]}


def _check_vocab(lot: str) -> None:
    if lot not in vocab.LOTS:
        raise HTTPException(422, f"Lot inconnu : {lot}")


def _check_transition(old: str, new: str, user: User) -> None:
    if new == old:
        return
    if new not in vocab.TRANSITIONS[old]:
        raise HTTPException(409, f"Transition interdite : {old} -> {new}")
    if new in VALIDATION_STATUSES and ROLES[user.role] < ROLES["ingenieur"]:
        raise HTTPException(403, "Seul un ingénieur peut valider ou refuser une levée")


def _upsert_reserve(db: Session, reserve_id: str, body: ReserveIn, user: User) -> tuple[Reserve, str]:
    """Crée ou met à jour. Renvoie (réserve, résultat) avec résultat = created | updated | stale.

    "stale" : le serveur détient une modification plus récente (autre téléphone) ; on la garde.
    """
    _project(db, body.project_id, user)
    _check_vocab(body.lot)
    data = body.model_dump(exclude={"updated_at", "id"})
    existing = db.get(Reserve, reserve_id)
    if existing is None:
        _check_transition("ouverte", body.status, user)
        number = (db.exec(select(func.max(Reserve.number)).where(Reserve.project_id == body.project_id)).one() or 0) + 1
        r = Reserve(id=reserve_id, number=number, client_updated_at=body.updated_at, **data)
        db.add(r)
        return r, "created"
    _project(db, existing.project_id, user)  # un id pris par un autre cabinet reste invisible
    if existing.project_id != body.project_id:
        raise HTTPException(409, "Une réserve ne change pas de chantier")
    if body.updated_at and existing.client_updated_at and body.updated_at < existing.client_updated_at:
        return existing, "stale"
    _check_transition(existing.status, body.status, user)
    for key, value in data.items():
        setattr(existing, key, value)
    if existing.deleted:
        _drop_media(db, [existing.id])
    existing.client_updated_at = body.updated_at or existing.client_updated_at
    existing.updated_at = now()
    db.add(existing)
    return existing, "updated"


# ---------- référentiel ----------

@router.get("/vocab")
def get_vocab() -> dict:
    return {"lots": vocab.LOTS, "severities": vocab.SEVERITIES, "statuses": vocab.STATUSES,
            "visit_kinds": vocab.VISIT_KINDS, "transitions": {k: sorted(v) for k, v in vocab.TRANSITIONS.items()},
            "roles": list(ROLES)}


# ---------- chantiers, entreprises, visites ----------

@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, user: User = Engineer, db: Session = Depends(get_session)) -> Project:
    if body.id and db.get(Project, body.id):
        return _project(db, body.id, user)  # rejouable
    check_can_create_report(db, db.get(Organization, user.org_id))
    p = Project(org_id=user.org_id, **body.model_dump(exclude_none=True))
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/projects")
def list_projects(user: User = Reader, db: Session = Depends(get_session)) -> list[dict]:
    """Tableau de bord du cabinet : chaque chantier avec son avancement."""
    out = []
    for p in db.exec(select(Project).where(Project.org_id == user.org_id).order_by(Project.created_at.desc())).all():
        rows = db.exec(select(Reserve.status, func.count()).where(Reserve.project_id == p.id, Reserve.deleted == False)  # noqa: E712
                       .group_by(Reserve.status)).all()
        counts = dict(rows)
        total = sum(counts.values())
        out.append({**p.model_dump(), "total": total, "open": sum(counts.get(s, 0) for s in OPEN_STATUSES),
                    "progress": round(100 * counts.get("levee", 0) / total) if total else 0})
    return out


def _drop_media(db: Session, reserve_ids: list[str]) -> None:
    """Supprime photos et notes vocales (fichiers compris) : la place est rendue au compte."""
    if not reserve_ids:
        return
    for m in db.exec(select(Media).where(Media.reserve_id.in_(reserve_ids))).all():
        (get_settings().media_dir / m.filename).unlink(missing_ok=True)
        db.delete(m)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, user: User = Engineer, db: Session = Depends(get_session)) -> dict:
    """Supprime un rapport avec ses défauts et ses photos. Rejouable : un rapport déjà supprimé répond pareil."""
    p = db.get(Project, project_id)
    if p is None:
        return {"deleted": True}
    _project(db, project_id, user)
    reserves = db.exec(select(Reserve).where(Reserve.project_id == project_id)).all()
    _drop_media(db, [r.id for r in reserves])
    db.flush()
    for row in [*reserves, *db.exec(select(Company).where(Company.project_id == project_id)).all(),
                *db.exec(select(Visit).where(Visit.project_id == project_id)).all()]:
        db.delete(row)
    db.flush()
    db.delete(p)
    db.commit()
    return {"deleted": True}


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, body: ProjectPatch, user: User = Engineer, db: Session = Depends(get_session)) -> Project:
    """Renomme le chantier, ou enregistre la synthèse corrigée par l'ingénieur."""
    p = _project(db, project_id, user)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(p, key, value.strip() if isinstance(value, str) else value)
    p.updated_at = now()
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/projects/{project_id}")
def get_project(project_id: str, user: User = Reader, db: Session = Depends(get_session)) -> dict:
    p = _project(db, project_id, user)
    companies = db.exec(select(Company).where(Company.project_id == project_id)).all()
    visits = db.exec(select(Visit).where(Visit.project_id == project_id).order_by(Visit.visit_date.desc())).all()
    return {**p.model_dump(), "companies": companies, "visits": visits}


@router.post("/projects/{project_id}/companies", status_code=201)
def add_company(project_id: str, body: CompanyIn, user: User = Engineer, db: Session = Depends(get_session)) -> Company:
    _project(db, project_id, user)
    _check_vocab(body.lot)
    if body.id and (found := db.get(Company, body.id)):
        _project(db, found.project_id, user)
        return found
    c = Company(project_id=project_id, **body.model_dump(exclude_none=True))
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/companies/{company_id}")
def delete_company(company_id: str, user: User = Engineer, db: Session = Depends(get_session)) -> dict:
    """Retire un artisan du chantier. Ses défauts restent, rattachés à leur corps de métier."""
    c = db.get(Company, company_id)
    if c is None:
        return {"deleted": True}
    _project(db, c.project_id, user)
    for r in db.exec(select(Reserve).where(Reserve.company_id == c.id)).all():
        r.company_id = None
        r.updated_at = now()
        db.add(r)
    db.flush()
    db.delete(c)
    db.commit()
    return {"deleted": True}


@router.post("/projects/{project_id}/visits", status_code=201)
def add_visit(project_id: str, body: VisitIn, user: User = Writer, db: Session = Depends(get_session)) -> Visit:
    _project(db, project_id, user)
    if body.id and (found := db.get(Visit, body.id)):
        _project(db, found.project_id, user)
        return found
    data = body.model_dump(exclude_none=True)
    data["inspector"] = data.get("inspector") or user.name
    v = Visit(project_id=project_id, **data)
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


@router.get("/projects/{project_id}/stats")
def project_stats(project_id: str, user: User = Reader, db: Session = Depends(get_session)) -> dict:
    _project(db, project_id, user)
    rows = db.exec(select(Reserve).where(Reserve.project_id == project_id, Reserve.deleted == False)).all()  # noqa: E712
    by_status = {k: 0 for k in vocab.STATUSES}
    by_lot: dict[str, dict[str, int]] = {}
    for r in rows:
        by_status[r.status] += 1
        lot = by_lot.setdefault(r.lot, {"total": 0, "open": 0})
        lot["total"] += 1
        lot["open"] += r.status in OPEN_STATUSES
    done = by_status["levee"]
    return {"total": len(rows), "by_status": by_status, "by_lot": by_lot,
            "progress": round(100 * done / len(rows)) if rows else 0}


# ---------- réserves ----------

@router.get("/projects/{project_id}/reserves")
def list_reserves(project_id: str, status: str | None = None, lot: str | None = None,
                  company_id: str | None = None, user: User = Reader,
                  db: Session = Depends(get_session)) -> list[dict]:
    _project(db, project_id, user)
    q = select(Reserve).where(Reserve.project_id == project_id, Reserve.deleted == False)  # noqa: E712
    if status:
        q = q.where(Reserve.status == status)
    if lot:
        q = q.where(Reserve.lot == lot)
    if company_id:
        q = q.where(Reserve.company_id == company_id)
    return [_reserve_out(db, r) for r in db.exec(q.order_by(Reserve.number)).all()]


@router.put("/reserves/{reserve_id}")
def put_reserve(reserve_id: str, body: ReserveIn, user: User = Writer, db: Session = Depends(get_session)) -> dict:
    r, result = _upsert_reserve(db, reserve_id, body, user)
    db.commit()
    db.refresh(r)
    return {**_reserve_out(db, r), "result": result}


@router.get("/reserves/{reserve_id}")
def get_reserve(reserve_id: str, user: User = Reader, db: Session = Depends(get_session)) -> dict:
    return _reserve_out(db, _reserve(db, reserve_id, user))


@router.post("/reserves/{reserve_id}/status")
def change_status(reserve_id: str, body: StatusChange, user: User = Writer,
                  db: Session = Depends(get_session)) -> dict:
    """Changement de statut en ligne. Lever une réserve exige une photo « après » comme preuve."""
    r = _reserve(db, reserve_id, user)
    if body.status != r.status:
        _check_transition(r.status, body.status, user)
        if body.status == "levee":
            proof = db.exec(select(Media).where(Media.reserve_id == r.id, Media.kind == "photo_apres")).first()
            if not proof:
                raise HTTPException(409, "Une photo « après » est obligatoire pour lever une réserve")
        r.status = body.status
        r.updated_at = now()
        db.add(r)
        db.commit()
        db.refresh(r)
    return _reserve_out(db, r)


# ---------- médias ----------

def _shrink_photo(raw: bytes) -> bytes:
    """Redresse (EXIF) et réduit à 1600 px : rapports légers et données mobiles économisées."""
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    img.thumbnail((1600, 1600))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80, optimize=True)
    return out.getvalue()


@router.put("/media/{media_id}")
async def put_media(media_id: str, reserve_id: str = Form(...), kind: str = Form("photo_avant"),
                    file: UploadFile = File(...), user: User = Writer, db: Session = Depends(get_session)) -> dict:
    if found := db.get(Media, media_id):
        _reserve(db, found.reserve_id, user)
        return _media_out(found)  # déjà reçu : l'envoi peut être rejoué après une coupure
    if kind not in MEDIA_KINDS:
        raise HTTPException(422, f"Type de média inconnu : {kind}")
    try:
        UUID(media_id)
    except ValueError:
        raise HTTPException(422, "L'identifiant du média doit être un UUID") from None
    _reserve(db, reserve_id, user)
    raw = await file.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "Fichier trop lourd (25 Mo max)")
    content_type = file.content_type or "application/octet-stream"
    if kind.startswith("photo"):
        try:
            raw, content_type, ext = _shrink_photo(raw), "image/jpeg", ".jpg"
        except Exception:
            raise HTTPException(422, "Image illisible") from None
    else:
        ext = {"audio/webm": ".webm", "audio/mp4": ".m4a", "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
               "audio/wav": ".wav"}.get(content_type.split(";")[0], ".bin")
    check_can_store(db, db.get(Organization, user.org_id), len(raw))
    filename = f"{media_id}{ext}"
    (get_settings().media_dir / filename).write_bytes(raw)
    m = Media(id=media_id, reserve_id=reserve_id, kind=kind, filename=filename, content_type=content_type, size=len(raw))
    db.add(m)
    db.commit()
    db.refresh(m)
    return _media_out(m)


@router.get("/media/{media_id}")
def get_media(media_id: str, user: User = Reader, db: Session = Depends(get_session)) -> FileResponse:
    m = db.get(Media, media_id)
    if not m:
        raise HTTPException(404, "Média introuvable")
    _reserve(db, m.reserve_id, user)
    path = get_settings().media_dir / m.filename
    if not path.exists():
        raise HTTPException(404, "Média introuvable")
    return FileResponse(path, media_type=m.content_type)


# ---------- synchronisation hors ligne ----------

@router.post("/sync/push")
def sync_push(body: SyncPush, user: User = Writer, db: Session = Depends(get_session)) -> dict:
    """Le téléphone envoie tout ce qu'il a créé ou modifié hors ligne. Rejouable sans doublon."""
    results = []
    for item in body.reserves:
        try:
            r, result = _upsert_reserve(db, item.id, item, user)
            db.commit()
            results.append({"id": item.id, "result": result, "number": r.number})
        except HTTPException as e:
            db.rollback()
            results.append({"id": item.id, "result": "rejected", "detail": e.detail})
    return {"server_time": now().isoformat(), "results": results}


@router.get("/sync/pull")
def sync_pull(project_id: str, since: datetime | None = None, user: User = Reader,
              db: Session = Depends(get_session)) -> dict:
    """Tout ce qui a changé sur le chantier depuis `since` (valeur `server_time` du dernier appel)."""
    _project(db, project_id, user)
    server_time = now()
    since = as_utc(since)

    def changed(model, *where):
        q = select(model).where(*where)
        return db.exec(q.where(model.updated_at > since) if since else q).all()

    reserves = changed(Reserve, Reserve.project_id == project_id)
    ids = [r.id for r in db.exec(select(Reserve).where(Reserve.project_id == project_id)).all()]
    media = changed(Media, Media.reserve_id.in_(ids)) if ids else []
    return {"server_time": server_time.isoformat(),
            "reserves": reserves,
            "companies": changed(Company, Company.project_id == project_id),
            "visits": changed(Visit, Visit.project_id == project_id),
            "media": [_media_out(m) for m in media]}


# ---------- IA (facturée à l'usage sur le crédit du cabinet) ----------

def _billing_view(org: Organization, charged: int, notice: str = "") -> dict:
    return {"charged_fcfa": fcfa(charged), "balance_fcfa": fcfa(org.balance_mfcfa), "notice": notice}


def _provider_for(org: Organization):
    """Le fournisseur configuré ; sans crédit, les règles du métier, gratuites : on ne bloque jamais la saisie."""
    provider = get_provider()
    if provider.name != "rules" and org.balance_mfcfa <= 0:
        return RulesProvider(), "Crédit IA épuisé : proposition par les règles du métier (gratuite)."
    return provider, ""


@router.post("/ai/structure")
def ai_structure(body: StructureIn, user: User = Writer, db: Session = Depends(get_session)) -> dict:
    """Note dictée -> un ou plusieurs défauts (lieu, corps de métier, description, travail à faire, gravité, délai).

    `draft` est le premier défaut (celui de la photo) ; `drafts` les contient tous, quand la note en décrit plusieurs.
    """
    org = db.get(Organization, user.org_id)
    provider, notice = _provider_for(org)
    drafts, usage = provider.analyze(body.text)
    charged = charge(db, org, user, "structure", usage)
    return {"draft": drafts[0], "drafts": drafts, **_billing_view(org, charged, notice)}


@router.post("/ai/transcribe")
async def ai_transcribe(file: UploadFile = File(...), duration_s: float = Form(0), user: User = Writer,
                        db: Session = Depends(get_session)) -> dict:
    """Note vocale -> texte + défauts proposés."""
    org = db.get(Organization, user.org_id)
    provider = get_provider()
    if provider.name != "rules" and org.balance_mfcfa <= 0:
        raise HTTPException(402, "Crédit IA épuisé : rechargez pour utiliser la dictée, ou saisissez le texte.")
    try:
        text, usage = provider.transcribe(await file.read(), file.filename or "note.webm", file.content_type or "",
                                          duration_s)
    except AIUnavailable as e:
        raise HTTPException(503, str(e)) from e
    charged = charge(db, org, user, "transcribe", usage)
    drafts = []
    if text:
        drafts, usage2 = provider.analyze(text)
        charged += charge(db, org, user, "structure", usage2)
    return {"text": text, "draft": drafts[0] if drafts else None, "drafts": drafts, **_billing_view(org, charged)}


@router.post("/ai/reserves/{reserve_id}/describe")
def ai_describe_photo(reserve_id: str, user: User = Writer, db: Session = Depends(get_session)) -> dict:
    """Défaut photographié sans note : l'IA lit la photo et remplit ce qui est vide (rien n'est écrasé)."""
    r = _reserve(db, reserve_id, user)
    photo = db.exec(select(Media).where(Media.reserve_id == r.id, Media.kind == "photo_avant")
                    .order_by(Media.created_at)).first()
    path = get_settings().media_dir / photo.filename if photo else None
    if not path or not path.exists():
        raise HTTPException(404, "Ce défaut n'a pas encore de photo sur le serveur")
    org = db.get(Organization, user.org_id)
    provider = get_provider()
    if provider.name != "rules" and org.balance_mfcfa <= 0:
        raise HTTPException(402, "Crédit IA épuisé : décrivez le défaut en quelques mots.")
    try:
        draft, usage = provider.describe_photo(path.read_bytes(), r.transcript)
    except AIUnavailable as e:
        raise HTTPException(503, str(e)) from e
    charged = charge(db, org, user, "photo", usage)
    if draft.description:
        was_empty = not r.description
        r.description = r.description or draft.description
        r.action = r.action or draft.action
        r.location = r.location or draft.location
        if r.lot == "autre":
            r.lot = draft.lot
        if was_empty:
            r.severity = draft.severity
        if r.due_date is None and r.status != "levee":
            r.due_date = date.today() + timedelta(days=draft.due_in_days)
        r.updated_at = now()
        db.add(r)
        db.commit()
        db.refresh(r)
    return {"reserve": _reserve_out(db, r), "found": bool(draft.description), **_billing_view(org, charged)}


def _facts(db: Session, p: Project) -> dict:
    """Ce que dit le chantier, en chiffres et en lignes : la matière de la synthèse."""
    rows = db.exec(select(Reserve).where(Reserve.project_id == p.id, Reserve.deleted == False)  # noqa: E712
                   .order_by(Reserve.number)).all()
    still = [r for r in rows if r.status != "levee"]
    today = date.today()
    by_lot: dict[str, int] = {}
    for r in still:
        by_lot[vocab.LOTS.get(r.lot, r.lot)] = by_lot.get(vocab.LOTS.get(r.lot, r.lot), 0) + 1

    def line(r: Reserve) -> dict:
        return {"number": r.number, "location": r.location, "lot": vocab.LOTS.get(r.lot, r.lot),
                "description": r.description or r.transcript, "action": r.action,
                "severity": vocab.SEVERITIES.get(r.severity, r.severity), "status": vocab.STATUSES.get(r.status, r.status),
                "due_date": r.due_date.isoformat() if r.due_date else None}

    return {
        "project": p.name, "client": p.client, "date": today.strftime("%d/%m/%Y"),
        "total": len(rows), "done": len(rows) - len(still), "open": len(still),
        "waiting_check": sum(1 for r in still if r.status == "levee_declaree"),
        "urgent_open": [line(r) for r in still if r.severity == "bloquante"],
        "by_lot_open": sorted(by_lot.items(), key=lambda kv: -kv[1]),
        "late": sum(1 for r in still if r.due_date and r.due_date < today),
        "open_items": [line(r) for r in still[:60]],
    }


@router.post("/projects/{project_id}/synthesis")
def write_synthesis(project_id: str, user: User = Engineer, db: Session = Depends(get_session)) -> dict:
    """Rédige la synthèse du rapport (état, urgences, priorités, proposition de réception).

    Elle remplace la précédente ; l'ingénieur la relit et la corrige ensuite (PATCH /projects/{id}).
    """
    p = _project(db, project_id, user)
    org = db.get(Organization, user.org_id)
    provider, notice = _provider_for(org)
    text, usage = provider.synthesize(_facts(db, p))
    charged = charge(db, org, user, "synthese", usage)
    p.summary, p.summary_at, p.updated_at = text, now(), now()
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"summary": p.summary, "summary_at": p.summary_at, "provider": provider.name, **_billing_view(org, charged, notice)}


# ---------- rapport et envoi ----------

def _open_for(db: Session, project_id: str, company: Company) -> list[Reserve]:
    rows = db.exec(select(Reserve).where(Reserve.project_id == project_id, Reserve.deleted == False,  # noqa: E712
                                         Reserve.status.in_(OPEN_STATUSES)).order_by(Reserve.number)).all()
    return [r for r in rows if r.company_id == company.id or (r.company_id is None and r.lot == company.lot)]


def _build_pdf(db: Session, p: Project, company_id: str | None, open_only: bool) -> Response:
    companies = db.exec(select(Company).where(Company.project_id == p.id)).all()
    title = "Rapport de finition"
    if company_id:
        company = db.get(Company, company_id)
        if not company or company.project_id != p.id:
            raise HTTPException(404, "Entreprise introuvable")
        reserves = _open_for(db, p.id, company)
        title = f"Réserves à lever — {company.name}"
    else:
        q = select(Reserve).where(Reserve.project_id == p.id, Reserve.deleted == False)  # noqa: E712
        if open_only:
            q = q.where(Reserve.status.in_(OPEN_STATUSES))
        reserves = db.exec(q).all()
    ids = [r.id for r in reserves]
    media = db.exec(select(Media).where(Media.reserve_id.in_(ids)).order_by(Media.created_at)).all() if ids else []
    org = db.get(Organization, p.org_id)
    # L'en-tête au nom du client (logo, coordonnées) est une fonction des offres payantes.
    try:
        pdf = render_report(org if plan_of(org).get("branding") else None, p, reserves, media, companies, title)
    except PdfUnavailable as e:
        raise HTTPException(503, str(e)) from e
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="reserves-{p.id[:8]}.pdf"'})


@router.get("/projects/{project_id}/report.pdf")
def report_pdf(project_id: str, company_id: str | None = None, open_only: bool = False, user: User = Reader,
               db: Session = Depends(get_session)) -> Response:
    return _build_pdf(db, _project(db, project_id, user), company_id, open_only)


@router.get("/public/report.pdf")
def public_report(t: str, db: Session = Depends(get_session)) -> Response:
    """Rapport ouvert par lien signé, sans compte : c'est ce lien qui part aux entreprises."""
    project_id, company_id = read_share_token(t)
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Chantier introuvable")
    return _build_pdf(db, p, company_id, open_only=True)


@router.post("/projects/{project_id}/share")
def share_link(project_id: str, company_id: str | None = None, user: User = Engineer,
               db: Session = Depends(get_session)) -> dict:
    """Lien de consultation pour le maître d'ouvrage (tout le chantier) ou une entreprise."""
    _project(db, project_id, user)
    s = get_settings()
    return {"url": f"{s.public_base_url.rstrip('/')}/api/public/report.pdf?t={make_share_token(project_id, company_id)}",
            "valid_days": s.share_link_days}


@router.post("/projects/{project_id}/dispatch")
def dispatch(project_id: str, body: DispatchIn, user: User = Engineer, db: Session = Depends(get_session)) -> list[dict]:
    """Prépare (et envoie si send=true) à chaque entreprise la liste de ses réserves ouvertes."""
    p = _project(db, project_id, user)
    check_feature(db.get(Organization, user.org_id), "dispatch", "L'envoi des défauts à chaque artisan")
    channel = get_channel()
    base = get_settings().public_base_url.rstrip("/")
    out = []
    for c in db.exec(select(Company).where(Company.project_id == project_id)).all():
        if body.company_ids is not None and c.id not in body.company_ids:
            continue
        reserves = _open_for(db, project_id, c)
        if not reserves:
            continue
        url = f"{base}/api/public/report.pdf?t={make_share_token(project_id, c.id)}"
        message = build_message(p, c, reserves, url)
        entry = {"company_id": c.id, "company": c.name, "reserve_count": len(reserves), "message": message,
                 "whatsapp_link": wa_link(c.phone, message) if c.phone else None, "sent": False, "detail": ""}
        if body.send:
            if not c.phone:
                entry["detail"] = "Pas de numéro de téléphone"
            else:
                text = build_sms(p, reserves, url) if channel.name == "sms" else message
                entry["sent"], entry["detail"] = channel.send(c.phone, text)
            db.add(DispatchLog(project_id=project_id, company_id=c.id, channel=channel.name, ok=entry["sent"],
                               detail=entry["detail"], reserve_count=len(reserves)))
        out.append(entry)
    db.commit()
    return out
