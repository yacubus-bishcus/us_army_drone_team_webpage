"""Send notification emails to registered users.

This script connects to the configured users database, gathers every
non-empty email address from the ``users`` table, and sends each
recipient a message. Emails are dispatched individually so delivery failures for one address do not affect the
others. An optional ``--missing_applications`` flag targets only users who
have not yet submitted an application and sends them a pre-defined
reminder message.

Usage (from the project root)::

    python -m scripts.email_users --dry_run --subject "Subject" --message "Message"
    python -m scripts.email_users --dry_run --missing_applications
    python -m scripts.email_users --dry_run --applicants --subject "Subject" --message "Message"
    python -m scripts.email_users --callsigns-file callsigns.txt --subject "Subject" --message "Message"
Use ``--dry-run`` to see which addresses would receive the message
without actually sending any email. Provide ``--callsigns-file`` to
limit notifications to the callsigns listed in the given text file.
"""

from __future__ import annotations

import argparse, logging, os
from pathlib import Path 
from typing import Iterable, List, Set, Tuple
from .load_user_env import load_environment
from sqlalchemy import inspect, text
from drone_team import create_app
from drone_team.db import get_engine, init_team_applications, init_users_db
from drone_team.mailer import send_email, send_admin_email

MISSING_APP_SUBJECT = "ONLY 6 DAYS to Compete for the US Army Drone Team: APPLY TODAY"
MISSING_APP_BODY_TEMPLATE = (
    "Dear {username}, \n\nYou have not submitted an application yet for the US Army "
    "Drone Team. Submit an Application Using the Apply Tab on the Webpage. Once "
    "you have submitted an application the passcode to access the Velocidrone "
    "track will appear on the US Army Drone Team Tab. Please ensure the callsign "
    "submitted on the application exactly matches the callsign used on the "
    "Velocidrone track. The track is open from 15-29 October. If you have multiple "
    "accounts and have applied using a different account you can ignore this email. "
    "\n\nFor questions or concerns reach out to usarmydroneteamexecutiveoffice@gmail.com."
    "\n\nV/r,\n\nUS Army Drone Team"
)


def fetch_user_emails(app, *, callsigns: Iterable[str] | None=None) -> List[str]:
    """Return sorted list of unique email addresses from the users table."""

    with app.app_context():
        init_users_db(app)
        engine = get_engine(app)
        inspector = inspect(engine)
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        has_callsign_column = "callsign" in user_columns

        filters = ["u.email IS NOT NULL", "TRIM(u.email) <> ''"]
        params: dict[str, str] = {}
        normalized_callsigns: List[str] = []

        if callsigns:
            normalized_callsigns = sorted(
                {callsign.strip().lower() for callsign in callsigns if callsign.strip()}
            )

        if normalized_callsigns and not has_callsign_column:
            table_names = set(inspector.get_table_names())
            if "team_applications" not in table_names:
                logging.warning(
                    "Unable to filter by callsign because the team_applications table "
                    "is missing. Returning no recipients."
                )
                return []

        if normalized_callsigns:
            placeholders = ", ".join(
                f":callsign_{index}" for index, _ in enumerate(normalized_callsigns)
            )
            params.update(
                {
                    f"callsign_{index}": callsign
                    for index, callsign in enumerate(normalized_callsigns)
                }
            )

        elif callsigns is not None:
            # An explicit but empty list of callsigns means no recipients.
            return []

        if normalized_callsigns and has_callsign_column:
            filters.append(f"LOWER(TRIM(u.callsign)) IN ({placeholders})")
            query = text(
                f"""
                SELECT DISTINCT u.email
                FROM users u
                WHERE {' AND '.join(filters)}
                ORDER BY u.email
                """
            )
        elif normalized_callsigns:
            filters.append(f"LOWER(TRIM(latest.callsign)) IN ({placeholders})")
            query = text(
                f"""
                WITH latest AS (
                    SELECT username, callsign
                    FROM (
                        SELECT
                            username,
                            callsign,
                            ROW_NUMBER() OVER (
                                PARTITION BY username
                                ORDER BY created_at DESC
                            ) AS rn
                        FROM team_applications
                        WHERE callsign IS NOT NULL AND TRIM(callsign) <> ''
                    ) ranked
                    WHERE rn = 1
                )
                SELECT DISTINCT u.email
                FROM users u
                JOIN latest ON latest.username = u.username
                WHERE {' AND '.join(filters)}
                ORDER BY u.email
                """
            )
        else:
            query = text(
                f"""
                SELECT DISTINCT u.email
                FROM users u
                WHERE {' AND '.join(filters)}
                ORDER BY u.email
                """
            )

        with engine.connect() as connection:
            rows = connection.execute(query, params)
            emails: Set[str] = {
                row.email.strip() for row in rows if getattr(row, "email", None)
            }
    return sorted(emails)


