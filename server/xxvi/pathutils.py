from pathlib import Path

# `pyproject.toml` is deliberately NOT a sentinel here. In this repo it
# lives in `server/`, one level *below* the true repo root (`.git`, `.env`,
# and `config/` all live at the top). Using it as a fallback sentinel put
# the boundary one directory too shallow in exactly the deploy shape that
# has no `.git` -- a tarball or CI artifact -- silently reintroducing the
# original "wrong/missing .env" bug in a checkout with no `.git` directory.
# `.env.example` is committed, so it travels with any clone, tarball, or CI
# artifact, and it is co-located with `.env` (the file usually being
# searched for) by construction -- it cannot land one level off the way
# `pyproject.toml` did.
_SENTINEL_MARKERS = (".git", ".env.example")


def _repo_boundary(anchor: Path) -> Path | None:
    """The outermost ancestor `find_upwards` is allowed to search.

    Prefers the closest ancestor containing `.git` -- the authoritative
    repo-root marker -- searched across the *whole* ancestor chain first.
    Only if no `.git` exists anywhere up to the filesystem root does this
    fall back to the closest ancestor containing `.env.example`.

    `.git` is checked with priority, not just as an arbitrary tiebreak: a
    later, nearer sentinel candidate must never win over the true root
    found farther up. Checking the whole chain for `.git` before falling
    back to `.env.example` is what keeps the boundary from landing one
    directory too shallow, whichever sentinel ends up being the one that's
    actually present.
    """
    ancestors = [anchor] + list(anchor.parents)
    for marker in _SENTINEL_MARKERS:
        for ancestor in ancestors:
            if (ancestor / marker).exists():
                return ancestor
    return None


def find_upwards(relative_path: str, anchor: Path) -> Path | None:
    """Search `anchor` and each of its ancestor directories for `relative_path`.

    This is the ancestor-walk strategy that makes CWD-relative config work
    whether the process is launched from the repo root or from `server/`
    (the documented dev workflow). Returns the first existing candidate, or
    `None` if no ancestor has it.

    The walk is bounded at the repository boundary (see `_repo_boundary`):
    it never searches past the ancestor that marks the repo root, so an
    unrelated file sitting further up the filesystem (a stray `~/.env` on a
    shared machine, for instance) is never picked up. This matters more for
    `.env` than it ever did for `config_path`: `.env` holds secrets --
    database URL, session secret, reward codes -- not just config.

    If no sentinel exists anywhere up the chain, there is no boundary to
    enforce -- and no safe default either, so this returns `None`
    immediately rather than falling through to an unbounded walk to the
    filesystem root. A build context that ships neither `.git` nor
    `.env.example` (a Docker image built from a `COPY xxvi ./xxvi` context,
    for instance) must not go hunting through the container's directory
    tree for a same-named file that happens to exist somewhere above it.
    Callers that intend a missing-sentinel case to still resolve something
    (there are none today) must opt into that explicitly; the default is to
    stop, not to guess.
    """
    boundary = _repo_boundary(anchor)
    if boundary is None:
        return None
    for ancestor in [anchor] + list(anchor.parents):
        candidate = ancestor / relative_path
        if candidate.exists():
            return candidate
        if ancestor == boundary:
            break
    return None
