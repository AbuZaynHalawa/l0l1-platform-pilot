"""DB engine/session setup. Defaults to a local SQLite file for pilot testing;
set DATABASE_URL to a real Postgres URL (e.g. Render's) to switch, no code changes needed.
"""
import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "app.db"),
)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_column(table_name: str, column_name: str, ddl_type: str) -> None:
    """Adds a column to an already-existing table if it's missing.

    metadata.create_all() only creates tables that don't exist yet — it never
    alters an existing table's columns, so a plain model change like adding
    a new field is invisible to a live database until this runs. No-op for a
    brand-new database (the table won't exist yet; create_all builds the
    column from the model directly).
    """
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return
    existing = [c["name"] for c in inspector.get_columns(table_name)]
    if column_name in existing:
        return
    with engine.connect() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl_type}"))
        conn.commit()


def ensure_enum_value(table_name: str, column_name: str, value: str) -> None:
    """Adds a value to a Postgres native enum type backing a column, if missing.

    SQLite has no real enum type — our Enum columns are just text there, so a
    new Python enum member works immediately. Postgres enums are a fixed,
    named type at the database level; SQLAlchemy's create_all() only creates
    that type once and never alters it, so a new member is invisible to a
    live database (every write of that value 500s) until this runs. No-op on
    SQLite and on a brand-new database (the table won't exist yet; create_all
    builds the type with every current member already included).
    """
    if not DATABASE_URL.startswith("postgres"):
        return
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return
    with engine.connect() as conn:
        enum_type = conn.execute(text(
            "SELECT udt_name FROM information_schema.columns WHERE table_name = :t AND column_name = :c"
        ), {"t": table_name, "c": column_name}).scalar()
        if not enum_type:
            return
        exists = conn.execute(text(
            "SELECT 1 FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = :enum_type AND e.enumlabel = :value"
        ), {"enum_type": enum_type, "value": value}).first()
        if exists:
            return
        conn.execute(text(f'ALTER TYPE "{enum_type}" ADD VALUE \'{value}\''))
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
