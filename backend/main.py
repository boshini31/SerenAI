# backend/main.py
import os
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import SQLModel, select, Session
from passlib.context import CryptContext
from dotenv import load_dotenv
import aiofiles

from db.session import engine, get_session
from db.models import User, UserProfile, MomProfile, MomVoice, UserEvent

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

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

# -------------------------------------------------
# DEV AUTH (FROZEN)
# -------------------------------------------------
def get_dev_user(session: Session = Depends(get_session)) -> User:
    user = session.exec(select(User).where(User.id == 1)).first()
    if not user:
        user = User(email="dev@seren.ai", hashed_password="dev", name="Seren Dev User")
        session.add(user)
        session.commit()
        session.refresh(user)
    return user

def get_current_user(session: Session = Depends(get_session)) -> User:
    return get_dev_user(session)

# -------------------------------------------------
# SCHEMAS
# -------------------------------------------------
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

# -------------------------------------------------
# INTENTS & RESPONSES
# -------------------------------------------------
INTENT_RESPONSES = {
    "mistake": {
        "gentle": {
            "reply": "Hmm… kanna, it’s okay. But take care of yourself, no?",
            "tone": "gentle-care"
        },
        "anger": {
            "reply": "Kanna… how many times now? I’m saying this because I care. Don’t hurt yourself like this.",
            "tone": "caring-anger"
        },
        "forgive":{
             "reply": "I know it wasn’t easy today, kanna. It’s okay. Just try again tomorrow.",
             "tone": "forgiving"
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
    },
    "improvement": {
        "reply": "That makes me really happy, kanna. I knew you could do it.",
        "tone": "proud"
    }
}

# -------------------------------------------------
# HELPERS
# -------------------------------------------------
def detect_intent(message: str) -> str:
    msg = message.lower()
    if any(w in msg for w in ["skip", "missed", "forgot", "didn't"]):
        return "mistake"
    if any(w in msg for w in ["sad", "lonely", "alone", "cry"]):
        return "sadness"
    if any(w in msg for w in ["tired", "exhausted", "burnt"]):
        return "fatigue"
    if any(w in msg for w in ["ate", "had food", "did eat", "took care"]):
        return "improvement"
    return "neutral"

def detect_mistake_intent(message: str) -> str:
    """
    Determines WHY the mistake happened
    """
    msg = message.lower()

    # Unintentional reasons
    if any(w in msg for w in [
        "busy", "work", "tired", "exhausted",
        "forgot because", "no time", "stuck"
    ]):
        return "unintentional"

    # Intentional / careless
    if any(w in msg for w in [
        "didn't care", "lazy", "ignored",
        "didn't feel like", "just skipped"
    ]):
        return "intentional"

    # default
    return "unknown"


def intent_to_event(intent: str):
    if intent == "mistake":
        return {"event_type": "mistake", "event_key": "generic_mistake", "severity": "medium"}
    if intent == "sadness":
        return {"event_type": "emotion", "event_key": "sadness", "severity": "medium"}
    if intent == "fatigue":
        return {"event_type": "emotion", "event_key": "fatigue", "severity": "low"}
    return None

def get_recent_event_counts(session: Session, user_id: int, event_key: str, limit: int = 3):
    events = session.exec(
        select(UserEvent)
        .where(UserEvent.user_id == user_id, UserEvent.event_key == event_key)
        .order_by(UserEvent.occurred_at.desc())
        .limit(limit)
    ).all()
    return len(events), events

# -------------------------------------------------
# CHAT (PHASE 2 STEP 2)
# -------------------------------------------------
@app.post("/api/chat", response_model=ChatOut)
def chat(payload: ChatIn, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    message = payload.message
    intent = detect_intent(message)

    response = INTENT_RESPONSES.get(intent, INTENT_RESPONSES["neutral"])
    event_data = intent_to_event(intent)

    # check recent mistakes
    mistake_count, _ = get_recent_event_counts(
        session=session,
        user_id=current_user.id,
        event_key="generic_mistake"
    )

    # IMPROVEMENT after mistakes
    if intent == "improvement" and mistake_count >= 2:
        response = {
            "reply": "That makes me really happy, kanna. See? You’re learning to take care of yourself.",
            "tone": "proud"
        }

        session.add(UserEvent(
            user_id=current_user.id,
            event_type="positive_change",
            event_key="meal_improvement",
            severity="low",
            source="ai",
            context={"message": message}
        ))
        session.commit()

        return response

    # normal event logging
    if event_data:
        session.add(UserEvent(
            user_id=current_user.id,
            event_type=event_data["event_type"],
            event_key=event_data["event_key"],
            severity=event_data["severity"],
            source="ai",
            context={"message": message}
        ))
        session.commit()

        if intent == "mistake" and mistake_count >= 2:
            response = INTENT_RESPONSES["mistake"]["anger"]
        elif intent == "mistake":
            response = INTENT_RESPONSES["mistake"]["gentle"]

    return response
