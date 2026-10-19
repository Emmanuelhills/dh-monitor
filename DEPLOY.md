# Deploying to GitHub + Vercel

The repository deploys as **two Vercel projects from the same GitHub repo**:

| Vercel project | Root directory | What it is |
|---|---|---|
| `dhm-api` | `backend` | FastAPI as a Python serverless function |
| `dhm-web` | `frontend` | Next.js site; proxies `/api/v1/*` to `dhm-api`, so sign-in cookies stay on one domain |

Vercel has no always-on worker, so in Vercel mode (detected automatically) background work runs
through **`/api/v1/cron/run`**. GitHub Actions calls it every 15 minutes
(`.github/workflows/scheduled-checks.yml`), and Vercel Cron calls it daily as a backup. Each call
runs due domain checks, expiration evaluation, reminders and email delivery, then stops after
45 seconds. Anything left over runs on the next call.

The database is **Neon Postgres**, added from inside Vercel (it has a free plan).

---

## 1. Push to GitHub

Create an **empty private** repository on github.com (no README), then from the project folder:

```powershell
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

## 2. Create the API project (`dhm-api`)

1. Go to vercel.com → **Add New… → Project** → import the repository.
2. Set **Root Directory** to `backend`. Leave **Framework Preset** as *Other*. Click **Deploy**.
   The first deploy can fail until the database exists; that's fine.
3. In the project, open **Storage → Create Database → Neon** and connect it to this project.
   This adds `DATABASE_URL` automatically.
4. Open **Settings → Environment Variables** and add:

   | Name | Value |
   |---|---|
   | `DHM_ENCRYPTION_KEY` | Copy it from `backend\.env`. Use the same key so stored secrets keep working. |
   | `CRON_SECRET` | Any long random string. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
   | `DHM_APP_BASE_URL` | The website URL from step 4, e.g. `https://dhm-web.vercel.app` (used in email links) |

5. Open **Deployments → ⋯ → Redeploy**.

## 3. Create the database tables and copy your data

Copy `DATABASE_URL` from the Neon tab (**Storage → your database → .env.local → show secret**), then run:

```powershell
.\ops\deploy-db.ps1 -TargetUrl "<DATABASE_URL>" -CopyLocalData
```

This creates the tables, then copies your domains, hosting plans, registrars, settings and admin
login. Leave out `-CopyLocalData` to start with an empty database. In that case, create the first
admin by adding `DHM_BOOTSTRAP_ADMIN_EMAIL` and `DHM_BOOTSTRAP_ADMIN_PASSWORD` (12+ characters)
to `dhm-api`. Redeploy, sign in once with them, then delete the password variable.

## 4. Create the website project (`dhm-web`)

1. **Add New… → Project** → import the **same** repository again.
2. Set **Root Directory** to `frontend` (Framework: Next.js is detected automatically).
3. Add the environment variable `BACKEND_URL` set to the API URL from step 2, e.g. `https://dhm-api.vercel.app`.
4. Click **Deploy**. Open the URL and sign in.

## 5. Turn on the 15-minute background checks

In GitHub, open **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `API_URL` | `https://dhm-api.vercel.app` (your API URL) |
| `CRON_SECRET` | The same value as on Vercel |
| `DATABASE_URL` | The Neon connection string. With this set, future schema changes migrate automatically on push. |

Run it once by hand: **Actions → Scheduled checks → Run workflow**. Its log shows how many domains were checked.

---

## After setup

- **Every push to `main`** redeploys both projects and runs CI (backend tests and frontend build).
  Schema changes are migrated by `.github/workflows/migrate.yml`.
- **Custom domain:** add it to `dhm-web` (*Settings → Domains*), then update `DHM_APP_BASE_URL` on `dhm-api`.
- **Email (SES):** set it up in the app under *Settings → Email*, the same as locally.
- **Public overview:** anyone with the website URL can see the domain list at `/`. Turn it off
  under *Settings → General* if the site shouldn't be public.
- **Logs:** *Vercel → dhm-api → Logs*. The dashboard warns if scheduled jobs stop running.
