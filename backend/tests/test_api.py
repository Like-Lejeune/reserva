"""Parcours complet : cabinet -> chantier -> réserves hors ligne -> photos -> levée -> PDF -> envoi,
plus cloisonnement entre cabinets, rôles et facturation IA."""

import io
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image


def _make_client(tmp_path, monkeypatch, **env):
    base = {"RESERVA_DATA_DIR": str(tmp_path), "RESERVA_AI_PROVIDER": "rules", "RESERVA_DISPATCH_CHANNEL": "console",
            "RESERVA_SECRET_KEY": "secret-de-test-suffisamment-long-pour-hs256", "RESERVA_BILLING_SECRET": "paiement",
            "RESERVA_ADMIN_LOGINS": '["699000000"]', "RESERVA_PAYMENT_SIMULATION": "true",
            "RESERVA_TRUSTCHANGE_API_KEY": "", **env}
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    from app import config, db, ratelimit, subscriptions

    config.get_settings.cache_clear()
    db.reset_engine()
    ratelimit.reset()
    subscriptions._operators_cache = None
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
    db.reset_engine()
    config.get_settings.cache_clear()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Serveur de test, paiements simulés (réussite immédiate, aucun appel réseau)."""
    yield from _make_client(tmp_path, monkeypatch)


@pytest.fixture()
def tc(tmp_path, monkeypatch):
    """Serveur de test branché sur un faux TrustChange : on pilote ses réponses et on envoie ses webhooks."""
    from app import trustchange

    state = {"status": "PROCESSING", "collect": "ok", "calls": []}

    def fake_request(method, path, *, json_body=None):
        state["calls"].append((method, path, json_body))
        if path == "/collect":
            if state["collect"] == "network":
                raise trustchange.TrustChangeError("TrustChange injoignable")
            if state["collect"] == "conflict":
                raise trustchange.AlreadySubmitted("Référence déjà utilisée", status_code=409)
            if state["collect"] == "refused":
                raise trustchange.TrustChangeError("Numéro invalide pour cet opérateur", status_code=400)
            return {"transactionId": "TC-1", "status": "PROCESSING", "fees": 50}
        if path.startswith("/transaction/"):
            if state["status"] == "NOT_FOUND":
                raise trustchange.TrustChangeError("Transaction introuvable", status_code=404)
            return {"transactionId": "TC-1", "status": state["status"], "externalReference": path.split("/")[-1]}
        if path == "/operators":
            return {"operators": [{"code": "CM_MTN", "name": "MTN Mobile Money", "country": "CM"},
                                  {"paymentCode": "CM_ORANGE", "label": "Orange Money"}]}
        raise AssertionError(path)

    monkeypatch.setattr(trustchange, "_request", fake_request)
    for c in _make_client(tmp_path, monkeypatch, RESERVA_PAYMENT_SIMULATION="false",
                          RESERVA_TRUSTCHANGE_API_KEY="tc_test_cle", RESERVA_TRUSTCHANGE_WEBHOOK_SECRET="secret-webhook"):
        c.state = state
        yield c


def signup(c, login="690 11 22 33", name="Jean Technicien", **extra):
    r = c.post("/api/auth/register", json={"name": name, "login": login, "password": "secret1", **extra})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()


def set_plan(session, plan):
    from sqlmodel import Session

    from app.db import get_engine
    from app.models import Organization

    with Session(get_engine()) as s:
        org = s.get(Organization, session["org"]["id"])
        org.plan = plan
        s.add(org)
        s.commit()


def member(c, h, role, login):
    c.post("/api/org/members", headers=h, json={"name": role, "login": login, "password": "secret1", "role": role})
    tok = c.post("/api/auth/login", json={"login": login, "password": "secret1"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def photo() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), (180, 120, 60)).save(buf, "JPEG")
    return buf.getvalue()


def setup_project(c, h):
    p = c.post("/api/projects", headers=h, json={"name": "Immeuble R+4 Bastos", "client": "SCI Mfoundi", "location": "Yaoundé"}).json()
    co = c.post(f"/api/projects/{p['id']}/companies", headers=h,
                json={"name": "Ets Plomberie Nkolo", "lot": "plomberie", "phone": "+237 690 00 00 00"}).json()
    return p, co


def reserve_body(pid, **kw):
    return {"project_id": pid, "location": "Cuisine", "lot": "plomberie",
            "description": "Fuite sous l'évier", "action": "Reprendre le siphon", "severity": "majeure", **kw}


def test_auth_required_and_login(client):
    assert client.get("/api/projects").status_code == 401
    h, session = signup(client)
    assert session["user"]["role"] == "admin" and session["org"]["balance_fcfa"] == 500
    assert "password_hash" not in session["user"]
    # Un indépendant s'inscrit avec son numéro : son espace personnel porte son nom, rien à configurer.
    assert session["org"]["name"] == "Jean Technicien" and session["user"]["login"] == "690112233"
    assert client.post("/api/auth/login", json={"login": "690112233", "password": "faux"}).status_code == 401
    assert client.post("/api/auth/login", json={"login": "+690 11-22-33", "password": "secret1"}).status_code == 200
    assert client.post("/api/auth/register", json={"name": "Y", "login": "690112233", "password": "secret1"}).status_code == 409
    assert client.post("/api/auth/register", json={"name": "Y", "login": "abc", "password": "secret1"}).status_code == 422
    # L'e-mail marche aussi, et le nom d'entreprise reste possible pour ceux qui en veulent un.
    _, pro = signup(client, "Chef@Cabinet.cm", "Chef", cabinet="Cabinet Fouda Ingénierie")
    assert pro["org"]["name"] == "Cabinet Fouda Ingénierie" and pro["user"]["login"] == "chef@cabinet.cm"
    # Sans rien configurer, un utilisateur seul peut tout faire : créer, valider, partager.
    p = client.post("/api/projects", headers=h, json={"name": "Villa Odza"}).json()
    assert client.post(f"/api/projects/{p['id']}/share", headers=h).status_code == 200


def test_cabinets_are_isolated(client):
    h1, _ = signup(client)
    h2, _ = signup(client, "autre@cabinet.cm", "Autre")
    p, co = setup_project(client, h1)
    rid, mid = str(uuid4()), str(uuid4())
    client.put(f"/api/reserves/{rid}", headers=h1, json=reserve_body(p["id"]))
    client.put(f"/api/media/{mid}", headers=h1, data={"reserve_id": rid, "kind": "photo_avant"},
               files={"file": ("p.jpg", photo(), "image/jpeg")})
    assert client.get("/api/projects", headers=h2).json() == []
    for url in (f"/api/projects/{p['id']}", f"/api/projects/{p['id']}/reserves", f"/api/reserves/{rid}",
                f"/api/media/{mid}", f"/api/projects/{p['id']}/report.pdf", f"/api/projects/{p['id']}/stats",
                f"/api/sync/pull?project_id={p['id']}"):
        assert client.get(url, headers=h2).status_code == 404, url
    assert client.put(f"/api/reserves/{rid}", headers=h2, json=reserve_body(p["id"])).status_code == 404
    assert client.post(f"/api/projects/{p['id']}/dispatch", headers=h2, json={}).status_code == 404
    # Un autre cabinet ne peut pas détourner un id de réserve existant vers son propre chantier.
    p2, _ = setup_project(client, h2)
    assert client.put(f"/api/reserves/{rid}", headers=h2, json=reserve_body(p2["id"])).status_code == 404
    assert len(client.get("/api/org/members", headers=h2).json()) == 1


def test_roles(client):
    h, session = signup(client)
    set_plan(session, "equipe")
    p, _ = setup_project(client, h)
    tech = member(client, h, "technicien", "tech@cabinet.cm")
    reader = member(client, h, "lecteur", "client@cabinet.cm")
    rid = str(uuid4())
    assert client.put(f"/api/reserves/{rid}", headers=reader, json=reserve_body(p["id"])).status_code == 403
    assert client.put(f"/api/reserves/{rid}", headers=tech, json=reserve_body(p["id"])).status_code == 200
    assert client.get(f"/api/projects/{p['id']}/reserves", headers=reader).status_code == 200
    assert client.post("/api/projects", headers=tech, json={"name": "X"}).status_code == 403
    assert client.post("/api/org/members", headers=tech, json={"name": "a", "login": "a@b.cm", "password": "secret1"}).status_code == 403
    # Le technicien déclare la levée ; seul l'ingénieur la valide.
    client.put(f"/api/media/{uuid4()}", headers=tech, data={"reserve_id": rid, "kind": "photo_apres"},
               files={"file": ("p.jpg", photo(), "image/jpeg")})
    assert client.post(f"/api/reserves/{rid}/status", headers=tech, json={"status": "levee_declaree"}).status_code == 200
    assert client.post(f"/api/reserves/{rid}/status", headers=tech, json={"status": "levee"}).status_code == 403
    assert client.put(f"/api/reserves/{rid}", headers=tech, json=reserve_body(p["id"], status="levee")).status_code == 403
    assert client.post(f"/api/reserves/{rid}/status", headers=h, json={"status": "levee"}).json()["status"] == "levee"
    # Un membre désactivé perd l'accès immédiatement.
    tech_id = next(m["id"] for m in client.get("/api/org/members", headers=h).json() if m["role"] == "technicien")
    client.delete(f"/api/org/members/{tech_id}", headers=h)
    assert client.get("/api/projects", headers=tech).status_code == 401


def test_upsert_is_idempotent_and_numbers(client):
    h, _ = signup(client)
    p, _ = setup_project(client, h)
    rid = str(uuid4())
    a = client.put(f"/api/reserves/{rid}", headers=h, json=reserve_body(p["id"])).json()
    b = client.put(f"/api/reserves/{rid}", headers=h, json=reserve_body(p["id"], description="Fuite évier")).json()
    c2 = client.put(f"/api/reserves/{uuid4()}", headers=h, json=reserve_body(p["id"])).json()
    assert (a["result"], b["result"]) == ("created", "updated")
    assert (a["number"], b["number"], c2["number"]) == (1, 1, 2)
    assert len(client.get(f"/api/projects/{p['id']}/reserves", headers=h).json()) == 2


def test_stale_offline_edit_is_ignored(client):
    h, _ = signup(client)
    p, _ = setup_project(client, h)
    rid = str(uuid4())
    client.put(f"/api/reserves/{rid}", headers=h, json=reserve_body(p["id"], description="récent", updated_at="2026-11-13T10:00:00"))
    r = client.put(f"/api/reserves/{rid}", headers=h,
                   json=reserve_body(p["id"], description="ancien", updated_at="2026-11-13T09:00:00")).json()
    assert r["result"] == "stale" and r["description"] == "récent"


def test_sync_push_pull(client):
    h, _ = signup(client)
    p, _ = setup_project(client, h)
    items = [{"id": str(uuid4()), **reserve_body(p["id"])}, {"id": str(uuid4()), **reserve_body(p["id"], lot="inconnu")}]
    push = client.post("/api/sync/push", headers=h, json={"reserves": items}).json()
    assert [r["result"] for r in push["results"]] == ["created", "rejected"]
    assert client.post("/api/sync/push", headers=h, json={"reserves": items[:1]}).json()["results"][0]["result"] == "updated"
    full = client.get("/api/sync/pull", headers=h, params={"project_id": p["id"]}).json()
    assert len(full["reserves"]) == 1 and len(full["companies"]) == 1
    later = client.get("/api/sync/pull", headers=h, params={"project_id": p["id"], "since": full["server_time"]}).json()
    assert later["reserves"] == []


def test_levee_requires_after_photo_and_transitions(client):
    h, _ = signup(client)
    p, _ = setup_project(client, h)
    rid = str(uuid4())
    client.put(f"/api/reserves/{rid}", headers=h, json=reserve_body(p["id"]))
    assert client.post(f"/api/reserves/{rid}/status", headers=h, json={"status": "refusee"}).status_code == 409
    assert client.post(f"/api/reserves/{rid}/status", headers=h, json={"status": "levee"}).status_code == 409
    mid = str(uuid4())
    up = client.put(f"/api/media/{mid}", headers=h, data={"reserve_id": rid, "kind": "photo_apres"},
                    files={"file": ("p.jpg", photo(), "image/jpeg")})
    assert up.status_code == 200
    again = client.put(f"/api/media/{mid}", headers=h, data={"reserve_id": rid, "kind": "photo_apres"},
                       files={"file": ("p.jpg", photo(), "image/jpeg")})
    assert again.json()["id"] == mid
    img = Image.open(io.BytesIO(client.get(f"/api/media/{mid}", headers=h).content))
    assert max(img.size) == 1600
    assert client.post(f"/api/reserves/{rid}/status", headers=h, json={"status": "levee"}).json()["status"] == "levee"
    assert client.get(f"/api/projects/{p['id']}/stats", headers=h).json()["progress"] == 100
    assert client.get("/api/projects", headers=h).json()[0]["progress"] == 100


def test_ai_free_mode(client):
    h, _ = signup(client)
    r = client.post("/api/ai/structure", headers=h, json={"text": "dans la salle de bain 2 le robinet du lavabo a une fuite"}).json()
    d = r["draft"]
    assert (d["lot"], d["severity"], d["location"]) == ("plomberie", "majeure", "Salle de bain 2")
    assert r["charged_fcfa"] == 0 and r["balance_fcfa"] == 500
    assert client.post("/api/ai/transcribe", headers=h, files={"file": ("n.webm", b"x", "audio/webm")}).status_code == 503


class FakeOnlineProvider:
    """Imite un fournisseur en ligne : renvoie une consommation facturable."""

    name = "openai"

    def structure(self, text):
        from app.billing import Usage
        from app.schemas import ReserveDraft

        return (ReserveDraft(lot="plomberie", description=text, action="Reprendre", provider="openai"),
                Usage(provider="openai", model="m", input_tokens=400, output_tokens=100))

    def transcribe(self, audio, filename, content_type, duration_s=0):
        from app.billing import Usage

        return "fuite sous l'évier", Usage(provider="openai", model="asr", audio_seconds=30)


def test_ai_is_metered_and_falls_back_when_empty(client, monkeypatch):
    import app.api as api

    monkeypatch.setattr(api, "get_provider", lambda: FakeOnlineProvider())
    h, session = signup(client)
    r = client.post("/api/ai/structure", headers=h, json={"text": "fuite"}).json()
    # 400 tok x 0,15 $/M + 100 tok x 0,60 $/M = 0,00012 $ -> 0,072 FCFA -> +30 % = 0,094 FCFA
    assert r["charged_fcfa"] == 0.094 and r["balance_fcfa"] == 499.906
    t = client.post("/api/ai/transcribe", headers=h, files={"file": ("n.webm", b"x", "audio/webm")}).json()
    # 30 s x 0,006 $/min = 0,003 $ -> 1,8 FCFA -> +30 % = 2,34 FCFA, plus la structuration
    assert t["charged_fcfa"] == 2.434 and t["text"] == "fuite sous l'évier"
    w = client.get("/api/billing/wallet", headers=h).json()
    assert w["totals"]["calls"] == 3 and w["totals"]["spent_fcfa"] == 2.528
    assert w["balance_fcfa"] == 497.472 and w["credits"][0]["kind"] == "bonus"
    # Solde à zéro : la structuration bascule sur le mode gratuit, la dictée est refusée.
    from sqlmodel import Session

    from app.db import get_engine
    from app.models import Organization

    with Session(get_engine()) as s:
        org = s.get(Organization, session["org"]["id"])
        org.balance_mfcfa = 0
        s.add(org)
        s.commit()
    r = client.post("/api/ai/structure", headers=h, json={"text": "fuite au robinet"}).json()
    assert r["charged_fcfa"] == 0 and r["draft"]["provider"] == "rules" and "épuisé" in r["notice"]
    assert client.post("/api/ai/transcribe", headers=h, files={"file": ("n.webm", b"x", "audio/webm")}).status_code == 402
    # Recharge : réservée au serveur de paiement, et jamais créditée deux fois.
    body = {"org_id": session["org"]["id"], "amount_fcfa": 2000, "reference": "MOMO-123"}
    assert client.post("/api/billing/credit", json=body).status_code == 403
    assert client.post("/api/billing/credit", headers=h, json=body).status_code == 403
    ok = {"X-Billing-Secret": "paiement"}
    assert client.post("/api/billing/credit", headers=ok, json=body).json()["balance_fcfa"] == 2000
    assert client.post("/api/billing/credit", headers=ok, json=body).json()["balance_fcfa"] == 2000


def test_branded_report_share_link_and_dispatch(client):
    h, session = signup(client)
    set_plan(session, "pro")
    p, co = setup_project(client, h)
    client.patch("/api/org", headers=h, json={"registration_no": "ONIGC 1234", "phone": "+237 6 90 00 00 00", "address": "Bastos, Yaoundé"})
    logo = io.BytesIO()
    Image.new("RGB", (400, 200), (31, 58, 95)).save(logo, "PNG")
    assert client.put("/api/org/logo", headers=h, files={"file": ("l.png", logo.getvalue(), "image/png")}).json()["has_logo"]
    rid = str(uuid4())
    client.put(f"/api/reserves/{rid}", headers=h, json=reserve_body(p["id"]))
    client.put(f"/api/reserves/{uuid4()}", headers=h, json=reserve_body(p["id"], lot="peinture", description="Coulures", location="Salon"))
    client.put(f"/api/media/{uuid4()}", headers=h, data={"reserve_id": rid, "kind": "photo_avant"},
               files={"file": ("p.jpg", photo(), "image/jpeg")})
    pdf = client.get(f"/api/projects/{p['id']}/report.pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    out = client.post(f"/api/projects/{p['id']}/dispatch", headers=h, json={"send": True}).json()
    assert len(out) == 1 and out[0]["sent"] and out[0]["reserve_count"] == 1
    assert out[0]["whatsapp_link"].startswith("https://wa.me/237690000000?text=")
    assert "Fuite sous l'évier" in out[0]["message"]
    # Le lien envoyé à l'entreprise s'ouvre sans compte ; un lien trafiqué est refusé.
    link = out[0]["message"].split("Rapport PDF avec photos : ")[1].replace("http://localhost:8000", "")
    assert client.get(link).content[:4] == b"%PDF"
    assert client.get(link[:-3] + "abc").status_code == 401
    assert client.get(f"/api/projects/{p['id']}/report.pdf").status_code == 401
    share = client.post(f"/api/projects/{p['id']}/share", headers=h).json()["url"].replace("http://localhost:8000", "")
    assert client.get(share).content[:4] == b"%PDF"


def test_free_plan_limits_and_usage_counters(client, monkeypatch):
    h, session = signup(client)
    assert session["org"]["plan"] == "gratuit"
    plans = client.get("/api/plans").json()  # public : lu par le site vitrine
    assert [p["key"] for p in plans] == ["gratuit", "pro", "equipe"] and plans[0]["max_reports"] == 3
    # 3 rapports maximum en gratuit ; rejouer une création déjà faite ne compte pas.
    ids = [client.post("/api/projects", headers=h, json={"name": f"Chantier {i}"}).json()["id"] for i in range(3)]
    blocked = client.post("/api/projects", headers=h, json={"name": "Chantier 4"})
    assert blocked.status_code == 402 and "3 rapports" in blocked.json()["detail"]
    assert client.post("/api/projects", headers=h, json={"id": ids[0], "name": "Chantier 0"}).status_code == 201
    # Un seul membre en gratuit.
    assert client.post("/api/org/members", headers=h, json={"name": "a", "login": "a@b.cm", "password": "secret1"}).status_code == 402
    # Stockage : la photo qui dépasse est refusée, celles d'avant restent.
    rid = str(uuid4())
    client.put(f"/api/reserves/{rid}", headers=h, json=reserve_body(ids[0]))
    up = client.put(f"/api/media/{uuid4()}", headers=h, data={"reserve_id": rid, "kind": "photo_avant"},
                    files={"file": ("p.jpg", photo(), "image/jpeg")})
    assert up.status_code == 200
    size = up.json()["size"]
    from app import plans as plans_module

    monkeypatch.setitem(plans_module.PLANS["gratuit"], "storage_mb", size * 1.5 / plans_module.MB)
    full = client.put(f"/api/media/{uuid4()}", headers=h, data={"reserve_id": rid, "kind": "photo_apres"},
                      files={"file": ("p.jpg", photo(), "image/jpeg")})
    assert full.status_code == 402 and "Pro" in full.json()["detail"]
    u = client.get("/api/account/usage", headers=h).json()
    assert u["plan"]["key"] == "gratuit" and u["reports"] == {"used": 3, "limit": 3}
    assert u["storage"]["used_bytes"] == size and u["storage"]["limit_bytes"] == size * 1.5
    assert (u["defects"], u["defects_fixed"], u["photos"], u["members"]["used"]) == (1, 0, 1, 1)
    assert u["ai"]["balance_fcfa"] == 500 and u["ai"]["month"]["calls"] == 0
    # Supprimer un rapport rend la place : stockage et nombre de rapports.
    assert client.delete(f"/api/projects/{ids[0]}", headers=h).json() == {"deleted": True}
    assert client.delete(f"/api/projects/{ids[0]}", headers=h).status_code == 200
    u = client.get("/api/account/usage", headers=h).json()
    assert u["reports"]["used"] == 2 and u["storage"]["used_bytes"] == 0 and u["photos"] == 0
    assert client.post("/api/projects", headers=h, json={"name": "Chantier 4"}).status_code == 201
    # Supprimer un défaut rend aussi la place de ses photos.
    rid2 = str(uuid4())
    client.put(f"/api/reserves/{rid2}", headers=h, json=reserve_body(ids[1]))
    client.put(f"/api/media/{uuid4()}", headers=h, data={"reserve_id": rid2, "kind": "photo_avant"},
               files={"file": ("p.jpg", photo(), "image/jpeg")})
    client.put(f"/api/reserves/{rid2}", headers=h, json=reserve_body(ids[1], deleted=True))
    assert client.get("/api/account/usage", headers=h).json()["storage"]["used_bytes"] == 0
    # En Pro, plus de limite de rapports.
    set_plan(session, "pro")
    assert client.post("/api/projects", headers=h, json={"name": "Chantier 5"}).status_code == 201


def test_platform_admin(client):
    h, session = signup(client)
    setup_project(client, h)
    # Un client, même « admin » de son espace, ne voit pas l'administration de la plateforme.
    assert session["user"]["is_staff"] is False
    for url in ("/api/admin/overview", "/api/admin/accounts"):
        assert client.get(url, headers=h).status_code == 404
        assert client.get(url).status_code == 401
    staff, me = signup(client, "699 00 00 00", "Équipe Reserva")
    assert me["user"]["is_staff"] is True
    o = client.get("/api/admin/overview", headers=staff).json()
    assert (o["accounts"], o["users"], o["reports"]) == (2, 2, 1) and o["by_plan"] == {"gratuit": 2, "pro": 0, "equipe": 0}
    assert len(o["signups_30d"]) == 30 and o["signups_30d"][-1]["count"] == 2 and o["monthly_revenue_fcfa"] == 0
    assert o["ai"]["credit_given_fcfa"] == 1000
    rows = client.get("/api/admin/accounts", headers=staff, params={"q": "jean"}).json()
    assert len(rows) == 1 and rows[0]["login"] == "690112233" and rows[0]["reports"] == 1
    oid = rows[0]["id"]
    # Changer d'offre, offrir du crédit, suspendre.
    assert client.patch(f"/api/admin/accounts/{oid}", headers=staff, json={"plan": "inconnu"}).status_code == 422
    granted = client.patch(f"/api/admin/accounts/{oid}", headers=staff, json={"plan": "pro", "months": 3}).json()
    assert granted["plan_label"] == "Pro" and granted["plan_source"] == "admin" and granted["plan_until"]
    # Une offre accordée à la main n'est pas un revenu : elle ne gonfle pas le revenu récurrent.
    o = client.get("/api/admin/overview", headers=staff).json()
    assert o["monthly_revenue_fcfa"] == 0 and o["by_plan"]["pro"] == 1
    assert client.patch(f"/api/admin/accounts/{oid}", headers=staff, json={"plan": "gratuit"}).json()["plan"] == "gratuit"
    client.patch(f"/api/admin/accounts/{oid}", headers=staff, json={"plan": "pro", "months": 0})
    assert client.get("/api/subscription", headers=h).json()["until"] is None  # sans échéance
    assert client.post(f"/api/admin/accounts/{oid}/credit", headers=staff, json={"amount_fcfa": 1000, "note": "geste"}).json()["balance_fcfa"] == 1500
    assert client.post(f"/api/admin/accounts/{oid}/credit", headers=h, json={"amount_fcfa": 1000}).status_code == 404
    client.patch(f"/api/admin/accounts/{oid}", headers=staff, json={"suspended": True})
    blocked = client.get("/api/projects", headers=h)
    assert blocked.status_code == 403 and "suspendu" in blocked.json()["detail"]
    client.patch(f"/api/admin/accounts/{oid}", headers=staff, json={"suspended": False})
    assert client.get("/api/projects", headers=h).status_code == 200


# ---------- abonnements ----------

def set_until(session, **delta):
    """Avance ou recule l'échéance de l'espace, pour simuler le temps qui passe."""
    from datetime import timedelta

    from sqlmodel import Session, select

    from app.db import get_engine
    from app.models import Organization, Subscription, now

    with Session(get_engine()) as s:
        org = s.get(Organization, session["org"]["id"])
        org.plan_until = now() + timedelta(**delta)
        s.add(org)
        for sub in s.exec(select(Subscription).where(Subscription.org_id == org.id, Subscription.status == "active")).all():
            sub.ends_at = org.plan_until
            s.add(sub)
        s.commit()


PAY = {"phone": "690 11 22 33", "operator": "CM_MTN"}


def days_until(iso):
    from datetime import datetime

    from app.models import as_utc, now

    return (as_utc(datetime.fromisoformat(iso)) - now()).days


def test_subscribe_renew_and_expire(client):
    h, session = signup(client)
    sub = client.get("/api/subscription", headers=h).json()
    assert (sub["plan"], sub["paid"], sub["until"], sub["trial_available"], sub["payments_enabled"]) == ("gratuit", False, None, True, True)
    q = client.post("/api/subscription/quote", headers=h, json={"plan": "pro", "period": "mois"}).json()
    assert (q["amount_fcfa"], q["renewal"]) == (5000, False)
    assert client.post("/api/subscription/quote", headers=h, json={"plan": "pro", "period": "an"}).json()["amount_fcfa"] == 50000
    assert client.post("/api/subscription/quote", headers=h, json={"plan": "gratuit"}).status_code == 422
    assert client.post("/api/subscription/checkout", headers=h, json={"plan": "pro"}).status_code == 422  # numéro manquant
    pay = client.post("/api/subscription/checkout", headers=h, json={"plan": "pro", "period": "mois", **PAY}).json()
    assert pay["status"] == "reussi" and pay["amount_fcfa"] == 5000
    sub = client.get("/api/subscription", headers=h).json()
    assert (sub["plan"], sub["source"], sub["period"], sub["expires_soon"]) == ("pro", "paiement", "mois", False)
    assert 27 <= sub["days_left"] <= 31
    # L'offre payée lève les limites du gratuit.
    for i in range(5):
        assert client.post("/api/projects", headers=h, json={"name": f"Chantier {i}"}).status_code == 201
    # Renouveler avant l'échéance prolonge à partir de l'échéance : aucun jour perdu.
    q = client.post("/api/subscription/quote", headers=h, json={"plan": "pro", "period": "an"}).json()
    assert q["renewal"] is True
    client.post("/api/subscription/checkout", headers=h, json={"plan": "pro", "period": "an", **PAY})
    sub = client.get("/api/subscription", headers=h).json()
    assert 390 <= sub["days_left"] <= 398 and len(sub["history"]) == 2 and len(sub["payments"]) == 2
    assert client.get("/api/account/usage", headers=h).json()["subscription"]["plan"] == "pro"
    # Bientôt échu : signalé. Échu : retour en Gratuit tout seul, sans rien supprimer.
    set_until(session, days=3)
    assert client.get("/api/subscription", headers=h).json()["expires_soon"] is True
    set_until(session, seconds=-5)
    sub = client.get("/api/subscription", headers=h).json()
    assert (sub["plan"], sub["until"], sub["paid"]) == ("gratuit", None, False)
    assert {x["status"] for x in sub["history"]} == {"expiree"}
    assert len(client.get("/api/projects", headers=h).json()) == 5  # les rapports restent
    assert client.post("/api/projects", headers=h, json={"name": "Un de plus"}).status_code == 402  # mais plus d'ajout


def test_trial_promo_and_upgrade(client):
    h, session = signup(client)
    staff, _ = signup(client, "699 00 00 00", "Équipe Reserva")
    # Essai : une fois, sans paiement, 14 jours.
    assert client.post("/api/subscription/trial", headers=h, json={"plan": "gratuit"}).status_code == 422
    trial = client.post("/api/subscription/trial", headers=h, json={"plan": "pro"}).json()
    assert (trial["plan"], trial["source"], trial["trial_available"]) == ("pro", "essai", False) and 12 <= trial["days_left"] <= 14
    assert client.post("/api/subscription/trial", headers=h, json={"plan": "equipe"}).status_code == 409
    # Code promo : créé par l'administration, vérifié au devis, compté seulement au paiement réussi.
    assert client.post("/api/admin/promos", headers=h, json={"code": "X", "percent_off": 20}).status_code == 404
    promo = client.post("/api/admin/promos", headers=staff, json={"code": "lancement", "percent_off": 20, "max_uses": 1}).json()
    assert promo["code"] == "LANCEMENT" and promo["usable"]
    assert client.post("/api/subscription/quote", headers=h, json={"plan": "pro", "promo_code": "inconnu"}).status_code == 422
    q = client.post("/api/subscription/quote", headers=h, json={"plan": "pro", "promo_code": " lancement "}).json()
    assert (q["base_fcfa"], q["discount_fcfa"], q["amount_fcfa"]) == (5000, 1000, 4000)
    assert client.get("/api/admin/promos", headers=staff).json()[0]["used"] == 0
    pay = client.post("/api/subscription/checkout", headers=h, json={"plan": "pro", "promo_code": "LANCEMENT", **PAY}).json()
    assert pay["amount_fcfa"] == 4000 and pay["status"] == "reussi"
    assert client.get("/api/admin/promos", headers=staff).json()[0]["used"] == 1
    assert client.post("/api/subscription/quote", headers=h, json={"plan": "pro", "promo_code": "LANCEMENT"}).status_code == 422
    # Payer pendant l'essai : la période payée commence à la fin de l'essai.
    assert 40 <= client.get("/api/subscription", headers=h).json()["days_left"] <= 45
    # Passer à l'offre supérieure : ce qui est déjà payé et pas encore consommé est déduit.
    # Ici le mois payé 4 000 n'a pas commencé (l'essai court encore) : il est déduit en entier.
    q = client.post("/api/subscription/quote", headers=h, json={"plan": "equipe"}).json()
    assert (q["prorata_fcfa"], q["amount_fcfa"], q["renewal"]) == (4000, 11000, False)
    client.post("/api/subscription/checkout", headers=h, json={"plan": "equipe", **PAY})
    sub = client.get("/api/subscription", headers=h).json()
    assert sub["plan"] == "equipe" and 27 <= sub["days_left"] <= 31
    assert [x["status"] for x in sub["history"]].count("active") == 1
    # Administration : encaissements réels et revenu récurrent.
    o = client.get("/api/admin/overview", headers=staff).json()
    assert o["collected_total_fcfa"] == 4000 + q["amount_fcfa"] and o["monthly_revenue_fcfa"] == 15000 and o["paying_accounts"] == 1
    rows = client.get("/api/admin/payments", headers=staff).json()
    assert len(rows) == 2 and rows[0]["account"] == "Jean Technicien" and rows[1]["promo_code"] == "LANCEMENT"
    client.delete("/api/admin/promos/LANCEMENT", headers=staff)
    assert client.get("/api/admin/promos", headers=staff).json()[0]["usable"] is False


def send_webhook(c, payload, secret="secret-webhook", age=0):
    from app import trustchange

    raw = json.dumps(payload).encode()
    ts = str(int(time.time()) - age)
    return c.post("/api/payments/webhook", content=raw, headers={
        "Content-Type": "application/json", "X-TrustChange-Timestamp": ts,
        "X-TrustChange-Signature": trustchange.sign_webhook(raw, ts, secret)})


def test_trustchange_payment_and_webhook(tc):
    h, session = signup(tc)
    ops = tc.get("/api/payments/operators", headers=h).json()
    assert [o["code"] for o in ops] == ["CM_MTN", "CM_ORANGE"] and ops[1]["name"] == "Orange Money"
    pay = tc.post("/api/subscription/checkout", headers=h, json={"plan": "pro", "period": "mois", **PAY}).json()
    assert pay["status"] == "en_attente"
    sent = next(body for method, path, body in tc.state["calls"] if path == "/collect")
    assert sent["phoneNumber"] == "690112233" and sent["amount"] == 5000 and sent["paymentCode"] == "CM_MTN"
    assert sent["externalReference"] == f"rsv-{pay['id']}"
    # Tant que le client n'a pas validé sur son téléphone, rien n'est activé.
    assert tc.get(f"/api/payments/{pay['id']}", headers=h).json()["status"] == "en_attente"
    assert tc.get("/api/subscription", headers=h).json()["plan"] == "gratuit"
    # Webhook : refusé sans bonne signature ou s'il est trop vieux.
    ok = {"data": {"transactionId": "TC-1", "externalReference": sent["externalReference"], "status": "SUCCESS", "amount": 5000}}
    assert send_webhook(tc, ok, secret="mauvais").status_code == 401
    assert send_webhook(tc, ok, age=900).status_code == 401
    assert tc.post("/api/payments/webhook", json=ok).status_code == 401
    assert tc.get("/api/subscription", headers=h).json()["plan"] == "gratuit"
    # Webhook authentique : l'abonnement démarre. Le rejouer ne crée pas une deuxième période.
    assert send_webhook(tc, ok).json()["status"] == "reussi"
    assert send_webhook(tc, ok).json()["status"] == "reussi"
    sub = tc.get("/api/subscription", headers=h).json()
    assert sub["plan"] == "pro" and len(sub["history"]) == 1 and 27 <= sub["days_left"] <= 31
    assert send_webhook(tc, {"externalReference": "inconnue", "status": "SUCCESS"}).json()["ignored"]
    # Un autre espace ne voit pas ce paiement.
    other, _ = signup(tc, "autre@cabinet.cm", "Autre")
    assert tc.get(f"/api/payments/{pay['id']}", headers=other).status_code == 404


def test_trustchange_uncertain_and_failed_payments(tc):
    h, session = signup(tc)
    staff, _ = signup(tc, "699 00 00 00", "Équipe Reserva")
    # Réseau coupé pendant l'envoi : on ne sait pas si c'est parti. On interroge, on ne rejoue pas.
    tc.state["collect"] = "network"
    pay = tc.post("/api/subscription/checkout", headers=h, json={"plan": "pro", **PAY}).json()
    assert pay["status"] == "en_attente"
    tc.state["status"] = "SUCCESS"
    assert tc.get(f"/api/payments/{pay['id']}", headers=h).json()["status"] == "reussi"
    assert tc.get("/api/subscription", headers=h).json()["plan"] == "pro"
    # Refus net de l'agrégateur : paiement échoué, message transmis, offre inchangée.
    tc.state.update(collect="refused", status="PROCESSING")
    refused = tc.post("/api/billing/topup", headers=h, json={"amount_fcfa": 2000, **PAY})
    assert refused.status_code == 400 and "Numéro invalide" in refused.json()["detail"]
    # Recharge de crédit IA : créditée à la confirmation, une seule fois.
    assert tc.post("/api/billing/topup", headers=h, json={"amount_fcfa": 100, **PAY}).status_code == 422
    tc.state["collect"] = "ok"
    top = tc.post("/api/billing/topup", headers=h, json={"amount_fcfa": 2000, **PAY}).json()
    assert top["status"] == "en_attente" and tc.get("/api/me", headers=h).json()["org"]["balance_fcfa"] == 500
    tc.state["status"] = "FAILED"
    assert tc.get(f"/api/payments/{top['id']}", headers=h).json()["status"] == "echoue"
    assert tc.get("/api/me", headers=h).json()["org"]["balance_fcfa"] == 500
    tc.state["status"] = "PROCESSING"
    top = tc.post("/api/billing/topup", headers=h, json={"amount_fcfa": 2000, **PAY}).json()
    ok = {"externalReference": f"rsv-{top['id']}", "status": "COMPLETED"}
    send_webhook(tc, ok)
    send_webhook(tc, ok)
    assert tc.get("/api/me", headers=h).json()["org"]["balance_fcfa"] == 2500
    # Paiement resté en attente : l'administration peut le trancher après vérification.
    stuck = tc.post("/api/billing/topup", headers=h, json={"amount_fcfa": 1000, **PAY}).json()
    assert client_pending(tc, staff) == 1
    assert tc.post(f"/api/admin/payments/{stuck['id']}/settle", headers=h, json={"success": True}).status_code == 404
    assert tc.post(f"/api/admin/payments/{stuck['id']}/settle", headers=staff, json={"success": True}).json()["status"] == "reussi"
    assert tc.post(f"/api/admin/payments/{stuck['id']}/settle", headers=staff, json={"success": True}).status_code == 409
    assert tc.get("/api/me", headers=h).json()["org"]["balance_fcfa"] == 3500
    # Un membre qui n'est pas responsable de l'espace ne peut pas engager de paiement.
    set_plan(session, "equipe")
    tech = member(tc, h, "technicien", "tech@cabinet.cm")
    assert tc.post("/api/subscription/checkout", headers=tech, json={"plan": "pro", **PAY}).status_code == 403


def client_pending(c, staff):
    return c.get("/api/admin/overview", headers=staff).json()["pending_payments"]


def test_payment_unavailable_without_key(tmp_path, monkeypatch):
    for c in _make_client(tmp_path, monkeypatch, RESERVA_PAYMENT_SIMULATION="false"):
        h, _ = signup(c)
        assert c.get("/api/subscription", headers=h).json()["payments_enabled"] is False
        assert c.get("/api/payments/operators", headers=h).json() == []
        r = c.post("/api/subscription/checkout", headers=h, json={"plan": "pro", **PAY})
        assert r.status_code == 503 and c.get("/api/subscription", headers=h).json()["plan"] == "gratuit"


# ---------- finalisation : mot de passe oublié, limites de tentatives, fonctions par offre, exploitation ----------

def test_forgot_and_reset_password(client, monkeypatch):
    from app import notify

    sent = {}
    monkeypatch.setattr(notify, "send_code", lambda login, code: sent.update({login: code}) or True)
    h, session = signup(client)
    # Même réponse que le compte existe ou non : on ne révèle pas qui est inscrit.
    unknown = client.post("/api/auth/forgot", json={"login": "655 00 00 00"}).json()
    known = client.post("/api/auth/forgot", json={"login": "690 11 22 33"}).json()
    assert unknown == known == {"ok": True, "delivery": "aucun", "minutes": 15}
    assert list(sent) == ["690112233"] and len(sent["690112233"]) == 6
    assert client.post("/api/auth/forgot", json={"login": "abc"}).status_code == 422
    # Mauvais code : refusé ; au bout de 5 essais le code est grillé, même le bon ne passe plus.
    code = sent["690112233"]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert client.post("/api/auth/reset", json={"login": "690112233", "code": wrong, "password": "nouveau1"}).status_code == 400
    assert client.post("/api/auth/reset", json={"login": "690112233", "code": code, "password": "nouveau1"}).status_code == 400
    assert client.post("/api/auth/login", json={"login": "690112233", "password": "secret1"}).status_code == 200
    # Nouveau code : le mot de passe change, l'utilisateur est connecté, le code ne resservira pas.
    client.post("/api/auth/forgot", json={"login": "690112233"})
    code = sent["690112233"]
    assert client.post("/api/auth/reset", json={"login": "690112233", "code": code, "password": "court"}).status_code == 422
    ok = client.post("/api/auth/reset", json={"login": "690112233", "code": f" {code} ", "password": "nouveau1"})
    assert ok.status_code == 200 and ok.json()["user"]["login"] == "690112233" and ok.json()["token"]
    assert client.post("/api/auth/reset", json={"login": "690112233", "code": code, "password": "encore12"}).status_code == 400
    assert client.post("/api/auth/login", json={"login": "690112233", "password": "secret1"}).status_code == 401
    assert client.post("/api/auth/login", json={"login": "690112233", "password": "nouveau1"}).status_code == 200
    # Pas plus de 3 demandes de code par quart d'heure pour un même compte.
    client.post("/api/auth/forgot", json={"login": "690112233"})
    assert client.post("/api/auth/forgot", json={"login": "690112233"}).status_code == 429
    # Un code expiré est refusé.
    from sqlmodel import Session, select

    from app.db import get_engine
    from app.models import ResetCode, now

    with Session(get_engine()) as db:
        row = db.exec(select(ResetCode).where(ResetCode.used == False)).one()  # noqa: E712
        row.expires_at = now()
        db.add(row)
        db.commit()
    assert client.post("/api/auth/reset", json={"login": "690112233", "code": sent["690112233"], "password": "encore12"}).status_code == 400
    # Sans SMS ni e-mail : l'administration génère un code à dicter au téléphone.
    staff, _ = signup(client, "699 00 00 00", "Équipe Reserva")
    assert client.post(f"/api/admin/accounts/{session['org']['id']}/reset-code", headers=h).status_code == 404
    given = client.post(f"/api/admin/accounts/{session['org']['id']}/reset-code", headers=staff).json()
    assert given["login"] == "690112233"
    assert client.post("/api/auth/reset", json={"login": "690112233", "code": given["code"], "password": "dicte123"}).status_code == 200


def test_delivery_channel_follows_configuration(tmp_path, monkeypatch):
    for c in _make_client(tmp_path, monkeypatch, RESERVA_SMS_GATEWAY_URL="https://sms.exemple/send", RESERVA_SMTP_HOST="smtp.exemple"):
        from app import notify
        from app.config import get_settings

        assert notify.delivery_for("690112233") == "sms" and notify.delivery_for("a@b.cm") == "email"
        assert notify.international("690112233", get_settings()) == "237690112233"
        assert notify.international("237690112233", get_settings()) == "237690112233"
        assert c.post("/api/auth/forgot", json={"login": "personne@exemple.cm"}).json()["delivery"] == "email"


def test_login_attempts_are_limited(client):
    from app import ratelimit

    signup(client)
    for _ in range(8):
        assert client.post("/api/auth/login", json={"login": "690112233", "password": "faux"}).status_code == 401
    # Compte verrouillé un quart d'heure : même le bon mot de passe est refusé, pour ne rien apprendre à l'attaquant.
    blocked = client.post("/api/auth/login", json={"login": "690112233", "password": "secret1"})
    assert blocked.status_code == 429 and "Mot de passe oublié" in blocked.json()["detail"]
    # Un autre compte n'est pas touché.
    signup(client, "autre@cabinet.cm", "Autre")
    assert client.post("/api/auth/login", json={"login": "autre@cabinet.cm", "password": "secret1"}).status_code == 200
    ratelimit.reset()
    assert client.post("/api/auth/login", json={"login": "690112233", "password": "secret1"}).status_code == 200
    # Un mot de passe juste remet le compteur à zéro.
    for _ in range(5):
        client.post("/api/auth/login", json={"login": "690112233", "password": "faux"})
    client.post("/api/auth/login", json={"login": "690112233", "password": "secret1"})
    for _ in range(5):
        assert client.post("/api/auth/login", json={"login": "690112233", "password": "faux"}).status_code == 401


def test_paid_features_and_artisans(client, monkeypatch):
    import app.api as api

    seen = []
    real = api.render_report
    monkeypatch.setattr(api, "render_report", lambda org, *a, **k: seen.append(org) or real(org, *a, **k))
    h, session = signup(client)
    p, co = setup_project(client, h)
    client.put(f"/api/reserves/{uuid4()}", headers=h, json=reserve_body(p["id"], company_id=co["id"]))
    # Offre gratuite : PDF sans en-tête au nom du client, et pas d'envoi aux artisans.
    assert client.get(f"/api/projects/{p['id']}/report.pdf", headers=h).content[:4] == b"%PDF" and seen[-1] is None
    blocked = client.post(f"/api/projects/{p['id']}/dispatch", headers=h, json={"send": False})
    assert blocked.status_code == 402 and "Pro" in blocked.json()["detail"]
    plans = {x["key"]: x for x in client.get("/api/plans").json()}
    assert (plans["gratuit"]["branding"], plans["pro"]["branding"], plans["pro"]["dispatch"]) == (False, True, True)
    # Offre Pro : en-tête du client sur le PDF, et message prêt pour chaque artisan.
    set_plan(session, "pro")
    client.get(f"/api/projects/{p['id']}/report.pdf", headers=h)
    assert seen[-1] is not None and seen[-1].name == "Jean Technicien"
    out = client.post(f"/api/projects/{p['id']}/dispatch", headers=h, json={"send": False}).json()
    assert len(out) == 1 and out[0]["sent"] is False and out[0]["whatsapp_link"].startswith("https://wa.me/237690000000")
    # Retirer un artisan : ses défauts restent, rattachés à leur corps de métier.
    other, _ = signup(client, "autre@cabinet.cm", "Autre")
    assert client.delete(f"/api/companies/{co['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/companies/{co['id']}", headers=h).json() == {"deleted": True}
    assert client.delete(f"/api/companies/{co['id']}", headers=h).status_code == 200
    assert client.get(f"/api/projects/{p['id']}", headers=h).json()["companies"] == []
    rows = client.get(f"/api/projects/{p['id']}/reserves", headers=h).json()
    assert len(rows) == 1 and rows[0]["company_id"] is None
    assert client.post(f"/api/projects/{p['id']}/dispatch", headers=h, json={"send": False}).json() == []


def test_production_refuses_dangerous_settings(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError) as err:
        for _ in _make_client(tmp_path, monkeypatch, RESERVA_ENV="production"):
            pass
    assert "RESERVA_SECRET_KEY" not in str(err.value)  # celle des tests est assez longue
    assert "RESERVA_PAYMENT_SIMULATION" in str(err.value) and "https://" in str(err.value)
    for c in _make_client(tmp_path, monkeypatch, RESERVA_ENV="production", RESERVA_PAYMENT_SIMULATION="false",
                          RESERVA_PUBLIC_BASE_URL="https://reserva.exemple"):
        assert c.get("/health").json() == {"ok": True}


def test_migrations_match_models_and_backup_restores(client):
    """La base est créée par les migrations ; elles doivent décrire exactement les modèles."""
    import sqlite3
    import tarfile

    from alembic import command
    from alembic.config import Config

    from app.backup import make_backup
    from app.config import get_settings
    from app.db import MIGRATIONS_DIR

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.check(config)  # lève si un modèle a changé sans migration

    h, _ = signup(client)
    p, _ = setup_project(client, h)
    rid = str(uuid4())
    client.put(f"/api/reserves/{rid}", headers=h, json=reserve_body(p["id"]))
    client.put(f"/api/media/{uuid4()}", headers=h, data={"reserve_id": rid, "kind": "photo_avant"},
               files={"file": ("p.jpg", photo(), "image/jpeg")})
    # Sauvegarde : une archive avec la base (lisible) et les photos ; les plus anciennes sont supprimées.
    dest = get_settings().data_dir / "sauvegardes"
    archive = make_backup(dest, keep=2)
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        assert "reserva.db" in names and sum(n.startswith("media/") and n.endswith(".jpg") for n in names) == 1
        tar.extract("reserva.db", dest / "restauree", filter="data")
    restored = sqlite3.connect(dest / "restauree" / "reserva.db")
    assert restored.execute("SELECT name FROM project").fetchall() == [("Immeuble R+4 Bastos",)]
    assert restored.execute("SELECT COUNT(*) FROM reserve").fetchone() == (1,)
    restored.close()
    for stamp in ("20200101-000000", "20200102-000000", "20200103-000000"):
        (dest / f"reserva-{stamp}.tar.gz").write_bytes(b"x")
    newest = make_backup(dest, keep=2)
    left = sorted(f.name for f in dest.glob("reserva-*.tar.gz"))
    assert len(left) == 2 and newest.name in left and "reserva-20200101-000000.tar.gz" not in left