def fetch_applicant_emails(app, *, callsigns: Iterable[str] | None = None) -> List[str]:
    """Return sorted list of unique applicant email addresses."""

    with app.app_context():
        init_team_applications(app)
        engine = get_engine(app)
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        if "team_applications" not in table_names:
            logging.warning(
                "Unable to load applicant emails because the team_applications table is missing."
            )
            return []

        filters = ["a.email IS NOT NULL", "TRIM(a.email) <> ''"]
        params: dict[str, str] = {}
        normalized_callsigns: List[str] = []

        if callsigns:
            normalized_callsigns = sorted(
                {callsign.strip().lower() for callsign in callsigns if callsign.strip()}
            )

        if normalized_callsigns:
            placeholders = ", ".join(
                f":callsign_{index}" for index, _ in enumerate(normalized_callsigns)
            )
            params.update(
                {
                    f"callsign_{index}": callsign
                    for index, callsign in enumerate(normalized_callsigns)
                }
            )
            filters.append(f"LOWER(TRIM(a.callsign)) IN ({placeholders})")

        elif callsigns is not None:
            # An explicit but empty list of callsigns means no recipients.
            return []

        query = text(
            f"""
            SELECT DISTINCT a.email
            FROM team_applications a
            WHERE {' AND '.join(filters)}
            ORDER BY a.email
            """
        )

        with engine.connect() as connection:
            rows = connection.execute(query, params)
            emails: Set[str] = {
                row.email.strip() for row in rows if getattr(row, "email", None)
            }
    return sorted(emails)


def fetch_missing_application_users(app) -> List[Tuple[str, str]]:
    """Return (email, username) tuples for users without applications."""

    with app.app_context():
        init_users_db(app)
        engine = get_engine(app)
        query = text(
            """
            SELECT u.email, u.username
            FROM users u
            LEFT JOIN team_applications t
              ON u.username = t.username
            WHERE t.username IS NULL
              AND u.email IS NOT NULL
              AND TRIM(u.email) <> ''
            ORDER BY u.username
            """
        )
        with engine.connect() as connection:
            rows = connection.execute(query)
            recipients: List[Tuple[str, str]] = []
            seen: Set[str] = set()
            for row in rows:
                email = getattr(row, "email", None)
                username = getattr(row, "username", None)
                if not email or not username:
                    continue
                email = email.strip()
                if email and email not in seen:
                    seen.add(email)
                    recipients.append((email, username))
    return recipients

