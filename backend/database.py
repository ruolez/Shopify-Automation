from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import sqlite3

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# Ensure database file exists for SQLite
if "sqlite" in DATABASE_URL:
    db_path = DATABASE_URL.replace("sqlite:///", "")
    # Create the database file if it doesn't exist
    if not os.path.exists(db_path):
        # Create directory if needed
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        # Create empty database file
        conn = sqlite3.connect(db_path)
        conn.close()

# Create SQLite engine with check_same_thread=False for FastAPI
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    Base.metadata.create_all(bind=engine)