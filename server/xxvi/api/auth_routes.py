from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from xxvi.api.deps import current_session, force_unlocked, get_sessionmaker_dep
from xxvi.auth.golive import is_live, seconds_until_live
from xxvi.auth.passwords import verify_password
from xxvi.auth.sessions import SESSION_COOKIE, SessionData, issue_session
from xxvi.persistence.models import Account
from xxvi.settings import Settings, get_settings

router = APIRouter(prefix="/api")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    role: str


class SessionInfo(BaseModel):
    authenticated: bool
    role: str | None
    live: bool
    seconds_until_live: int


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    response: Response,
    sessionmaker: async_sessionmaker = Depends(get_sessionmaker_dep),
) -> LoginResponse:
    async with sessionmaker() as session:
        result = await session.execute(select(Account).where(Account.username == body.username))
        account = result.scalar_one_or_none()

    if account is None or not verify_password(body.password, account.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    token = issue_session(SessionData(account_id=account.id, role=account.role))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=True)
    return LoginResponse(role=account.role)


@router.post("/auth/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/session", response_model=SessionInfo)
async def session_info(
    session: SessionData | None = Depends(current_session),
    settings: Settings = Depends(get_settings),
    forced: bool = Depends(force_unlocked),
) -> SessionInfo:
    now = datetime.now(UTC)
    return SessionInfo(
        authenticated=session is not None,
        role=session.role if session else None,
        live=is_live(now, settings, forced=forced),
        seconds_until_live=seconds_until_live(now, settings),
    )
