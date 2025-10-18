# scripts/password_reset_admin.py
"""Send notification to user to reset password.

This script connects to the configured users database and sends the
user a password reset message. 

Usage (from the project root)::

    python -m scripts.password_reset_admin --username "Username"

Use ``--dry-run`` to see which addresses would receive the message
without actually sending any email.
"""

import os, logging, argparse
from .load_user_env import load_environment 
from flask import url_for
from drone_team import create_app
from drone_team.db import get_user_by_username, create_password_reset_token
from drone_team.mailer import send_email, send_email_sendgrid

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send password reset instructions to user with "
            "a registered email address."
        )
    )
    parser.add_argument(
        "--username",
        type=str,
        dest="username",
        help="List intended recipients without sending any email.",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="List intended recipients without sending any email.",
    )
    return parser.parse_args()

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    load_environment()
    args = parse_args()

    if not args.username:
        logging.warning("No username provided. Exiting...")
        return 

    app = create_app()
    user = get_user_by_username(app, args.username)

    if not user or not getattr(user, "email", None):
        raise LookupError("User missing or has no email on file")

    if args.dry_run:
        logging.info("Dry run enabled; no emails will be sent.")
        logging.info("[DRY RUN] Would send email to %s", user.email)
        return 

    with app.app_context():
        token = create_password_reset_token(app, user.id)
        reset_url = url_for("auth.reset_password", token=token, _external=True)

        subject = "[drone_team DB] Password reset instructions"
        body = (
            f"Hello {user.username},\n\n"
            "An administrator requested a password reset for your drone_team account.\n\n"
            f"Use the link below to set a new password (expires in one hour):\n{reset_url}\n\n"
            "If you did not expect this change, please contact support at usarmydroneteamexecutiveoffice@gmail.com"
        )

        try:
            success = send_email(app, user.email, subject, body)
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.exception("Failed to send email to %s: %s", user.email, exc)
            success = False

        if success:
            logging.info("Email sent to %s", user.email)
        else:
            logging.error("Failure when sending to %s", user.email)

    return 
    


if __name__ == "__main__":
    main()
