# backend/main.py
import os
import uuid
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlmodel import SQLModel, select, Session
from passlib.context import CryptContext
from dotenv import load_dotenv
import jwt
import aiofiles

# --- env + paths ---
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in .env")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change")

BASE_DIR = os.path.dirname(__file__)
VOICE_DIR = os.path.join(BASE_DIR, "static", "mom_voices")
os.makedirs(VOICE_DIR, exist_ok=True)

# --- crypto / hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt limit helper: truncate to 72 bytes (bcrypt limitation).
def safe_password_bytes(pw: str) -> bytes:
    if pw is None:
        return b""
    b = pw.encode("utf-8")
    if len(b) > 72:
        # truncate bytes (advisable to inform user in real app)
        return b[:72]
    return b

def hash_password(password: str) -> str:
    # Pass bytes-safe password to passlib; passlib will accept str but we ensure truncation
    pw = safe_password_bytes(password).decode("utf-8", errors="ignore")
    return pwd_context.hash(pw)

def verify_password(plain: str, hashed: str) -> bool:
    pw = safe_password_bytes(plain).decode("utf-8", errors="ignore")
    return pwd_context.verify(pw, hashed)

# --- JWT helpers ---
def create_access_token(data: dict, expires_minutes: int = 1440):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm="HS256")

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- DB session / models (expected to exist in backend/db) ---
# from db.session import engine, get_session  # you already have this file per earlier messages
# from db.models import User, UserProfile, MomProfile, MomVoice
#
# To avoid circular import problems during copy-paste, import here:
try:
    from db.session import engine, get_session
    from db.models import User, UserProfile, MomProfile, MomVoice
except Exception as e:
    raise RuntimeError("Make sure backend/db/session.py and backend/db/models.py exist and export engine, get_session and models. Error: " + str(e))

# Optional: create missing tables from SQLModel metadata (dev convenience)
def create_db():
    SQLModel.metadata.create_all(engine)

