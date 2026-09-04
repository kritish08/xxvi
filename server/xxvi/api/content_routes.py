from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from xxvi.api.deps import current_session, force_unlocked
from xxvi.auth.golive import is_live
from xxvi.auth.sessions import SessionData
from xxvi.content.loader import get_config
from xxvi.content.schema import RunConfig
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings, get_settings

router = APIRouter(prefix="/api")

MASK = "???"


class TrophyView(BaseModel):
    id: str
    name: str
    grade: str
    hidden: bool


class CopyView(BaseModel):
    coming_soon: str
    teaser: str
    how_to_play: str
    closing: str


class ContentView(BaseModel):
    # The wire contract is `copy`, but BaseModel already defines a (deprecated,
    # pydantic-v1-compat) `copy` *method* -- naming the field `copy` shadows
    # it, which pydantic accepts at runtime (the field wins) but mypy flags
    # as an assignment-type error against the inherited method signature.
    # `Field(alias="copy")` keeps the JSON key `copy` (FastAPI serialises
    # response models by alias) while giving the attribute a name that
    # doesn't collide with anything on BaseModel.
    model_config = ConfigDict(populate_by_name=True)
    copy_block: CopyView = Field(alias="copy")
    trophies: list[TrophyView]


def _bare(config: RunConfig, *, teaser: str = "") -> ContentView:
    """The restricted shape: `coming_soon` (and optionally `teaser`) only,
    no trophy names, no `how_to_play`, no closing message, no trophies at
    all. Used for both tiers below `full` -- anonymous and
    authenticated-but-not-yet-live -- so there is exactly one place that
    defines "what a caller who hasn't earned the real payload gets".
    """
    return ContentView(
        copy=CopyView(coming_soon=config.copy.coming_soon, teaser=teaser, how_to_play="", closing=""),
        trophies=[],
    )


@router.get("/content", response_model=ContentView)
async def content(
    request: Request,
    session: SessionData | None = Depends(current_session),
    settings: Settings = Depends(get_settings),
    forced: bool = Depends(force_unlocked),
) -> ContentView:
    # This route intentionally has no `require_live`/session requirement --
    # it's the one endpoint the coming-soon page needs to be able to read
    # with no session at all (App.tsx calls it before login exists). That
    # used to mean EVERYTHING in it was public: a real anonymous
    # pre-go-live request got all 19 standard trophy names, how_to_play,
    # teaser, and the closing message at 200 -- only hidden-trophy names
    # were ever masked. Only `coming_soon` is meant to be public; see
    # task-30 review finding #4. `_bare()` below is what an anonymous or
    # not-yet-live caller gets instead of the full payload.
    config = getattr(request.app.state, "config", None) or get_config()

    if session is None:
        return _bare(config)

    # An authenticated operator always gets the full payload, live or
    # not -- they run the event and the dashboard needs the real content
    # regardless of the gate (mirrors require_live's own operator carve-out
    # in deps.py). An authenticated PLAYER before go-live still gets
    # `teaser` -- ComingSoon.tsx personalises with it for exactly this
    # caller (see App.tsx's `personalised` branch) -- but nothing past
    # that: trophy names, how_to_play, and the closing message are the
    # payoff of a run he hasn't started yet.
    if session.role != "operator" and not is_live(datetime.now(UTC), settings, forced=forced):
        return _bare(config, teaser=config.copy.teaser)

    earned: frozenset[str] = frozenset()
    repo = RunRepository(request.app.state.sessionmaker)
    run = await repo.get_by_account(session.account_id)
    if run is not None:
        earned = await repo.earned_trophies(run.id)

    return ContentView(
        copy=CopyView(**config.copy.model_dump()),
        trophies=[
            TrophyView(
                id=t.id,
                # Masked here, not in the client — otherwise the names ship
                # in the bundle and devtools spoils them.
                name=MASK if (t.hidden and t.id not in earned) else t.name,
                grade=t.grade,
                hidden=t.hidden,
            )
            for t in config.trophies
        ],
    )
