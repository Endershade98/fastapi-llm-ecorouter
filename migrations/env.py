import os

import psycopg
from alembic import context
from sqlalchemy import create_engine, pool

database_url = os.environ["ECOROUTER_DATABASE_URL"]
engine = create_engine(
    "postgresql+psycopg://",
    creator=lambda: psycopg.connect(database_url),
    poolclass=pool.NullPool,
)

try:
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