def load_callsigns_from_file(path: str | os.PathLike[str]) -> List[str]:
    provided_path = Path(path)

    if provided_path.is_absolute():
        candidate_paths = [provided_path]
    else:
        scripts_dir = Path(__file__).resolve().parent
        project_root = scripts_dir.parent
        candidate_paths = [scripts_dir / provided_path, project_root / provided_path]

    file_path: Path | None = None
    for candidate in candidate_paths:
        if candidate.is_file():
            file_path = candidate
            break

    if file_path is None:
        searched = ", ".join(str(candidate) for candidate in candidate_paths)
        raise FileNotFoundError(
            f"Callsign file not found. Looked in: {searched or provided_path}"
        )

    callsigns: List[str] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            callsigns.append(stripped)

    return callsigns

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send information to every user with "
            "a registered email address."
        )
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="List intended recipients without sending any email.",
    )
    parser.add_argument(
        "--subject",
        type=str,
        dest="subject",
        default=None,
        help="Provide the Message Subject Line."
    )
    parser.add_argument(
        "--message",
        dest="body",
        type=str,
        default=None,
        help="Provide the Message body."
    )
    parser.add_argument(
        "--missing_applications",
        dest="missing_applications",
        action="store_true",
        help=(
            "Send the predefined reminder to users who have not submitted an "
            "application."
        ),
    )
    parser.add_argument(
        "--applicants",
        dest="applicants",
        action="store_true",
        help=(
            "Send the message to email addresses collected from the "
            "team_applications table."
        ),
    )
    parser.add_argument(
        "--callsigns-file",
        dest="callsigns_file",
        type=str,
        default=None,
        help=(
            "Path to a text file containing one callsign per line. "
            "Only users matching these callsigns will be emailed."
        )
    )
    parser.add_argument(
        "--admin_email",
        dest="admin_email",
        action="store_true",
        help=(
            "Send the message to the configured admin recipients even when "
            "--dry_run is enabled."
        )
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    load_environment()
    args = parse_args()
    app = create_app()
    subject = args.subject
    body = args.body
    missing_applications = args.missing_applications
    applicants = args.applicants
    callsigns: List[str] | None = None

    if missing_applications and applicants:
        logging.error("The --missing_applications and --applicants flags cannot be used together.")
        return

    if args.callsigns_file:
        try:
            callsigns = load_callsigns_from_file(args.callsigns_file)
        except OSError as exc:
            logging.error("Unable to read callsign file '%s': %s", args.callsigns_file, exc)
            return 
            
        if not callsigns:
            logging.warning("No callsigns found in file %s", args.callsigns_file)
            return 
        logging.info("Restricting email recipients to %d callsigns listed in %s", len(callsigns), args.callsigns_file,)

    if not args.dry_run and not missing_applications:
        if not subject or not body:
            logging.warning("No subject or message body found.")
            return

    if missing_applications:
        recipients = fetch_missing_application_users(app)
        if not recipients:
            logging.warning("No users without applications were found.")
            return
        subject = subject or MISSING_APP_SUBJECT
        logging.info(
            "Prepared to send reminder to %d users without applications.",
            len(recipients),
        )
    else:
        if applicants:
            emails = fetch_applicant_emails(app, callsigns=callsigns)
            if not emails:
                logging.warning("No applicant email addresses found.")
                return
            logging.info(
                "Prepared to send message to %d applicants.",
                len(emails),
            )
        else:
            emails = fetch_user_emails(app, callsigns=callsigns)
            if not emails:
                logging.warning("No user email addresses found.")
                return

            logging.info("Prepared to send message to %d recipients.", len(emails))

    if args.dry_run:
        if args.admin_email:
            logging.info(
                "Dry run enabled; user emails suppressed but an admin notification will be sent."
            )
        else:
            logging.info("Dry run enabled; no emails will be sent.")

    with app.app_context():
        if missing_applications:
            for email, username in recipients:
                personalized_body = MISSING_APP_BODY_TEMPLATE.format(
                    username=username
                )
                if args.dry_run:
                    logging.info(
                        "[DRY RUN] Would send reminder to %s (%s)",
                        username,
                        email,
                    )
                    continue

                try:
                    success = send_email(app, email, subject, personalized_body)
                except Exception as exc:  # pragma: no cover - defensive logging
                    logging.exception(
                        "Failed to send reminder to %s (%s): %s",
                        username,
                        email,
                        exc,
                    )
                    continue

                if success:
                    logging.info("Reminder sent to %s (%s)", username, email)
                else:
                    logging.error(
                        "Failure when sending reminder to %s (%s)",
                        username,
                        email,
                    )
        else:
            for email in emails:
                if args.dry_run:
                    logging.info("[DRY RUN] Would send email to %s", email)
                    continue

                try:
                    success = send_email(app, email, subject, body)
                except Exception as exc:  # pragma: no cover - defensive logging
                    logging.exception("Failed to send email to %s: %s", email, exc)
                    continue

                if success:
                    logging.info("Email sent to %s", email)
                else:
                    logging.error("Failure when sending to %s", email)

        if args.admin_email:
            admin_subject = subject
            if missing_applications:
                admin_body = MISSING_APP_BODY_TEMPLATE.format(username="Admin")
            else:
                admin_body = body

            if not admin_subject or not admin_body:
                logging.warning(
                    "Admin email requested but subject or body is missing; skipping admin email."
                )
            else:
                try:
                    success = send_admin_email(app, admin_subject, admin_body)
                except Exception as exc:  # pragma: no cover - defensive logging
                    logging.exception("Failed to send admin email: %s", exc)
                else:
                    if success:
                        logging.info("Admin email sent to configured recipients.")
                    else:
                        logging.error("Failure when sending admin email.")

    return



if __name__ == "__main__":
    main()
