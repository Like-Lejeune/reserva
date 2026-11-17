"""Environnement Alembic : compare app/models.py à la base et applique les migrations.

La base utilisée est celle de l'application (RESERVA_DATABASE_URL ou data/reserva.db).
"""

from alembic import context
from sqlmodel import SQLModel

from app import models  # noqa: F401  (enregistre les tables)
from app.db import get_engine

target_metadata = SQLModel.metadata


def run_migrations() -> None:
    with get_engine().connect() as connection:
        # render_as_batch : SQLite ne sait pas modifier une colonne en place, Alembic recopie la table.
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


run_migrations()
