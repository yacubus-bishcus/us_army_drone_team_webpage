"""Utility entrypoint to run Alembic migrations with the Flask app context.

Usage (from the repo root)::

    python -m scripts.run_db_migrations

This mirrors the ``flask db upgrade`` command but avoids needing to export
environment variables manually.  It is safe to run multiple times; Alembic will
only apply migrations that have not been run yet.
"""

from flask_migrate import upgrade

from drone_team import create_app


def main() -> None:
    app = create_app()
    with app.app_context():
        upgrade()
        app.logger.info("Database migrations applied (alembic upgrade head)")


if __name__ == "__main__":
    main()
