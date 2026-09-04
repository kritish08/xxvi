"""Emit the OpenAPI schema to stdout (or a file) without a running server.

`GET /api/openapi.json` is gated behind `require_operator` (an anonymous
visitor must never be able to read the API surface before go-live -- see
xxvi/main.py's docs_router), but the frontend's codegen step still needs
the schema at build time. `FastAPI.openapi()` is a plain method call that
builds the schema in-process; it needs no HTTP request, no session, and no
running server, so this script -- unlike xxvi/cli.py -- is free to import
xxvi.main directly.

    python -m scripts.emit_openapi                    # stdout
    python -m scripts.emit_openapi > openapi.json      # redirect
    python -m scripts.emit_openapi --out openapi.json  # or write directly
"""

import argparse
import json
import sys

from xxvi.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=str, default=None, help="write to this file instead of stdout")
    args = parser.parse_args()

    schema = create_app().openapi()
    text = json.dumps(schema, indent=2)

    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
            f.write("\n")
    else:
        sys.stdout.write(text)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
