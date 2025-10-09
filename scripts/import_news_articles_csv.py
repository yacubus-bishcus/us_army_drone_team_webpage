"""Import news articles from a CSV file into the configured database."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

import click
from dotenv import load_dotenv
from sqlalchemy import inspect, select

from drone_team import create_app
from drone_team.extensions import db
from drone_team.models import NewsArticle

CSV_HEADERS = [
    "id",
    "url",
    "title",
    "summary",
    "image_url",
    "added_by",
    "added_at",
]

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Load environment variables from the project .env file when present."""
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _parse_datetime(value: str) -> datetime:
    value = value.strip()
    if not value:
        raise ValueError("added_at column cannot be empty")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported datetime format: {value}") from exc


def _iter_rows(csv_path: Path) -> Iterable[Tuple[dict, int]]:
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [h for h in CSV_HEADERS if h not in (reader.fieldnames or [])]
        if missing:
            raise click.ClickException(
                f"CSV file is missing required columns: {', '.join(missing)}"
            )
        for idx, row in enumerate(reader, start=2):  # header is line 1
            yield row, idx


def _normalize_row(raw: dict, line_number: int) -> dict:
    try:
        added_at = _parse_datetime(raw["added_at"])
    except KeyError as exc:
        raise click.ClickException(
            f"Line {line_number}: missing required column {exc.args[0]}"
        ) from exc
    except ValueError as exc:
        raise click.ClickException(f"Line {line_number}: {exc}") from exc

    row_id = (raw.get("id") or "").strip()
    if not row_id:
        raise click.ClickException(f"Line {line_number}: id column cannot be empty")

    url = (raw.get("url") or "").strip()
    title = (raw.get("title") or "").strip()
    if not url:
        raise click.ClickException(f"Line {line_number}: url column cannot be empty")
    if not title:
        raise click.ClickException(f"Line {line_number}: title column cannot be empty")

    return {
        "id": row_id,
        "url": url,
        "title": title,
        "summary": (raw.get("summary") or "").strip() or None,
        "image_url": (raw.get("image_url") or "").strip() or None,
        "added_by": (raw.get("added_by") or "").strip() or "admin",
        "added_at": added_at,
    }


@click.command()
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--dry-run",
    is_flag=True,
    help="Parse the CSV and report the operations without modifying the database.",
)
def main(csv_path: Path, dry_run: bool) -> None:
    """Load news articles from CSV into the configured database."""
    _load_dotenv()
    app = create_app()

    with app.app_context():
        inspector = inspect(db.engine)
        if not inspector.has_table(NewsArticle.__tablename__):
            raise click.ClickException(
                "news_articles table is missing. Run 'flask db upgrade' before importing."
            )

        existing_ids = set(db.session.execute(select(NewsArticle.id)).scalars())

        created = 0
        updated = 0

        for raw_row, line_number in _iter_rows(csv_path):
            payload = _normalize_row(raw_row, line_number)
            if payload["id"] in existing_ids:
                article = db.session.get(NewsArticle, payload["id"])
                if article is None:
                    article = NewsArticle(id=payload["id"])
                    db.session.add(article)
                article.url = payload["url"]
                article.title = payload["title"]
                article.summary = payload["summary"]
                article.image_url = payload["image_url"]
                article.added_by = payload["added_by"]
                article.added_at = payload["added_at"]
                updated += 1
            else:
                article = NewsArticle(**payload)
                db.session.add(article)
                created += 1
                existing_ids.add(payload["id"])

        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()

    action = "would import" if dry_run else "imported"
    click.echo(
        f"{action} {created} new article(s) and {updated} existing article(s) from {csv_path}."
    )


if __name__ == "__main__":
    main()
