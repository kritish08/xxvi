from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import async_sessionmaker

from xxvi.auth.golive import is_live
from xxvi.auth.sessions import SESSION_COOKIE, SessionData, read_session
from xxvi.settings import Settings, get_settings


def get_sessionmaker_dep(request: Request) -> async_sessionmaker:
    return request.app.state.sessionmaker


def force_unlocked(request: Request) -> bool:
    return bool(getattr(request.app.state, "force_unlocked", False))


def current_session(request: Request) -> SessionData | None:
    token = request.cookies.get(SESSION_COOKIE)
    return read_session(token) if token else None


def require_session(session: SessionData | None = Depends(current_session)) -> SessionData:
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    return session


def require_player(
    session: SessionData = Depends(require_session),
    settings: Settings = Depends(get_settings),
) -> SessionData:
    if session.role == "player":
        return session
    # Dry run exists so the operator can play the full experience before
    # go-live -- spec's dress rehearsal, called higher-value than any unit
    # test. `require_live` already lets the operator's requests past the
    # go-live gate under dry_run (see below); without this, every player
    # route still 403s him here, making that rehearsal path inert
    # everywhere except GET /api/session (measured: player 423, anonymous
    # 423, operator 403 -- the rehearsal never actually ran).
    if settings.dry_run and session.role == "operator":
        return session
    raise HTTPException(status.HTTP_403_FORBIDDEN, "player role required")


def require_operator(session: SessionData = Depends(require_session)) -> SessionData:
    if session.role != "operator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "operator role required")
    return session


def require_live(
    settings: Settings = Depends(get_settings),
    forced: bool = Depends(force_unlocked),
    session: SessionData | None = Depends(current_session),
) -> None:
    # Dry run is a rehearsal path for the operator only. He still waits.
    if settings.dry_run and session is not None and session.role == "operator":
        return
    if not is_live(datetime.now(UTC), settings, forced=forced):
        raise HTTPException(status.HTTP_423_LOCKED, "not yet")
