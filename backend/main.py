# backend/main.py
import os
import uuid
import json
import hashlib
from datetime import datetime
from typing import Optional, List
from db.models import UserEvent
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import SQLModel, select, Session
from passlib.context import CryptContext
from dotenv import load_dotenv
import aiofiles

from db.session import engine, get_session
from db.models import User, UserProfile, MomProfile, MomVoice

# -------------------------------------------------
# ENV
# -------------------------------------------------
load_dotenv()

BASE_DIR = os.path.dirname(__file__)
VOICE_DIR = os.path.join(BASE_DIR, "static", "mom_voices")
os.makedirs(VOICE_DIR, exist_ok=True)

# -------------------------------------------------
# APP
# -------------------------------------------------
app = FastAPI(title="SerenAI — My Mom's Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(BASE_DIR, "static")),
    name="static"
)

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

# -------------------------------------------------
# DEV AUTH (FROZEN)
# -------------------------------------------------
def get_dev_user(session: Session = Depends(get_session)) -> User:
    """
    Single global dev user for Phase 1
    """
    user = session.exec(select(User).where(User.id == 1)).first()

    if not user:
        user = User(
            email="dev@seren.ai",
            hashed_password="dev",
            name="Seren Dev User"
        )
        session.add(user)
        session.commit()
        session.refresh(user)

    return user

def get_current_user(
    session: Session = Depends(get_session)
) -> User:
    """
    AUTH COMPLETELY BYPASSED
    """
    return get_dev_user(session)

# -------------------------------------------------
# PASSWORD UTILS (kept for later)
# -------------------------------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password[:72])

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain[:72], hashed)

# -------------------------------------------------
# SCHEMAS
# -------------------------------------------------
class SignupIn(BaseModel):
    email: str
    password: str
    name: Optional[str] = None

class ProfileIn(BaseModel):
    full_name: Optional[str] = None
    dob: Optional[str] = None
    preferences: Optional[dict] = None

class PersonalityIn(BaseModel):
    personality: dict

class ChatIn(BaseModel):
    message: str

class ChatOut(BaseModel):
    reply: str
    tone: str

INTENT_RESPONSES = {
    "mistake": {
        "gentle": {
            "reply": "Hmm… kanna, it’s okay. But take care of yourself, no?",
            "tone": "gentle-care"
        },
        "anger": {
            "reply": "Kanna… how many times now? I’m saying this because I care. Don’t hurt yourself like this.",
            "tone": "caring-anger"
        }
    },
    "sadness": {
        "reply": "Come here… you don’t have to feel alone. I’m with you.",
        "tone": "comforting"
    },
    "fatigue": {
        "reply": "You sound very tired. Please rest a little, kanna.",
        "tone": "nurturing"
    },
    "neutral": {
        "reply": "I’m listening. Tell me slowly.",
        "tone": "gentle"
    }
    INTENT_RESPONSES["improvement"] = {
    "reply": "That makes me really happy, kanna. I knew you could do it.",
    "tone": "proud"
      }

}

def detect_intent(message: str) -> str:
    msg = message.lower()

    if any(w in msg for w in ["skip", "missed", "forgot", "didn't"]):
        return "mistake"

    if any(w in msg for w in ["sad", "lonely", "alone", "cry"]):
        return "sadness"

    if any(w in msg for w in ["tired", "exhausted", "burnt"]):
        return "fatigue"

    if any(w in msg for w in ["ate", "had food", "took care", "did eat"]):
        return "improvement"
    
    return "neutral"

def intent_to_event(intent: str):
    if intent == "mistake":
        return {
            "event_type": "mistake",
            "event_key": "generic_mistake",
            "severity": "medium"
        }
    if intent == "sadness":
        return {
            "event_type": "emotion",
            "event_key": "sadness",
            "severity": "medium"
        }
    if intent == "fatigue":
        return {
            "event_type": "emotion",
            "event_key": "fatigue",
            "severity": "low"
        }
    return None

def count_recent_events(
    session: Session,
    user_id: int,
    event_key: str,
    limit: int = 5
) -> int:
    """
    Count recent occurrences of the same event for the user
    """
    events = session.exec(
        select(UserEvent)
        .where(
            UserEvent.user_id == user_id,
            UserEvent.event_key == event_key
        )
        .order_by(UserEvent.occurred_at.desc())
        .limit(limit)
    ).all()

    return len(events)

