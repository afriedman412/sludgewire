#!/usr/bin/env python
"""Drop all tables and recreate them. Run this once to reset the database."""
from app.settings import load_settings
from app.db import make_engine
from sqlmodel import SQLModel

# Import all models to register them
from app.schemas import (
    Committee, IngestionTask, FilingF3X, IEScheduleE,
    EmailRecipient, BackfillJob, AppConfig
)

if __name__ == "__main__":
    settings = load_settings()
    engine = make_engine(settings)

    print(f"Connecting to: {settings.postgres_url}")
    print("WARNING: This will DROP ALL TABLES and recreate them!")

    confirm = input("Type 'yes' to continue: ")
    if confirm.lower() != 'yes':
        print("Aborted.")
        exit(1)

    print("Dropping all tables...")
    SQLModel.metadata.drop_all(engine)

    print("Creating tables...")
    SQLModel.metadata.create_all(engine)

    print("Done! Tables recreated:")
    for table in SQLModel.metadata.tables:
        print(f"  - {table}")
