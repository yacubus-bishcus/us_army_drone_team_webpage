"""Send notification emails to registered users.

This script connects to the configured users database, gathers every
non-empty email address from the ``users`` table, and sends each
recipient a message. Emails are dispatched individually so delivery failures for one address do not affect the others. Use ``--delay-seconds`` to throttle bulk sends when an SMTP provider enforces rate limits.

An optional ``--missing_applications`` flag targets only users who have not yet submitted an application and sends them a pre-defined reminder message.

An optional ``--applicants`` flag targets only users that have submitted an application and sends them a custom message. 

An optional ``--callsigns-file`` flag targets emails based on the leaderboard callsigns and sends them a custom message.

Usage (from the project root)::

    python -m scripts.email_users --dry_run --subject "Subject" --message "Message"
    python -m scripts.email_users --dry_run --missing_applications
    python -m scripts.email_users --dry_run --applicants --subject "Subject" --message "Message"
    python -m scripts.email_users --callsigns-file callsigns.txt --subject "Subject" --message "Message"
    python -m scripts.email_users --delay-seconds 2 --subject "Subject" --message "Message"

Use ``--dry-run`` to see which addresses would receive the message
without actually sending any email. Within messages insert variable {username} to address users.
"""

from __future__ import annotations

import argparse, logging, os, time
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


def unescape_newlines(s: str) -> str:
    return s.replace("\\n", "\n")

def fetch_user_emails(
    app, *, callsigns: Iterable[str] | None = None
) -> Tuple[List[Tuple[str, str]], Set[str]]:
    """Return unique (email, username) pairs from the users table.

    When callsigns are provided the second item in the returned tuple contains the
    normalized callsigns that matched at least one user record.
    """

    with app.app_context():
        init_users_db(app)
        engine = get_engine(app)
        inspector = inspect(engine)
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        has_callsign_column = "callsign" in user_columns

        filters = ["u.email IS NOT NULL", "TRIM(u.email) <> ''", "u.username IS NOT NULL", "TRIM(u.username) <> ''"]
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
                return [], set()

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
            return [], set()

        if normalized_callsigns and has_callsign_column:
            filters.append(f"LOWER(TRIM(u.callsign)) IN ({placeholders})")
            query = text(
                f"""
                SELECT
                    u.username,
                    u.email,
                    LOWER(TRIM(u.callsign)) AS matched_callsign
                FROM users u
                WHERE {' AND '.join(filters)}
                ORDER BY u.username
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
                SELECT
                    u.username,
                    u.email,
                    LOWER(TRIM(latest.callsign)) AS matched_callsign
                FROM users u
                JOIN latest ON latest.username = u.username
                WHERE {' AND '.join(filters)}
                ORDER BY u.username
                """
            )
        else:
            query = text(
                f"""
                SELECT u.username, u.email
                FROM users u
                WHERE {' AND '.join(filters)}
                ORDER BY u.username
                """
            )

        with engine.connect() as connection:
            rows = connection.execute(query, params)
            recipients: List[Tuple[str, str]] = []
            seen: Set[str] = set()
            matched_callsigns: Set[str] = set()
            for row in rows:
                email = getattr(row, "email", None)
                username = getattr(row, "username", None)
                if not email or not username:
                    continue
                email = email.strip()
                if not email or email in seen:
                    continue
                seen.add(email)
                recipients.append((email, username))
                matched = getattr(row, "matched_callsign", None)
                if matched:
                    matched_callsigns.add(str(matched).strip().lower())
    return recipients, matched_callsigns


