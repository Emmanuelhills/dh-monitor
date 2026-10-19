"""Administrative commands.

    python -m app.cli create-admin --email you@example.com      (prompts for the password)
    python -m app.cli reset-password --email you@example.com
    python -m app.cli generate-key                               (new DHM_ENCRYPTION_KEY)
    python -m app.cli run-job evaluate_reminders                 (run a scheduled job once, inline)
"""

import argparse
import getpass
import sys

from sqlalchemy import func, select


def _read_password() -> str:
    password = getpass.getpass("Password (min 12 characters): ")
    if len(password) < 12:
        sys.exit("Password must be at least 12 characters.")
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("Passwords do not match.")
    return password


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create-admin", "reset-password"):
        p = sub.add_parser(name)
        p.add_argument("--email", required=True)
        p.add_argument("--password-stdin", action="store_true", help="Read the password from stdin")
    sub.add_parser("generate-key")
    job = sub.add_parser("run-job")
    job.add_argument("name", choices=["dispatch_due_checks", "evaluate_expirations", "evaluate_reminders",
                                       "dispatch_notifications"])
    args = parser.parse_args(argv)

    if args.command == "generate-key":
        from cryptography.fernet import Fernet

        print(Fernet.generate_key().decode())
        return

    if args.command == "run-job":
        from app.tasks import jobs

        task = {
            "dispatch_due_checks": jobs.dispatch_due_checks,
            "evaluate_expirations": jobs.evaluate_expirations_task,
            "evaluate_reminders": jobs.evaluate_reminders_task,
            "dispatch_notifications": jobs.dispatch_notifications,
        }[args.name]
        print(task.apply().get())
        return

    from app.db import session_scope
    from app.models import User
    from app.services.audit import record_audit
    from app.services.auth import hash_password

    password = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else _read_password()
    if len(password) < 12:
        sys.exit("Password must be at least 12 characters.")
    email = args.email.strip().lower()
    with session_scope() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if args.command == "create-admin":
            if user:
                sys.exit(f"User {email} already exists. Use reset-password.")
            db.add(User(email=email, password_hash=hash_password(password)))
            record_audit(db, "admin_created", actor="cli", details={"email": email})
        else:
            if not user:
                sys.exit(f"User {email} does not exist.")
            user.password_hash = hash_password(password)
            record_audit(db, "password_reset", actor="cli", details={"email": email})
    print(f"OK: {args.command} {email}")


if __name__ == "__main__":
    main()
