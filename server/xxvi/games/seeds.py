import hashlib

FACE_BUTTONS = 4


def simon_sequence(seed: str, length: int) -> list[int]:
    """Deterministic face-button sequence for a seed.

    Uses a counter-mode hash rather than `random` so that the sequence is
    stable across Python versions, and so a shorter sequence is always a
    prefix of a longer one for the same seed.
    """
    out: list[int] = []
    counter = 0
    while len(out) < length:
        digest = hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        out.extend(byte % FACE_BUTTONS for byte in digest)
        counter += 1
    return out[:length]
