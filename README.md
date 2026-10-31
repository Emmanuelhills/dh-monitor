# Domain & Hosting Monitor

Centralized inventory of domains and hosting accounts with expiration tracking, background
RDAP/WHOIS and provider checks, and Amazon SES reminder emails. Implements PRD v1.0 and
Technical Specification v1.0.

| Component | Technology | Location |
|---|---|---|
| Frontend | Next.js 16 + TypeScript | `frontend/` |
| API | FastAPI (`/api/v1`) | `backend/app/api/` |
| Database | PostgreSQL 17, SQLAlchemy 2 + Alembic | `backend/app/models.py`, `backend/alembic/` |
| Background jobs | Celery worker + Celery beat | `backend/app/tasks/`, `backend/app/celery_app.py` |
| Domain lookups | RDAP (IANA bootstrap), WHOIS fallback | `backend/app/monitoring/` |
| Hosting lookups | Provider adapters (WHMCS, custom JSON API) | `backend/app/monitoring/hosting_adapters/` |
| Email | Amazon SES v2 via boto3 | `backend/app/notifications/` |

**Deploying to GitHub + Vercel:** see [DEPLOY.md](DEPLOY.md).

## Running locally (Windows)

Prerequisites: Python 3.12+, Node 22+, PostgreSQL 17. Redis is optional: use Redis or
[Memurai](https://www.memurai.com/) on Windows, or set `DHM_BROKER_URL` to PostgreSQL (see below).

```powershell
# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env                       # then edit: DB URL, encryption key (python -m app.cli generate-key)
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m app.cli create-admin --email you@example.com

# Frontend
cd ..\frontend
npm install

# Start everything (API, worker, scheduler, frontend) in separate windows
cd ..
.\ops\dev.ps1                                 # open http://localhost:3000
```

Run the processes yourself if you prefer:

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
.\.venv\Scripts\celery -A app.celery_app worker --loglevel=INFO --pool=solo   # --pool=solo is required on Windows
.\.venv\Scripts\celery -A app.celery_app beat --loglevel=INFO
cd ..\frontend; npm run dev
```

**Broker:** `DHM_BROKER_URL=redis://localhost:6379/0` is recommended. Without Redis, Celery can
use PostgreSQL itself: `DHM_BROKER_URL=sqla+postgresql+psycopg://dhm:PASSWORD@localhost:5432/dhm`
(kombu creates `kombu_*` tables; Alembic ignores them).

## Tests

```powershell
cd backend
.\.venv\Scripts\python -m pytest            # unit + integration (needs DHM_TEST_DATABASE_URL: a disposable DB, wiped each run)

cd ..\frontend
npm run typecheck
$env:E2E_EMAIL="you@example.com"; $env:E2E_PASSWORD="..."; npm run test:e2e   # against a running stack
```

The backend suite covers domain normalization, expiration countdowns, reminder windows,
eligibility (active and inactive alike), idempotency, renewal and date-change cancellation,
retry and backoff, SES with a mocked SDK, RDAP and WHOIS parsing, reconciliation conflicts,
CRUD, relationships, filters and sorting, admin-URL privacy, CSRF and the login rate limit.
The Playwright suite walks the end-to-end administrator flow from spec §11 on desktop and
phone. It creates its own records and deletes them afterwards.

## Registrars

*Registrars* lists the companies you buy from. Each one is ticked as providing **domain
names**, **hosting**, or both. Domains pick from the domain registrars, and hosting plans pick
their company from the hosting registrars. "Other" lets you type a company name that isn't in
the list. Renaming a registrar updates the company name shown on its hosting plans. Deleting
one unlinks its records but never deletes them. A domain also keeps the registrar name reported
by RDAP/WHOIS, shown as "Registry reports", so you can spot mismatches.

## Public overview

`/` is a read-only page anyone can open without signing in, so team members can follow
domains and hosting accounts. It shows names, hosting assignment, expiration dates and statuses
(`GET /api/v1/public/overview`). Notes, admin URLs, registrar details, monitoring errors,
history and settings stay behind sign-in. The admin dashboard is at `/dashboard`. Turn the public
page off under *Settings → General*. If the site is reachable from the internet, that list is
public; put it behind your VPN or reverse-proxy access rules if it shouldn't be.

## Key behaviour

- **Statuses are independent.** Usage (active/inactive), service (active/suspended/expired/unknown),
  renewal (unknown/renewed/not renewed) and monitoring (current/due/partial/failed/manual) are
  separate fields and are displayed separately.
- **A passed date is not "expired".** Once overdue with an unknown outcome, the record is shown as
  overdue and a verification check is requested. It becomes *expired* only from a reliable
  source (registry redemption/pending-delete, provider "terminated") or when an administrator
  confirms non-renewal.
- **Lookups never erase data.** Missing or redacted fields are left alone. Failures keep previous
  values. Manual *suspended/expired* states are never overwritten automatically. A source reporting
  an earlier date than a manually entered one, or a registry auto-renew grace period, is
  recorded as a **conflict** in the check history and not applied.
- **Reminders** use the configured schedule (default 30/14/7/3/1 days, expiration day, 7 daily
  overdue reminders) in the configured timezone. Each slot has a window, so a record added late
  still gets its current warning, but stale reminders are never back-filled. The logical key
  `record_type|record_id|expiration_date|interval|recipient` is a unique database key, so any
  number of concurrent schedulers produce one reminder. A reminder is re-validated just before it
  is sent: if the date changed, a renewal was confirmed, notifications were disabled or the
  recipient was removed, it is cancelled instead.
- **Delivery** retries transient SES errors with exponential backoff, up to 5 attempts.
  Permanent errors (rejected, unverified identity, no credentials) fail immediately and are shown
  in *Notification history* with a Retry button. "Sent" means **SES accepted the message**, not
  that it reached an inbox.
- **Privacy.** The hosting admin URL appears only through `GET /hosting-accounts/{id}/admin-url`
  (audited, behind the edit form). It never appears in list or detail responses, change logs or emails. SES and
  integration secrets are Fernet-encrypted with `DHM_ENCRYPTION_KEY` and never returned.

## Amazon SES setup

1. Verify the sender address or its domain in SES (with DKIM, SPF and optionally DMARC).
2. Request production access, or verify each recipient while the account is in the sandbox.
3. Grant `ses:SendEmail`, `ses:GetAccount` and `ses:GetEmailIdentity`, preferably through an
   IAM role on the worker host. Alternatively, enter access keys in *Settings → Email*; they are
   stored encrypted.
4. Optional: a configuration set with event destinations for delivery, bounce and complaint events.
5. In *Settings → Email*: region, sender, recipients and schedule. Then **Validate only** and
   **Send test email**.

## Resend (alternative to SES)

*Settings → Email → Email sender* switches between **Amazon SES** and **Resend**. Only the selected
one sends; the other's settings are kept.

1. At resend.com, add and verify your sending domain (DNS records).
2. Create an API key. *Sending access* is enough, though *Full access* also lets **Validate only**
   confirm that the sender's domain is verified.
3. Choose **Resend**, enter the sender address (on the verified domain) and the API key, then save.
   The key is stored encrypted and never shown again.
4. **Validate only**, then **Send test email**.

Retries and error handling work the same as with SES: rate limits and server errors are retried,
and rejections fail immediately.

## Hosting provider integrations

*Settings → Provider integrations*. Built-in adapters:

- **WHMCS**: next due date and service status through the official API (`GetClientsProducts`).
  Set the hosting account's *Provider service ID* to the WHMCS service ID.
- **Custom JSON API**: any authorized HTTPS endpoint, with a URL template, field paths and a
  status mapping.

Accounts without an integration are maintained manually; their monitoring status is *Manual*.
To add a provider, subclass `HostingAdapter` in `backend/app/monitoring/hosting_adapters/` and
call `register()`. Adapters declare their fields, authentication, rate limit, timeout and retry policy.

## Operations

- **Health:** `GET /api/v1/health` (database and broker; returns 503 when degraded). The dashboard warns
  when the scheduled jobs (`job_runs` heartbeats) have not run for 2 hours.
- **Schedules:** checks are dispatched every 15 minutes, using each record's own interval (default 24 h);
  expiration evaluation runs hourly and reminder evaluation hourly. Every job is idempotent.
- **Logs:** JSON on stdout, with secrets redacted (AWS keys, tokens, passwords, URL credentials).
- **Backups:** `ops\backup.ps1` (Windows; schedule it in Task Scheduler) or `ops/backup.sh` (Docker).
  Both verify the archive. For restores, see `ops/restore.md`. Keep `DHM_ENCRYPTION_KEY` in your
  secret manager: it is not part of the database backup.
- **Production:** `docker compose up -d --build` runs the frontend, API, worker, scheduler (one
  instance), PostgreSQL, Redis and a one-shot migration. Put HTTPS in front of it and set
  `DHM_COOKIE_SECURE=true`. API docs (`/api/v1/docs`) are disabled when
  `DHM_ENVIRONMENT=production`.

## Password reset

- **Forgot password?** on the sign-in page emails a reset link through the selected email sender
  (SES or Resend), so email must be set up first. The link works once, expires after 1 hour, and
  only the newest link is valid. Resetting signs the account out everywhere. The response never
  reveals whether an email address has an account, and requests are limited to 5 per hour per
  email or IP. Links use `DHM_APP_BASE_URL`, so set it to the website address.
- **Settings → Administrators → Set password** lets an admin set another admin's password
  directly. Use it when email isn't working.
- **Locked out with no email?** Run `python -m app.cli reset-password --email you@example.com`
  against the database.

## Security notes

- Server-side sessions (hashed token, HttpOnly, SameSite=Lax cookie, 12 h). Every
  state-changing request requires the `X-CSRF-Token` header that matches the session.
- Passwords are hashed with Argon2. Sign-in is rate-limited to 5 failures per 15 minutes per
  email or IP, persisted in the database.
- All administrative actions are written to `audit_events`, with secrets redacted.
- First-release scope is a single administrator role. The data model leaves room for more users.
