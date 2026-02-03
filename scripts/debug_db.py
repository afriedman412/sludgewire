#!/usr/bin/env python3
from sqlmodel import SQLModel, Session, text
from app.db import make_engine
from app.settings import load_settings
from app.schemas import Committee, SeenFiling, FilingF3X, IEScheduleE

settings = load_settings()
print(f"Connecting to: {settings.postgres_url}")

engine = make_engine(settings)

# Test raw connection and list tables
with engine.connect() as conn:
    result = conn.execute(text("SELECT current_database()"))
    print(f"Database: {result.scalar()}")

    result = conn.execute(text("""
        SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    """))
    tables = [r[0] for r in result]
    print(f"Existing tables: {tables}")

# Now try creating tables
print("\nCreating tables...")
SQLModel.metadata.create_all(engine)
print("create_all completed")

# Check again
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    """))
    tables = [r[0] for r in result]
    print(f"Tables after create_all: {tables}")
