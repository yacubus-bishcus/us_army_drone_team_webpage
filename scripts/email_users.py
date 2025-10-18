"""Send notification to all registered users.

This script connects to the configured users database, gathers every
non-empty email address from the ``users`` table, and sends each
recipient a message. Emails are dispatched individually so delivery failures for one address do not affect the
others.

Usage (from the project root)::

    python -m scripts.email_users --dry_run --subject "Subject" --message "Message"

Use ``--dry-run`` to see which addresses would receive the message
without actually sending any email.
"""

from __future__ import annotations

import argparse, os, logging
from typing import Iterable, List, Set
from .load_user_env import load_environment
from sqlalchemy import text
from drone_team import create_app
from drone_team.db import get_engine, init_users_db
from drone_team.mailer import send_email


def fetch_user_emails(app) -> List[str]:
    """Return sorted list of unique email addresses from the users table."""

    with app.app_context():
        init_users_db(app)
        engine = get_engine(app)
        query = text(
            """
            SELECT DISTINCT email
            FROM users
            WHERE email IS NOT NULL AND TRIM(email) <> ''
            ORDER BY email
            """
        )
        with engine.connect() as connection:
            rows = connection.execute(query)
            emails: Set[str] = {
                row.email.strip() for row in rows if getattr(row, "email", None)
            }
    return sorted(emails)

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
        default="None",
        help="Provide the Message Subject Line."
    )
    parser.add_argument(
        "--message",
        dest="body",
        type=str,
        default="None",
        help="Provide the Message body."
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    load_environment()
    args = parse_args()

    app = create_app()
    subject = args.subject 
    body = args.body 
    
    if not args.dry_run:
        if subject == "None" or body == "None":
            logging.warning("No subject or message body found.")
            return 

    emails = fetch_user_emails(app)
    if not emails:
        logging.warning("No user email addresses found.")
        return

    logging.info("Prepared to send message to %d recipients.", len(emails))
    if args.dry_run:
        logging.info("Dry run enabled; no emails will be sent.")

    with app.app_context():
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
