from dataclasses import asdict, dataclass

from itsdangerous import BadSignature, URLSafeSerializer

from xxvi.settings import get_settings

SESSION_COOKIE = "xxvi_session"
_SALT = "xxvi.session.v1"


@dataclass(frozen=True)
class SessionData:
    account_id: int
    role: str


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt=_SALT)


def issue_session(data: SessionData) -> str:
    return _serializer().dumps(asdict(data))


def read_session(token: str) -> SessionData | None:
    try:
        payload = _serializer().loads(token)
    except BadSignature:
        return None
    try:
        return SessionData(account_id=int(payload["account_id"]), role=str(payload["role"]))
    except (KeyError, TypeError, ValueError):
        return None
