"""Moteur SQLModel + session FastAPI."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = get_settings().db_url
        sqlite = url.startswith("sqlite")
        _engine = create_engine(url, connect_args={"check_same_thread": False} if sqlite else {})
        if sqlite:
            @event.listens_for(_engine, "connect")
            def _pragmas(conn, _):  # WAL : lectures pendant les écritures de synchro
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
    return _engine


def reset_engine() -> None:
    """Pour les tests : force la recréation du moteur après changement de config."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def init_db() -> None:
    """Met la base au niveau du code en appliquant les migrations en attente (Alembic).

    Appelé à chaque démarrage : une nouvelle version de l'application met la base à jour seule,
    sans perdre de données. Pour créer une migration après un changement de modèle :
    `alembic revision --autogenerate -m "..."` depuis backend/.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    tables = set(inspect(get_engine()).get_table_names())
    if tables and "alembic_version" not in tables:
        raise RuntimeError(
            "Cette base a été créée avant la mise en place des migrations. Base de test : supprimez le fichier "
            "(data/reserva.db) et relancez. Base à conserver : `alembic stamp head` si son schéma est à jour.")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.upgrade(config, "head")


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
