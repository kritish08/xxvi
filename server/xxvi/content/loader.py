from functools import lru_cache
from pathlib import Path

import yaml

from xxvi.content.schema import RunConfig
from xxvi.pathutils import find_upwards
from xxvi.settings import get_settings

_EXAMPLE_FILENAME = "run.example.yaml"


def load_config(path: Path | str) -> RunConfig:
    """Load and validate a RunConfig from a YAML file."""
    if isinstance(path, str):
        path = Path(path)
    raw = yaml.safe_load(path.read_text())
    return RunConfig.model_validate(raw)


def _resolve_config_path(config_path: str, example_fallback: bool = True) -> Path:
    """
    Resolve a config path, checking multiple locations to support dev and docker environments.

    Tries:
    1. The given path as-is (absolute or CWD-relative)
    2. The same relative path from ancestors of this file (for CWD=server in dev)
    3. run.example.yaml with the same fallback strategy

    Args:
        config_path: Path to search for (e.g., "config/run.yaml")
        example_fallback: If True, also search for run.example.yaml

    Returns:
        Path: The first candidate that exists

    Raises:
        FileNotFoundError: If no path is found, with all attempted locations listed
    """
    candidates = []

    # Try the given path as absolute or CWD-relative
    path = Path(config_path)
    if path.exists():
        return path
    candidates.append(str(path.resolve()))

    # Try the same relative path from ancestor directories of this module
    if not path.is_absolute() and ("/" in config_path or "\\" in config_path):
        # Only walk up for relative paths with directory components
        this_file = Path(__file__).resolve()
        found = find_upwards(config_path, this_file.parent)
        if found is not None:
            return found
        for ancestor in [this_file.parent] + list(this_file.parents):
            candidates.append(str(ancestor / config_path))

    # Try run.example.yaml as fallback
    if example_fallback:
        example_name = config_path.replace("run.yaml", "run.example.yaml")
        return _resolve_config_path(example_name, example_fallback=False)

    # Nothing found
    raise FileNotFoundError(
        f"Config file not found. Searched: {', '.join(candidates)}"
    )


@lru_cache
def resolved_config_path() -> Path:
    """The actual path `get_config()` loads, resolved from settings and
    environment. Split out from `get_config()` so a caller can tell
    WHICH file was served (real vs. `run.example.yaml`) without having to
    re-derive the same resolution logic -- see `is_serving_example_content`.
    """
    settings = get_settings()
    return _resolve_config_path(settings.config_path)


def is_serving_example_content() -> bool:
    """True when `config/run.yaml` could not be found and `get_config()`
    silently fell back to the placeholder `run.example.yaml` instead.

    That fallback (`_resolve_config_path`'s `example_fallback`) is left in
    place deliberately -- it's what lets `get_config()` work out of the box
    in dev/CI with no `config/run.yaml` on disk at all. The bug this
    guards against is not the fallback existing, it's the fallback being
    silent: nothing warned that the *real* run would ask "Q1 placeholder"
    and expect "placeholder1" if `config/run.yaml` was never hand-placed on
    the box. Callers that must not tolerate that silently (`cli
    check-config`, app startup) use this to fail loudly instead.
    """
    return resolved_config_path().name == _EXAMPLE_FILENAME


@lru_cache
def get_config() -> RunConfig:
    """Get cached RunConfig, resolving path from settings and environment."""
    return load_config(resolved_config_path())
