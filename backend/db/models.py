# backend/db/models.py
from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, Text, Integer, Boolean, JSON, TIMESTAMP

# -----------------------
# SQLModel models for SerenAI
# -----------------------

class User(SQLModel, table=True):
    __tablename__ = "users"
    id: Optional[int] = Field(default=None, primary_key=True)
    # use sa_column for unique constraint; do NOT set index=True when using sa_column
    email: str = Field(sa_column=Column(Text, unique=True, nullable=False))
    hashed_password: str = Field(sa_column=Column(Text, nullable=False))
    name: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = Field(default=None)


class UserProfile(SQLModel, table=True):
    __tablename__ = "user_profiles"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    full_name: Optional[str] = Field(default=None)
    dob: Optional[str] = Field(default=None)  # stored as DATE in DB; string accepted here
    preferences: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MomProfile(SQLModel, table=True):
    __tablename__ = "mom_profiles"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    personality: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    voice_model_id: Optional[str] = Field(default=None)
    voice_model_type: Optional[str] = Field(default=None)
    voice_ready: bool = Field(default=False)
    persona_model_id: Optional[str] = Field(default=None)
    persona_ready: bool = Field(default=False)
    consent_given: bool = Field(default=False)
    consent_granted_at: Optional[datetime] = Field(default=None)
    voice_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MomVoice(SQLModel, table=True):
    __tablename__ = "mom_voices"
    id: Optional[int] = Field(default=None, primary_key=True)
    mom_profile_id: int = Field(foreign_key="mom_profiles.id")
    user_id: int = Field(foreign_key="users.id")
    filename: str
    stored_name: str
    path: str
    mime_type: Optional[str] = Field(default=None)
    size_bytes: Optional[int] = Field(default=None)
    duration_secs: Optional[float] = Field(default=None)
    checksum: Optional[str] = Field(default=None)
    status: str = Field(default="pending")
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    type: str
    status: str = Field(default="queued")
    meta: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    error_msg: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AuditEvent(SQLModel, table=True):
    __tablename__ = "audit_events"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    event_type: str
    payload: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    ip_address: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ErrorCatalog(SQLModel, table=True):
    __tablename__ = "error_catalog"
    id: Optional[int] = Field(default=None, primary_key=True)
    error_code: str = Field(sa_column=Column(Text, unique=True, nullable=False))
    http_status: int = Field(sa_column=Column(Integer, nullable=False))
    short_message: str = Field(sa_column=Column(Text, nullable=False))
    long_message: Optional[str] = Field(default=None)
    severity: str = Field(default="error")
    i18n_key: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ErrorOccurrence(SQLModel, table=True):
    __tablename__ = "error_occurrence"
    id: Optional[int] = Field(default=None, primary_key=True)
    error_code: Optional[str] = Field(default=None)  # nullable; DB FK handled at SQL level
    user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    request_path: Optional[str] = Field(default=None)
    http_method: Optional[str] = Field(default=None)
    http_status: Optional[int] = Field(default=None)
    details: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