def fetch_applicant_emails(
    app, *, callsigns: Iterable[str] | None = None
) -> Tuple[List[Tuple[str, str]], Set[str]]:
    """Return unique (email, username) pairs for applicants.

    When callsigns are provided the second item in the returned tuple contains the
    normalized callsigns that matched at least one application.
    """

    with app.app_context():
        init_team_applications(app)
        engine = get_engine(app)
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        if "team_applications" not in table_names:
            logging.warning(
                "Unable to load applicant emails because the team_applications table is missing."
            )
            return [], set()

        filters = [
            "a.email IS NOT NULL",
            "TRIM(a.email) <> ''",
            "a.username IS NOT NULL",
            "TRIM(a.username) <> ''",
        ]
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
            return [], set()

        query = text(
            f"""
            SELECT
                a.username,
                a.email,
                LOWER(TRIM(a.callsign)) AS matched_callsign
            FROM team_applications a
            WHERE {' AND '.join(filters)}
            ORDER BY a.username
            """
        )

        with engine.connect() as connection:
            rows = connection.execute(query, params)
            recipients: List[Tuple[str, str]] = []
            seen: Set[str] = set()
            matched_callsigns: Set[str] = set()
            for row in rows:
                email = getattr(row, "email", None)
                username = getattr(row, "username", None)
                if not email or not username:
                    continue
                email = email.strip()
                if not email or email in seen:
                    continue
                seen.add(email)
                recipients.append((email, username))
                matched = getattr(row, "matched_callsign", None)
                if matched:
                    matched_callsigns.add(str(matched).strip().lower())
    return recipients, matched_callsigns


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
        type=unescape_newlines,
        default=None,
        help="Provide the Message body. use literal \\n for line breaks."
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
    parser.add_argument(
        "--SANDBOX_DISABLE",
        dest="sandbox_disable",
        action="store_true",
        help=(
            "Override SANDBOX_DATA_MODE and force sandbox features off even if the "
            "environment enables them."
        )
    )

    parser.add_argument(
        "--delay-seconds",
        dest="delay_seconds",
        type=float,
        default=float(os.getenv("EMAIL_USERS_DELAY_SECONDS", "0") or 0),
        help=(
            "Seconds to pause after each SMTP send attempt. This can help avoid "
            "provider rate limits during bulk notifications. Defaults to the "
            "EMAIL_USERS_DELAY_SECONDS environment variable or 0."
        ),
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    load_environment()
    args = parse_args()
    override = False 
    if getattr(args, "sandbox_disable", False):
        override = True 
        logging.info("SANDBOX_DATA_MODE disabled; Accessing production database.")

    app = create_app(override)
    subject = args.subject
    body = args.body
    missing_applications = args.missing_applications
    applicants = args.applicants
    callsigns: List[str] | None = None
    callsign_pairs: List[Tuple[str, str]] = []
    recipients: List[Tuple[str, str]] = []
    matched_callsigns: Set[str] = set()
    delay_seconds = max(args.delay_seconds or 0, 0)

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
        logging.info(
            "Restricting email recipients to %d callsigns listed in %s",
            len(callsigns),
            args.callsigns_file,
        )
        callsign_pairs = [
            (callsign, callsign.strip().lower()) for callsign in callsigns if callsign.strip()
        ]

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
            recipients, matched_callsigns = fetch_applicant_emails(app, callsigns=callsigns)
            unmatched_callsigns: List[str] = []
            if callsign_pairs:
                seen_normals: Set[str] = set()
                for original, normalized in callsign_pairs:
                    if not normalized or normalized in seen_normals:
                        continue
                    seen_normals.add(normalized)
                    if normalized not in matched_callsigns:
                        unmatched_callsigns.append(original)
            if unmatched_callsigns:
                logging.warning(
                    "Usernames not found for callsigns: %s",
                    ", ".join(unmatched_callsigns),
                )
            if not recipients:
                logging.warning("No applicant email addresses found.")
                return
            logging.info(
                "Prepared to send message to %d applicants.",
                len(recipients),
            )
        else:
            recipients, matched_callsigns = fetch_user_emails(app, callsigns=callsigns)
            unmatched_callsigns: List[str] = []
            if callsign_pairs:
                seen_normals: Set[str] = set()
                for original, normalized in callsign_pairs:
                    if not normalized or normalized in seen_normals:
                        continue
                    seen_normals.add(normalized)
                    if normalized not in matched_callsigns:
                        unmatched_callsigns.append(original)
            if unmatched_callsigns:
                logging.warning(
                    "Usernames not found for callsigns: %s",
                    ", ".join(unmatched_callsigns),
                )
            if not recipients:
                logging.warning("No user email addresses found.")
                return

            logging.info("Prepared to send message to %d recipients.", len(recipients))

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

                if delay_seconds:
                    time.sleep(delay_seconds)
        else:
            for email, username in recipients:
                if args.dry_run:
                    logging.info(
                        "[DRY RUN] Would send email to %s (%s)",
                        username,
                        email,
                    )
                    continue

                try:
                    personalized_body = body.format(username=username)
                except (IndexError, KeyError, ValueError) as exc:
                    logging.error(
                        "Unable to format message body for %s (%s): %s",
                        username,
                        email,
                        exc,
                    )
                    continue

                try:
                    success = send_email(app, email, subject, personalized_body)
                except Exception as exc:  # pragma: no cover - defensive logging
                    logging.exception("Failed to send email to %s: %s", email, exc)
                    continue

                if success:
                    logging.info("Email sent to %s (%s)", username, email)
                else:
                    logging.error("Failure when sending to %s (%s)", username, email)

                if delay_seconds:
                    time.sleep(delay_seconds)

        if args.admin_email:
            admin_subject = subject
            if missing_applications:
                admin_body = MISSING_APP_BODY_TEMPLATE.format(username="Admin")
            else:
                try:
                    admin_body = body.format(username="Admin") if body else body
                except (IndexError, KeyError, ValueError) as exc:
                    logging.error("Unable to format admin email body: %s", exc)
                    admin_body = None

            if not admin_subject or not admin_body:
                logging.warning(
                    "Admin email requested but subject or body is missing; skipping admin email."
                )
                logging.warning(f"Subject: %s", admin_subject)
                logging.warning(f"Body: %s", admin_body)
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
