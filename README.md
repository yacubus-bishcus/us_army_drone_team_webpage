# US Army Drone Team Webpage Limited Distribution
Beta Release v1 will only include the Drone Team Page.

US Army Drone Team Page
==

The US Army Drone Team drives unmanned aerial systems (UAS) innovation to ensure technological and operational dominance in modern warfare through national and international competitions. By recruiting and training the next generation of drone operators, the Army Drone Team advances tactical and technical capabilities aligned with the Army's Continuous Transformation Initiative. 
Apply Now Option leads to another page where the user can apply to the US Army Drone Team with a standard application form. After inputing applicant details the user will be emailed a confirmation with details to access the Velocidrone Racetrack.

## Local development quickstart

1. update the values for your environment.
2. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Apply database migrations against the database URL defined in `.env`:
   ```bash
   python -m scripts.run_db_migrations
   ```
   The helper wraps `flask db upgrade`, so you do not need to export
   `FLASK_APP`. It is safe to rerun; Alembic only applies new migrations.
4. Initialise the auxiliary SQLite stores the app expects:
   ```bash
   flask --app wsgi init-db
   ```
5. Launch the development server:
   ```bash
   flask --app wsgi run --debug
   ```
### Local data sandboxing
When `SANDBOX_DATA_MODE=true` (the default for local testing) the site stores
news articles and team applications in local CSV/SQLite files. Unset the flag to
exercise the production PostgreSQL-backed code paths. Set `SANDBOX_DATA_MODE=true` in your environment while debugging or running automated tests to ensure the production
Postgres database and Google Sheets remain untouched. When this flag is enabled the application uses a local SQLite database (override the path with `SANDBOX_SQLITE_URL`) and all Google Sheets synchronisation is skipped.

## Collaboration workflow

Active feature development now happens on the `velocidrone` branch. Create pull
requests against that branch instead of `development` so review environments and
deploy previews mirror the latest secure Velocidrone login work.

## Deployment checklist

1. Set `APP_ENV=production` for strict cookies and HTTPS redirects.
2. Provide a PostgreSQL connection string via `DATABASE_URL`.
3. Leave `SANDBOX_DATA_MODE` unset (or explicitly `false`) so the application
   uses PostgreSQL instead of the CSV sandbox mode for news articles.
4. Run database migrations during each deploy. Either execute the helper:
   ```bash
   python -m scripts.run_db_migrations
   ```
   or call the underlying Flask-Migrate command:
   ```bash
   flask --app wsgi db upgrade
   ```
   Render supports [release commands](https://render.com/docs/deploys#release-phase);
   configure one of the commands above so schema changes (such as adding the
   `news_articles.open_count` column) are applied before the web service starts.


## License

Use of this project is governed by a proprietary [End User License Agreement](LICENSE). Redistribution, modification, and other derivative use cases are prohibited without prior written consent.

## Disclaimer

This webpage and its associated respositories are provided for research and educational purposes only. It is not an official U.S. Army communication channel, endorsement, or recruitment
platform, and it should not be interpreted as such. Content, assets, and demonstrations do not represent real-world commitments, capabilities, or policy statements.