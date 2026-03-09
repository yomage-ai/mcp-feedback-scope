"""Thread-safe in-memory session and feedback store with async notification."""

from __future__ import annotations

import asyncio
import threading
from typing import Callable

from .models import (
    FeedbackRequest,
    FeedbackStatus,
    Session,
    SessionStatus,
)

import logging

logger = logging.getLogger("mcp-feedback-scope.store")


class FeedbackStore:
    """Central store shared across the web server.

    All public methods are thread-safe. Async waiters use asyncio.Event
    so the web server can await responses without polling.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        self._requests: dict[str, FeedbackRequest] = {}
        self._waiters: dict[str, asyncio.Event] = {}
        self._on_change: list[Callable[[], None]] = []
        self._next_session_id = 1

    def on_change(self, callback: Callable[[], None]) -> None:
        self._on_change.append(callback)

    def _notify(self) -> None:
        for cb in self._on_change:
            try:
                cb()
            except Exception:
                pass

    # ── sessions ──

    def allocate_session_id(self) -> str:
        """Return the next auto-increment session ID."""
        with self._lock:
            sid = str(self._next_session_id)
            self._next_session_id += 1
            return sid

    def register_session(self, session_id: str, title: str = "") -> Session:
        """Register a session with a given ID, or update title if exists."""
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing:
                if title:
                    existing.title = title
                existing.touch()
                return existing
            session = Session(id=session_id, title=title or f"Session {session_id}")
            self._sessions[session_id] = session
            self._notify()
            return session

    def get_or_create_session(self, title: str) -> Session:
        with self._lock:
            for s in self._sessions.values():
                if s.title == title and s.status != SessionStatus.CLOSED:
                    s.touch()
                    return s
            session = Session(title=title)
            self._sessions[session.id] = session
            self._notify()
            return session

    def list_sessions(self) -> list[Session]:
        with self._lock:
            return sorted(
                self._sessions.values(),
                key=lambda s: s.last_activity,
                reverse=True,
            )

    def get_session(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> bool:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                return False
            s.status = SessionStatus.CLOSED
            s.touch()
            self._notify()
            return True

    def disconnect_session(self, session_id: str) -> bool:
        """Mark a session as disconnected and cancel all its pending requests.

        Called when the MCP server process detects that Cursor has closed
        the stdio connection (timeout, user cancel, crash, etc.).
        """
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                return False
            s.status = SessionStatus.DISCONNECTED
            s.touch()
            logger.info("Session %s disconnected", session_id)

            cancelled = 0
            for req in self._requests.values():
                if req.session_id == session_id and req.status == FeedbackStatus.PENDING:
                    req.status = FeedbackStatus.CANCELLED
                    cancelled += 1
                    waiter = self._waiters.get(req.id)
                    if waiter:
                        waiter.set()

            if cancelled:
                logger.info("Cancelled %d pending request(s) for session %s", cancelled, session_id)

            self._notify()
            return True

    # ── feedback requests ──

    def create_request(
        self,
        session_id: str,
        summary: str,
        summary_images: list[str] | None = None,
    ) -> FeedbackRequest:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.status = SessionStatus.WAITING
                session.touch()

            req = FeedbackRequest(
                session_id=session_id,
                summary=summary,
                summary_images=summary_images or [],
            )
            self._requests[req.id] = req
            self._waiters[req.id] = asyncio.Event()
            self._notify()
            return req

    def get_request(self, request_id: str) -> FeedbackRequest | None:
        with self._lock:
            return self._requests.get(request_id)

    def get_pending_request(self, session_id: str) -> FeedbackRequest | None:
        with self._lock:
            for r in reversed(list(self._requests.values())):
                if r.session_id == session_id and r.status == FeedbackStatus.PENDING:
                    return r
            return None

    def list_requests(self, session_id: str) -> list[FeedbackRequest]:
        with self._lock:
            return [
                r
                for r in self._requests.values()
                if r.session_id == session_id
            ]

    def respond(
        self, request_id: str, text: str, images: list[str] | None = None
    ) -> FeedbackRequest | None:
        with self._lock:
            req = self._requests.get(request_id)
            if req is None or req.status != FeedbackStatus.PENDING:
                return None
            req.respond(text, images=images)

            session = self._sessions.get(req.session_id)
            if session:
                session.status = SessionStatus.ACTIVE
                session.touch()

            waiter = self._waiters.get(request_id)
            if waiter:
                waiter.set()

            self._notify()
            return req

    async def wait_for_response(
        self, request_id: str, timeout: float = 3600.0
    ) -> FeedbackRequest | None:
        waiter = self._waiters.get(request_id)
        if waiter is None:
            return None
        try:
            await asyncio.wait_for(waiter.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            with self._lock:
                req = self._requests.get(request_id)
                if req and req.status == FeedbackStatus.PENDING:
                    req.status = FeedbackStatus.TIMEOUT
            return None
        with self._lock:
            return self._requests.get(request_id)

    def cleanup_waiter(self, request_id: str) -> None:
        self._waiters.pop(request_id, None)


# Singleton used by the web server process
store = FeedbackStore()
