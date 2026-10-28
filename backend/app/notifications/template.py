"""Reminder email content. Never includes admin URLs, credentials or provider tokens."""

from html import escape

from app.models import DataSource, Domain, HostingAccount
from app.notifications.ses import OutgoingEmail
from app.services.domain_names import display_domain_name
from app.services.expiration import ExpirationInfo


def record_label(record: Domain | HostingAccount) -> tuple[str, str]:
    if isinstance(record, Domain):
        return "Domain", display_domain_name(record.normalized_domain_name)
    return "Hosting account", record.name


def record_link(base_url: str, record: Domain | HostingAccount) -> str:
    path = "domains" if isinstance(record, Domain) else "hosting"
    return f"{base_url.rstrip('/')}/{path}/{record.id}"


def _timing(info: ExpirationInfo) -> str:
    if info.days_remaining is None:
        return "has an unknown expiration date"
    if info.days_remaining > 0:
        return f"expires in {info.days_remaining} day{'s' if info.days_remaining != 1 else ''}"
    if info.days_remaining == 0:
        return "expires today"
    overdue = -info.days_remaining
    return f"is overdue by {overdue} day{'s' if overdue != 1 else ''}"


def render_reminder(record: Domain | HostingAccount, info: ExpirationInfo, base_url: str) -> OutgoingEmail:
    kind, name = record_label(record)
    subject = f"Expiration reminder: {name} {_timing(info)}"
    verified = record.expiration_source != DataSource.manual and record.expiration_verified_at is not None
    rows: list[tuple[str, str]] = [
        ("Record", f"{kind}: {name}"),
        ("Expiration date", record.expiration_date.isoformat() if record.expiration_date else "Unknown"),
        ("Time remaining", info.label),
        ("Usage status", record.usage_status.value.capitalize()),
        ("Service status", record.service_status.value.capitalize()),
    ]
    if isinstance(record, Domain):
        hosting = record.hosting_account
        rows.append(("Hosting account", hosting.name if hosting else "Unassigned"))
        if record.registrar_name:
            rows.append(("Registrar", record.registrar_name))
    else:
        rows.append(("Hosting company", record.provider_name))
    rows.append(
        (
            "Date source",
            f"Verified via {record.expiration_source.value.upper()}" if verified else "Maintained manually (unverified)",
        )
    )
    link = record_link(base_url, record)

    text = "\n".join(
        [subject, "", *[f"{label}: {value}" for label, value in rows], "", f"Open the record: {link}", "",
         "You receive this because expiration reminders are enabled in Domain & Hosting Monitor."]
    )
    html_rows = "".join(
        f'<tr><th align="left" style="padding:4px 16px 4px 0;color:#555;font-weight:600">{escape(label)}</th>'
        f'<td style="padding:4px 0">{escape(value)}</td></tr>'
        for label, value in rows
    )
    html = f"""<!doctype html><html><body style="font-family:Arial,Helvetica,sans-serif;color:#1a1a1a">
<h2 style="font-size:18px;margin:0 0 12px">{escape(subject)}</h2>
<table cellspacing="0" cellpadding="0" style="font-size:14px">{html_rows}</table>
<p style="margin:20px 0"><a href="{escape(link)}" style="background:#1f5fbf;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none">Open record</a></p>
<p style="font-size:12px;color:#777">You receive this because expiration reminders are enabled in Domain &amp; Hosting Monitor.</p>
</body></html>"""
    return OutgoingEmail(to="", subject=subject, text=text, html=html)


def render_test_email(sender: str, provider: str = "Amazon SES") -> OutgoingEmail:
    subject = "Domain & Hosting Monitor: test email"
    text = (
        "This is a test message from Domain & Hosting Monitor.\n\n"
        f"{provider} accepted it from {sender}. Expiration reminders will use the same configuration."
    )
    html = f"<p>This is a test message from Domain &amp; Hosting Monitor.</p><p>{escape(provider)} accepted it from {escape(sender)}. Expiration reminders will use the same configuration.</p>"
    return OutgoingEmail(to="", subject=subject, text=text, html=html)