# --- FastAPI app ---
app = FastAPI(title="SerenAI — My Mom's Bot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

@app.on_event("startup")
def on_startup():
    # ensure tables exist in dev
    create_db()

# --- Auth dependency ---
bearer_scheme = HTTPBearer(auto_error=False)

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
                     session: Session = Depends(get_session)) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = credentials.credentials
    payload = decode_access_token(token)
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = session.exec(select(User).where(User.id == user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# --- Pydantic Schemas ---
class SignupIn(BaseModel):
    email: str
    password: str
    name: Optional[str] = None

class LoginIn(BaseModel):
    email: str
    password: str

class ProfileIn(BaseModel):
    full_name: Optional[str] = None
    dob: Optional[str] = None
    preferences: Optional[dict] = None

class PersonalityIn(BaseModel):
    personality: dict

# --- Routes ---
@app.get("/")
def home():
    return {"message": "SerenAI backend running"}

# Auth
@app.post("/signup")
def signup(payload: SignupIn, session: Session = Depends(get_session)):
    existing = session.exec(select(User).where(User.email == payload.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        name=payload.name
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    token = create_access_token({"user_id": user.id, "email": user.email})
    return {"message": "Signup successful", "user_id": user.id, "token": token}

@app.post("/login")
def login(payload: LoginIn, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == payload.email)).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"user_id": user.id, "email": user.email})
    # update last_login_at (optional)
    user.last_login_at = datetime.utcnow()
    session.add(user)
    session.commit()
    return {"message": "Login successful", "user_id": user.id, "token": token}

# Profile (authenticated)
@app.post("/api/profile")
def save_profile(payload: ProfileIn, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    existing = session.exec(select(UserProfile).where(UserProfile.user_id == current_user.id)).first()
    pref_json = json.dumps(payload.preferences or {})
    if existing:
        existing.full_name = payload.full_name or existing.full_name
        existing.dob = payload.dob or existing.dob
        existing.preferences = pref_json if hasattr(existing, "preferences") else pref_json
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return {"status": "updated", "profile_id": existing.id}
    profile = UserProfile(user_id=current_user.id, full_name=payload.full_name, dob=payload.dob, preferences=pref_json)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return {"status": "created", "profile_id": profile.id}

@app.get("/api/profile")
def get_profile(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    profile = session.exec(select(UserProfile).where(UserProfile.user_id == current_user.id)).first()
    if not profile:
        return {"user_id": current_user.id, "full_name": None, "dob": None, "preferences": {}, "created_at": None}
    # preferences might be stored as JSONB or string - handle both
    prefs = {}
    try:
        prefs = json.loads(profile.preferences) if isinstance(profile.preferences, str) else (profile.preferences or {})
    except Exception:
        prefs = profile.preferences or {}
    return {
        "user_id": profile.user_id,
        "full_name": profile.full_name,
        "dob": profile.dob.isoformat() if getattr(profile, "dob", None) else profile.dob,
        "preferences": prefs,
        "created_at": profile.created_at.isoformat() if profile.created_at else None
    }

# Mom personality endpoints (authenticated)
@app.post("/api/mom/personality")
def save_mom_personality(payload: PersonalityIn, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    existing = session.exec(select(MomProfile).where(MomProfile.user_id == current_user.id)).first()
    pj = payload.personality or {}
    if existing:
        existing.personality = pj
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return {"status": "updated", "mom_profile_id": existing.id}
    mom = MomProfile(user_id=current_user.id, personality=pj, voice_count=0, consent_given=False)
    session.add(mom)
    session.commit()
    session.refresh(mom)
    return {"status": "created", "mom_profile_id": mom.id}

@app.get("/api/mom/profile")
def get_mom_profile(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    mom = session.exec(select(MomProfile).where(MomProfile.user_id == current_user.id)).first()
    if not mom:
        return {"user_id": current_user.id, "personality": {}, "voice_files": [], "consent_given": False, "created_at": None}
    # load voice rows
    voices = session.exec(select(MomVoice).where(MomVoice.mom_profile_id == mom.id, MomVoice.is_active == True)).all()
    vlist = []
    for v in voices:
        vlist.append({
            "id": v.id,
            "filename": v.filename,
            "stored_name": v.stored_name,
            "path": v.path,
            "mime_type": v.mime_type,
            "size_bytes": v.size_bytes,
            "duration_secs": float(v.duration_secs) if v.duration_secs is not None else None,
            "status": v.status,
            "uploaded_at": v.uploaded_at.isoformat() if v.uploaded_at else None
        })
    return {
        "user_id": mom.user_id,
        "personality": mom.personality or {},
        "voice_files": vlist,
        "consent_given": bool(mom.consent_given),
        "voice_count": int(mom.voice_count or len(vlist)),
        "created_at": mom.created_at.isoformat() if mom.created_at else None
    }

# Upload voice (authenticated) - multipart/form-data
@app.post("/api/mom/upload_voice")
async def upload_mom_voice(
    consent: bool = Form(...),
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    if not consent:
        raise HTTPException(status_code=400, detail="Consent is required to upload voice samples")
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="No audio files provided")

    # ensure mom profile exists
    mom = session.exec(select(MomProfile).where(MomProfile.user_id == current_user.id)).first()
    if not mom:
        mom = MomProfile(user_id=current_user.id, personality={}, voice_count=0, consent_given=True)
        session.add(mom)
        session.commit()
        session.refresh(mom)

    saved_files = []
    for f in files:
        if not (f.content_type and f.content_type.startswith("audio/")):
            raise HTTPException(status_code=400, detail=f"Invalid file type for {f.filename}")

        contents = await f.read()
        max_bytes = 10 * 1024 * 1024
        if len(contents) > max_bytes:
            raise HTTPException(status_code=400, detail=f"File too large: {f.filename}")

        ext = os.path.splitext(f.filename)[1] or ".wav"
        safe_name = f"{uuid.uuid4().hex}{ext}"
        out_path = os.path.join(VOICE_DIR, safe_name)

        # write to disk
        async with aiofiles.open(out_path, "wb") as out_f:
            await out_f.write(contents)

        # metadata
        size_bytes = len(contents)
        checksum = hashlib.sha256(contents).hexdigest()
        rel_path = f"/static/mom_voices/{safe_name}"  # path used by app

        # insert MomVoice row
        mv = MomVoice(
            mom_profile_id=mom.id,
            user_id=current_user.id,
            filename=f.filename,
            stored_name=safe_name,
            path=rel_path,
            mime_type=f.content_type,
            size_bytes=size_bytes,
            duration_secs=None,
            checksum=checksum,
            status="validated",
            is_active=True
        )
        session.add(mv)
        saved_files.append(safe_name)

    # commit voices
    session.commit()

    # update voice_count on mom profile
    cnt = session.exec(select(MomVoice).where(MomVoice.mom_profile_id == mom.id, MomVoice.is_active == True)).count()
    mom.voice_count = cnt
    mom.consent_given = True
    mom.updated_at = datetime.utcnow() if hasattr(mom, "updated_at") else mom.created_at
    session.add(mom)
    session.commit()
    session.refresh(mom)

    return {"status": "ok", "saved_files": saved_files, "mom_profile_id": mom.id}

# list voices by any user_id (admin-like)
@app.get("/api/list_voices/{user_id}")
def list_voices(user_id: int, session: Session = Depends(get_session)):
    mom = session.exec(select(MomProfile).where(MomProfile.user_id == user_id)).first()
    if not mom:
        return {"voice_files": []}
    voices = session.exec(select(MomVoice).where(MomVoice.mom_profile_id == mom.id, MomVoice.is_active == True)).all()
    vlist = []
    for v in voices:
        vlist.append({
            "id": v.id,
            "filename": v.filename,
            "stored_name": v.stored_name,
            "path": v.path,
            "mime_type": v.mime_type,
            "size_bytes": v.size_bytes,
            "status": v.status,
            "uploaded_at": v.uploaded_at.isoformat() if v.uploaded_at else None
        })
    return {"voice_files": vlist}
