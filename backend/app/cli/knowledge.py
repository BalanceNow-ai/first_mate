"""Knowledge corpus commands.

* ``python -m app.cli ingest-knowledge --synthetic [--admit]`` — ingest the synthetic
  fixtures in ``app/seed/knowledge`` (development/test only; ``--admit`` admits them).
* ``python -m app.cli ingest-knowledge PATH --title T --publisher P --licence L --domain D
  [--licence-verified] [--applies-to-json JSON] [--url U] [--version V]`` — ingest a
  real, licensed text/markdown document. It stays ``pending`` until an admin admits it
  through ``POST /knowledge/sources/{id}/admit``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.core.errors import AppError


def _print_result(result) -> None:
    s = result.source
    print(f"{result.status:12} {s.admission_status:9} chunks={result.chunk_count:<3} {s.id} {s.title}")


async def run(args: argparse.Namespace) -> int:
    from app.database import async_session
    from app.services.rag.chunking import parse_front_matter
    from app.services.rag.ingestion import SourceMetadata, ingest
    from app.services.rag.seed import ingest_synthetic_corpus

    settings = get_settings()
    try:
        if args.synthetic:
            if args.path:
                print("--synthetic takes no PATH")
                return 2
            if not settings.is_local:
                print("Refusing: synthetic fixtures may only be ingested in development/test.")
                return 1
            async with async_session() as db:
                results = await ingest_synthetic_corpus(db, admit_sources=args.admit)
                await db.commit()
            for result in results:
                _print_result(result)
            return 0

        if args.admit:
            print("--admit is only available with --synthetic; admit licensed sources via the admin API.")
            return 2
        if not args.path or not (args.title and args.publisher and args.licence and args.domain):
            print("PATH, --title, --publisher, --licence and --domain are required")
            return 2
        path = Path(args.path)
        if not path.is_file():
            print(f"No such file: {path}")
            return 1
        meta_fm, body = parse_front_matter(path.read_text(encoding="utf-8"))
        applies_to = json.loads(args.applies_to_json) if args.applies_to_json else meta_fm.get("applies_to", {})
        meta = SourceMetadata(
            title=args.title,
            publisher=args.publisher,
            url=args.url,
            licence=args.licence,
            licence_verified=bool(args.licence_verified),
            domain=args.domain,
            applies_to=applies_to,
            is_synthetic=False,
            version=args.version,
            facts=list(meta_fm.get("facts", [])),
        )
        async with async_session() as db:
            result = await ingest(db, meta, body)
            await db.commit()
        _print_result(result)
        print("The source is pending until an admin admits it.")
        return 0
    except AppError as exc:
        print(f"Error ({exc.code}): {exc.message}")
        return 1
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Error: {type(exc).__name__}: {exc}")
        return 1


def register(sub) -> None:
    p = sub.add_parser("ingest-knowledge", help="Ingest knowledge sources (pending until admitted)")
    p.add_argument("path", nargs="?", help="text/markdown file of licensed content")
    p.add_argument("--synthetic", action="store_true", help="ingest the synthetic fixtures (local only)")
    p.add_argument("--admit", action="store_true", help="with --synthetic: admit the fixtures")
    p.add_argument("--title")
    p.add_argument("--publisher")
    p.add_argument("--licence")
    p.add_argument("--domain")
    p.add_argument("--url")
    p.add_argument("--version")
    p.add_argument("--licence-verified", action="store_true")
    p.add_argument("--applies-to-json", help='e.g. {"engine_make": "Yamaha", "engine_model": "F150"}')
    p.set_defaults(handler=run)
