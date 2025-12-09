import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine, select
from passlib.context import CryptContext
from dotenv import load_dotenv
import jwt

# Load .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------- DB SETUP ----------------
engine = create_engine(DATABASE_URL, echo=True)

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

def create_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

# ---------------- AUTH HELPERS ----------------
def create_access_token(data: dict, expires_minutes: int = 1440):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm="HS256")

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str):
    return pwd_context.verify(plain, hashed)

# ---------------- FASTAPI APP ----------------
app = FastAPI(title="My Mom's Bot API - Day 1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- SCHEMAS ----------------
class SignupIn(BaseModel):
    email: str
    password: str
    name: Optional[str] = None

class LoginIn(BaseModel):
    email: str
    password: str

# ---------------- ROUTES ----------------
@app.on_event("startup")
def on_startup():
    create_db()

@app.get("/")
def home():
    return {"message": "Backend running (Day 1)"}

@app.post("/signup")
def signup(payload: SignupIn, session: Session = Depends(get_session)):
    existing = session.exec(select(User).where(User.email == payload.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        name=payload.name
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    token = create_access_token({"user_id": user.id, "email": user.email})

    return {"status": "success", "token": token, "user_id": user.id}

@app.post("/login")
def login(payload: LoginIn, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == payload.email)).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"user_id": user.id, "email": user.email})

    return {"status": "success", "token": token, "user_id": user.id}
