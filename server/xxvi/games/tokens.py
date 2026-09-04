import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from xxvi.persistence.repositories import RunRepository
from xxvi.settings import get_settings

_SALT = "xxvi.segment.v1"
CONSUMED_EVENT = "segment_token_consumed"


class TokenInvalid(Exception):
    """Bad signature, expired, wrong run, or already consumed."""


@dataclass(frozen=True)
class SegmentClaim:
    run_id: int
    segment: int
    seed: str
    nonce: str
    issued_at: datetime


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt=_SALT)


# One hour, not ten minutes. 600s was fine when the longest segment was a
# 25s drift, but a stack segment is bounded by a TARGET rather than a clock:
# at 166 blocks a careful player waiting for each alignment can genuinely be
# playing for eight or nine minutes, and an expired token rejects the run
# AFTER all of it. That failure is indistinguishable from missing, which is
# the worst possible way to lose a perfect run.
#
# Lengthening it costs very little. The token is single-use regardless
# (`consumed_tokens`, UNIQUE(run_id, nonce)), and the wall-clock check in
# verify_result still caps a claimed duration against the time the token has
# actually existed -- sitting on a token longer buys nothing.
DEFAULT_SEGMENT_TTL_SECONDS = 3600


def issue_segment_token(
    run_id: int, segment: int, ttl_seconds: int = DEFAULT_SEGMENT_TTL_SECONDS
) -> tuple[str, str]:
    """Returns (token, seed). The seed is sent to the client; the server keeps
    the authoritative copy inside the signed token.

    `ttl_seconds` is carried inside the signed payload and is what actually
    governs expiry (see `decode_segment_token`) -- not whatever `max_age` a
    particular verifier call happens to pass. It used to be accepted here
    and silently dropped, which meant every token's real expiry was governed
    only by the verifier's `max_age` default, identical regardless of what
    the issuer asked for.
    """
    seed = secrets.token_urlsafe(12)
    nonce = secrets.token_urlsafe(9)
    token = _serializer().dumps(
        {
            "run_id": run_id,
            "segment": segment,
            "seed": seed,
            "nonce": nonce,
            "ttl_seconds": ttl_seconds,
        }
    )
    return token, seed


def decode_segment_token(token: str, max_age: int = 600) -> SegmentClaim:
    """`max_age` is an outer ceiling on the itsdangerous signature check
    itself (and the only thing enforced if a legacy/forged payload has no
    `ttl_seconds`). The real, per-issuance expiry is `ttl_seconds`, embedded
    in the signed payload by `issue_segment_token` and checked here against
    the signed issue timestamp -- so a caller can't accidentally widen a
    short-lived token's window by passing a larger `max_age`, and a short
    `ttl_seconds` always shrinks it.
    """
    try:
        payload, issued_at = _serializer().loads(token, max_age=max_age, return_timestamp=True)
    except SignatureExpired:
        raise TokenInvalid("segment token expired") from None
    except BadSignature:
        raise TokenInvalid("segment token signature invalid") from None

    ttl_seconds = int(payload.get("ttl_seconds", max_age))
    age_seconds = (datetime.now(UTC) - issued_at).total_seconds()
    if age_seconds > ttl_seconds:
        raise TokenInvalid("segment token expired")

    return SegmentClaim(
        run_id=int(payload["run_id"]),
        segment=int(payload["segment"]),
        seed=str(payload["seed"]),
        nonce=str(payload["nonce"]),
        issued_at=issued_at,
    )


class TokenService:
    """Enforces single use via a UNIQUE (run_id, nonce) constraint on the
    dedicated `consumed_tokens` table (see `RunRepository.consume_token`).
    That insert is the actual lock. A successful claim also gets an audit
    entry in the run event log, but the event log itself carries no
    constraint and is not what makes this race-safe -- `has_event` +
    `append_event` as a pair is a check-then-act across two separate
    transactions, which two concurrent callers can both pass.
    """

    def __init__(self, repo: RunRepository) -> None:
        self._repo = repo

    async def consume(self, token: str, run_id: int, max_age: int = 600) -> SegmentClaim:
        claim = decode_segment_token(token, max_age=max_age)
        if claim.run_id != run_id:
            raise TokenInvalid("segment token belongs to another run")
        newly_consumed = await self._repo.consume_token(claim.run_id, claim.nonce, claim.segment)
        if not newly_consumed:
            raise TokenInvalid("segment token already consumed")
        await self._repo.append_event(
            run_id, CONSUMED_EVENT, {"nonce": claim.nonce, "segment": claim.segment}
        )
        return claim