def get_recent_event_counts(
    session: Session,
    user_id: int,
    event_key: str,
    limit: int = 3
):
    events = session.exec(
        select(UserEvent)
        .where(
            UserEvent.user_id == user_id,
            UserEvent.event_key == event_key
        )
        .order_by(UserEvent.occurred_at.desc())
        .limit(limit)
    ).all()

    return len(events), events


# -------------------------------------------------
# ROUTES
# -------------------------------------------------
@app.get("/")
def home():
    return {"message": "SerenAI backend running (Phase 1)"}

# -------------------------------------------------
# PROFILE
# -------------------------------------------------
@app.post("/api/profile")
def save_profile(
    payload: ProfileIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    profile = session.exec(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    ).first()

    if profile:
        profile.full_name = payload.full_name
        profile.dob = payload.dob
        profile.preferences = payload.preferences
    else:
        profile = UserProfile(
            user_id=current_user.id,
            full_name=payload.full_name,
            dob=payload.dob,
            preferences=payload.preferences
        )
        session.add(profile)

    session.commit()
    session.refresh(profile)

    return {"status": "ok", "profile_id": profile.id}

@app.get("/api/profile")
def get_profile(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    profile = session.exec(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    ).first()

    if not profile:
        return {}

    return {
        "user_id": profile.user_id,
        "full_name": profile.full_name,
        "dob": profile.dob,
        "preferences": profile.preferences
    }

# -------------------------------------------------
# MOM PROFILE
# -------------------------------------------------
@app.post("/api/mom/personality")
def save_mom_personality(
    payload: PersonalityIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    mom = session.exec(
        select(MomProfile).where(MomProfile.user_id == current_user.id)
    ).first()

    if not mom:
        mom = MomProfile(
            user_id=current_user.id,
            personality=payload.personality
        )
        session.add(mom)
    else:
        mom.personality = payload.personality

    session.commit()
    session.refresh(mom)

    return {"status": "ok", "mom_profile_id": mom.id}

# -------------------------------------------------
# VOICE UPLOAD
# -------------------------------------------------
@app.post("/api/mom/upload_voice")
async def upload_mom_voice(
    consent: bool = Form(...),
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    if not consent:
        raise HTTPException(status_code=400, detail="Consent required")

    mom = session.exec(
        select(MomProfile).where(MomProfile.user_id == current_user.id)
    ).first()

    if not mom:
        mom = MomProfile(user_id=current_user.id, consent_given=True)
        session.add(mom)
        session.commit()
        session.refresh(mom)

    saved = []

    for f in files:
        content = await f.read()
        name = f"{uuid.uuid4().hex}{os.path.splitext(f.filename)[1]}"
        path = os.path.join(VOICE_DIR, name)

        async with aiofiles.open(path, "wb") as out:
            await out.write(content)

        voice = MomVoice(
            mom_profile_id=mom.id,
            user_id=current_user.id,
            filename=f.filename,
            stored_name=name,
            path=f"/static/mom_voices/{name}",
            mime_type=f.content_type,
            size_bytes=len(content),
            status="validated"
        )
        session.add(voice)
        saved.append(name)

    session.commit()

    return {"status": "ok", "saved_files": saved}

# -------------------------------------------------
# CHAT (PHASE 1)
# -------------------------------------------------
@app.post("/api/chat", response_model=ChatOut)
def chat(
    payload: ChatIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    message = payload.message
    intent = detect_intent(message)

    # Default response
    response = INTENT_RESPONSES.get(intent, INTENT_RESPONSES["neutral"])

    event_data = intent_to_event(intent)

    # Store event if applicable
    if event_data:
        event = UserEvent(
            user_id=current_user.id,
            event_type=event_data["event_type"],
            event_key=event_data["event_key"],
            severity=event_data["severity"],
            source="ai",
            context={"message": message}
        )
        session.add(event)
        session.commit()

        # 🔥 NEW: repetition check
        repeat_count = count_recent_events(
            session,
            current_user.id,
            event_data["event_key"]
        )

        if intent == "mistake" and repeat_count >= 3:
            response = INTENT_RESPONSES["mistake"]["anger"]
        elif intent == "mistake":
            response = INTENT_RESPONSES["mistake"]["gentle"]

    return {
        "reply": response["reply"],
        "tone": response["tone"]
    }
