import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from xxvi.api import auth_routes, content_routes, operator_routes, run_routes, ws_routes
from xxvi.api.deps import require_operator
from xxvi.auth.sessions import SessionData
from xxvi.content.loader import is_serving_example_content
from xxvi.persistence.models import Account
from xxvi.persistence.session import get_sessionmaker
from xxvi.settings import Settings, get_settings

logger = logging.getLogger(__name__)

health_router = APIRouter()

# Not the entire structure of the game for an anonymous browser to read.
# The coming-soon page is the only thing an anonymous visitor is meant to
# ever see, with no hint of what's behind it -- but FastAPI's default
# /api/docs and /api/openapi.json are public by default and, until gated,
# hand out all fifteen paths and the Difficulty enum to anyone who asks
# before go-live. `docs_url=None, openapi_url=None` below turns the
# built-in versions off entirely; these two routes reimplement them behind
# `require_operator`. `server/scripts/emit_openapi.py` is the way to get
# the schema locally for frontend codegen without needing a running,
# authenticated server.
docs_router = APIRouter()


@docs_router.get("/api/openapi.json", include_in_schema=False)
async def openapi_json(
    request: Request,
    session: SessionData = Depends(require_operator),
) -> JSONResponse:
    return JSONResponse(request.app.openapi())


@docs_router.get("/api/docs", include_in_schema=False)
async def api_docs(session: SessionData = Depends(require_operator)) -> HTMLResponse:
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="XXVI API")


@health_router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def seed_accounts(sessionmaker: async_sessionmaker, settings: Settings) -> None:
    """Two accounts, from env. No signup, no recovery. Idempotent."""
    wanted = [
        (settings.player_username, settings.player_password_hash, "player"),
        (settings.operator_username, settings.operator_password_hash, "operator"),
    ]
    async with sessionmaker() as session:
        for username, password_hash, role in wanted:
            if not username or not password_hash:
                continue
            result = await session.execute(select(Account).where(Account.username == username))
            account = result.scalar_one_or_none()
            if account is None:
                session.add(Account(username=username, password_hash=password_hash, role=role))
            else:
                account.password_hash = password_hash
                account.role = role
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "sessionmaker"):
        app.state.sessionmaker = get_sessionmaker()
    # KNOWN LIMITATION (documented loudly in docs/runbook.md's own section
    # on this): force-golive is in-memory only, not persisted to the
    # database. Every restart resets it to False here, so an operator who
    # forced go-live before a restart has to notice `GET /api/session`
    # went back to `live: false` and force it again -- there is no alarm
    # for this. Deliberately left in-memory rather than adding a new DB
    # table/migration for a once-only live event this close to the 20th;
    # see the runbook section for the operator-facing mitigation.
    app.state.force_unlocked = False
    await seed_accounts(app.state.sessionmaker, get_settings())
    # `cli check-config` is the operator's explicit preflight for this, but
    # nothing stops the container itself from starting with config/run.yaml
    # missing (it's gitignored and volume-mounted, never baked into the
    # image) -- this is the same failure surfacing on every boot, not just
    # the one deliberate check, so it logs loudly here too rather than only
    # where an operator has to remember to look. run.example.yaml is now a
    # real, playable demo config (not the old "Q1 placeholder" content), so
    # this warning no longer claims the run is uncompletable -- it just
    # says plainly that this is the demo, not the real event.
    if is_serving_example_content():
        logger.warning(
            "config/run.yaml not found -- serving run.example.yaml, the "
            "playable demo config. This run can be finished end to end, "
            "but its reward codes are placeholders. For a real run, place "
            "config/run.yaml on this box, set real REWARD_{n}_CODE values, "
            "and restart; run `python -m xxvi.cli check-config` to confirm "
            "it took."
        )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="XXVI",
        # Disabled here, reimplemented above behind require_operator -- an
        # anonymous visitor must never be able to read the API surface
        # before go-live. See docs_router's comment.
        docs_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.force_unlocked = False
    app.include_router(health_router)
    app.include_router(docs_router)
    app.include_router(auth_routes.router)
    app.include_router(content_routes.router)
    app.include_router(run_routes.router)
    app.include_router(operator_routes.router)
    app.include_router(ws_routes.router)
    return app


app = create_app()
