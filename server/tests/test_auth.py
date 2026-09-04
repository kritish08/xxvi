import xxvi.auth.sessions as sessions_module
from xxvi.auth.passwords import hash_password, verify_password
from xxvi.auth.sessions import SessionData, issue_session, read_session
from xxvi.settings import Settings


def test_password_round_trips_and_rejects_wrong_input():
    hashed = hash_password("correct horse")
    assert verify_password("correct horse", hashed) is True
    assert verify_password("wrong horse", hashed) is False


def test_hash_is_salted_so_two_hashes_of_one_password_differ():
    assert hash_password("same") != hash_password("same")


def test_verify_password_rejects_empty_string_hash_without_raising():
    # Settings.player_password_hash / operator_password_hash both default
    # to "". If an env var is missing on deploy day, the first login
    # attempt must be cleanly denied, not crash the login path.
    assert verify_password("whatever", "") is False


def test_verify_password_rejects_malformed_hash_without_raising():
    assert verify_password("whatever", "not-a-hash-at-all") is False


def test_verify_password_rejects_hash_from_a_different_algorithm_without_raising():
    # A valid-looking but non-argon2 hash (bcrypt's $2b$ format) must be
    # rejected, not raise. argon2-cffi raises InvalidHashError (a
    # ValueError subclass, not a VerificationError subclass) for this.
    bcrypt_shaped = "$2b$12$KIXQ4Z9Z9Z9Z9Z9Z9Z9Z9uZ9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9"
    assert verify_password("whatever", bcrypt_shaped) is False


def test_session_round_trips():
    token = issue_session(SessionData(account_id=7, role="player"))
    restored = read_session(token)
    assert restored == SessionData(account_id=7, role="player")


def test_tampered_session_is_rejected():
    token = issue_session(SessionData(account_id=7, role="player"))
    # Flip a character in the middle of the token rather than the very
    # last one: the trailing base64 sextet of an HMAC-SHA1 signature has
    # unused padding bits, so some substitutions at position -1 decode to
    # the same bytes and the tampered token would still verify. A
    # mid-token flip always changes a fully-constrained byte.
    middle = len(token) // 2
    original = token[middle]
    replacement = "a" if original != "a" else "b"
    tampered = token[:middle] + replacement + token[middle + 1 :]
    assert read_session(tampered) is None


def test_garbage_session_is_rejected_without_raising():
    assert read_session("not-a-token") is None


def test_session_signing_uses_the_configured_secret_not_a_hardcoded_one(monkeypatch):
    monkeypatch.setattr(
        sessions_module, "get_settings", lambda: Settings(session_secret="secret-a")
    )
    token = issue_session(SessionData(account_id=1, role="player"))

    monkeypatch.setattr(
        sessions_module, "get_settings", lambda: Settings(session_secret="secret-b")
    )
    assert read_session(token) is None


def test_session_signing_is_salted_so_a_different_salt_cannot_verify_it(monkeypatch):
    monkeypatch.setattr(sessions_module, "_SALT", "salt-a")
    token = issue_session(SessionData(account_id=1, role="player"))

    monkeypatch.setattr(sessions_module, "_SALT", "salt-b")
    assert read_session(token) is None
