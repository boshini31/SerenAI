# backend/db/session.py
import os
from sqlmodel import create_engine, Session
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:3123@localhost:5432/mom_bot")

# SQLModel / SQLAlchemy engine
# echo=True during dev to see SQL in logs
engine = create_engine(DATABASE_URL, echo=True)

# simple session factory for FastAPI dependencies
def get_session():
    with Session(engine) as session:
        yield session
