"""Data models for sessions and feedback requests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SessionStatus(str, Enum):
    ACTIVE = "active"
    WAITING = "waiting"
    CLOSED = "closed"
    DISCONNECTED = "disconnected"


class FeedbackStatus(str, Enum):
    PENDING = "pending"
    RESPONDED = "responded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Session:
    id: str = field(default_factory=_new_id)
    title: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    last_activity: datetime = field(default_factory=_utcnow)
    status: SessionStatus = SessionStatus.ACTIVE

    def touch(self) -> None:
        self.last_activity = _utcnow()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "status": self.status.value,
        }


@dataclass
class FeedbackRequest:
    id: str = field(default_factory=_new_id)
    session_id: str = ""
    summary: str = ""
    summary_images: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    status: FeedbackStatus = FeedbackStatus.PENDING
    response: str | None = None
    response_images: list[str] = field(default_factory=list)
    responded_at: datetime | None = None

    def respond(self, text: str, images: list[str] | None = None) -> None:
        self.response = text
        self.response_images = images or []
        self.status = FeedbackStatus.RESPONDED
        self.responded_at = _utcnow()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "summary": self.summary,
            "summary_images": self.summary_images,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "response": self.response,
            "response_images": self.response_images,
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
        }
