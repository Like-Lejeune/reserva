"""Rapport PDF des réserves (WeasyPrint), regroupé par lot, avec photos avant/après."""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app.config import get_settings
from app.models import Company, Media, Organization, Project, Reserve
from app.vocab import LOTS, SEVERITIES, STATUSES

_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                   autoescape=select_autoescape(["html"]))


def render_report(org: Organization | None, project: Project, reserves: list[Reserve], media: list[Media],
                  companies: list[Company], title: str = "Rapport de finition") -> bytes:
    media_dir = get_settings().media_dir.resolve()
    photos: dict[str, dict[str, list[str]]] = {}
    for m in media:
        if m.kind.startswith("photo") and (media_dir / m.filename).exists():
            photos.setdefault(m.reserve_id, {}).setdefault(m.kind, []).append((media_dir / m.filename).as_uri())
    logo = media_dir / org.logo_filename if org and org.logo_filename else None
    by_company = {c.id: c for c in companies}
    by_lot_company = {c.lot: c for c in companies}
    groups: dict[str, list[dict]] = {}
    for r in sorted(reserves, key=lambda r: r.number):
        company = by_company.get(r.company_id or "") or by_lot_company.get(r.lot)
        groups.setdefault(r.lot, []).append({
            "r": r, "company": company.name if company else "",
            "avant": photos.get(r.id, {}).get("photo_avant", [])[:2],
            "apres": photos.get(r.id, {}).get("photo_apres", [])[:2],
        })
    counts = {k: sum(1 for r in reserves if r.status == k) for k in STATUSES}
    html = _env.get_template("rapport.html").render(
        org=org, logo=logo.as_uri() if logo and logo.exists() else "", project=project, title=title, today=date.today().strftime("%d/%m/%Y"), total=len(reserves),
        groups=[(LOTS.get(lot, lot), items) for lot, items in groups.items()],
        counts=counts, STATUSES=STATUSES, SEVERITIES=SEVERITIES)
    return HTML(string=html, base_url=str(media_dir)).write_pdf()
