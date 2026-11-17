"""Sauvegarde de la base et des photos.

    python -m app.backup                      # archive dans data/backups, garde les 14 dernières
    python -m app.backup --dest /mnt/disque --keep 30

À lancer chaque nuit (cron ou timer systemd), puis à copier HORS du serveur (rclone, rsync) :
une sauvegarde qui reste sur la machine qu'elle protège ne sert à rien le jour où le disque lâche.

La base est copiée par l'API de sauvegarde de SQLite : la copie est cohérente même si
l'application écrit pendant ce temps. Ne fonctionne qu'avec SQLite.
"""

import argparse
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from app.config import get_settings


def make_backup(dest: Path | None = None, keep: int = 14) -> Path:
    s = get_settings()
    if not s.db_url.startswith("sqlite:///"):
        raise SystemExit("Sauvegarde prévue pour SQLite uniquement. Pour une autre base, utiliser son outil (pg_dump, mysqldump).")
    db_path = Path(s.db_url.removeprefix("sqlite:///"))
    if not db_path.exists():
        raise SystemExit(f"Base introuvable : {db_path}")
    dest = dest or s.data_dir / "backups"
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / f"reserva-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "reserva.db"
        source, target = sqlite3.connect(db_path), sqlite3.connect(copy)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        # Vérifie que la copie est lisible avant de la considérer comme une sauvegarde.
        check = sqlite3.connect(copy)
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SystemExit("La copie de la base est corrompue : sauvegarde abandonnée.")
        finally:
            check.close()
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(copy, arcname="reserva.db")
            if s.media_dir.exists():
                tar.add(s.media_dir, arcname="media")

    old = sorted(dest.glob("reserva-*.tar.gz"))[:-keep] if keep > 0 else []
    for path in old:
        path.unlink()
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description="Sauvegarde la base et les photos de Reserva.")
    parser.add_argument("--dest", type=Path, default=None, help="dossier des archives (défaut : data/backups)")
    parser.add_argument("--keep", type=int, default=14, help="nombre d'archives à garder (défaut : 14)")
    args = parser.parse_args()
    archive = make_backup(args.dest, args.keep)
    print(f"Sauvegarde écrite : {archive} ({archive.stat().st_size / 1024 / 1024:.1f} Mo)", file=sys.stderr)
    print(archive)


if __name__ == "__main__":
    main()
