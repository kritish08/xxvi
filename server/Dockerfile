# Build context is server/ (see docker-compose.yml: `build: ./server`). The
# resulting image has /app/xxvi, /app/alembic, /app/pyproject.toml -- and
# deliberately no .git, no .env.example, no .env. Real config arrives at
# runtime as environment variables (compose's `env_file: .env`), which
# pydantic-settings reads directly -- see xxvi/settings.py and
# xxvi/pathutils.py's find_upwards, which returns None (not an unbounded
# filesystem walk) when neither sentinel is present, exactly as it is here.
FROM python:3.12-slim
WORKDIR /app

# Installed before the source is copied so dependency layers cache across
# source-only changes. This step installs the third-party dependencies
# declared in pyproject.toml; it does NOT make `xxvi` importable via
# site-packages (there is no xxvi/ on disk yet for setuptools to package).
# That's fine: uvicorn adds the process cwd (this WORKDIR) to sys.path when
# resolving an "xxvi.main:app" import string, so the plain source tree
# copied in below is what actually runs -- confirmed by running this exact
# shape (install stub, then add source, then import by cwd) outside Docker.
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY xxvi ./xxvi
COPY alembic ./alembic
COPY alembic.ini ./

# config/run.yaml is NEVER baked in here -- it is gitignored real content,
# mounted read-only by docker-compose.yml (`./config:/app/config:ro`).

EXPOSE 8000
CMD ["uvicorn", "xxvi.main:app", "--host", "0.0.0.0", "--port", "8000"]
