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
    python -m scripts.email_users --callsigns-file callsigns.txt --subject "Subject" --message "Message"
Use ``--dry-run`` to see which addresses would receive the message
without actually sending any email. Provide ``--callsigns-file`` to
limit notifications to the callsigns listed in the given text file.
"""

from __future__ import annotations

import argparse, logging, os
from pathlib import Path 
from typing import List, Set, Tuple
from .load_user_env import load_environment
from sqlalchemy import text
from drone_team import create_app
from drone_team.db import get_engine, init_users_db
from drone_team.mailer import send_email

MISSING_APP_SUBJECT = "Reminder: Submit Your US Army Drone Team Application"
MISSING_APP_BODY_TEMPLATE = (
    "Dear {username}, You have not submitted an application yet for the US Army "
    "Drone Team. Submit an Application Using the Apply Tab on the Webpage. Once "
    "you have submitted an application the passcode to access the Velocidrone "
    "track will appear on the US Army Drone Team Tab. Please ensure the callsign "
    "submitted on the application exactly matches the callsign used on the "
    "Velocidrone track. The track is open from 15-29 October. For questions or "
    "concerns reach out to usarmydroneteamexecutiveoffice@gmail.com.\n\nV/r,\n\nUS Army Drone Team"
)


def fetch_user_emails(app, *, callsigns: Iterable[str] | None=None) -> List[str]:
    """Return sorted list of unique email addresses from the users table."""

    with app.app_context():
        init_users_db(app)
        engine = get_engine(app)
        filters = ["email IS NOT NULL", "TRIM(email) <> ''"]
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
            filters.append(f"LOWER(TRIM(callsign)) IN ({placeholders})")
            params.update(
                {
                    f"callsign_{index}": callsign
                    for index, callsign in enumerate(normalized_callsigns)
                }
            )
        elif callsigns is not None:
            # An explicit but empty list of callsigns means no recipients.
            return []

        where_clause = " AND ".join(filters)
        query = text(
            f"""
            SELECT DISTINCT email
            FROM users
            WHERE {where_clause}
            ORDER BY email
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
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Callsign file not found: {file_path}")

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
        "--callsigns-file",
        dest="callsigns_file",
        type=str,
        default=None,
        help=(
            "Path to a text file containing one callsign per line. "
            "Only users matching these callsigns will be emailed."
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
    callsigns: List[str] | None = None 
    
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
        emails = fetch_user_emails(app, callsigns=callsigns)
        if not emails:
            logging.warning("No user email addresses found.")
            return
        
        logging.info("Prepared to send message to %d recipients.", len(emails))

    if args.dry_run:
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

    return



if __name__ == "__main__":
    main()
