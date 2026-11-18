# Deployment Plan

Plain-language plan for putting the demo online, with a local fallback. Anything that can only be confirmed once the app exists is marked **VERIFY AFTER BUILD**. Pricing and free-tier limits change; check each provider's pricing page on the day. No prices are quoted here.

## 1. Recommendation

- **Frontend**: a Render Web Service (root directory `frontend`).
- **Database**: Neon Postgres (pooled string for the app, direct string for migrations and loading).
- **Backend**: a thin read-only API (FastAPI) on a Render Web Service (root directory `backend`).
- **Batch ingestion** (loading files, including the batch 2 demo): stays local. Run it from the dev machine against Neon.
- **Fallback**: everything local with a native Postgres 17 (database) plus `uvicorn` and `npm run dev`. If any hosted piece misbehaves during the review, switch to local.

Why: the data is loaded once, so the hosted backend only reads. Neon wakes quickly. Render free services sleep when idle, so a keep-alive option and a local fallback are planned.

## 2. Platform comparison

Free tiers and limits change, so treat the notes as "what to check" and confirm on each site.

### Frontend hosts
| | Vercel | Netlify | Cloudflare (Pages) |
|---|---|---|---|
| Free-tier fit | Good for a demo | Good | Good |
| Cold starts | Static pages: none; server features may have small start delays | Similar | Similar |
| Next.js support | Best (made by the Next.js authors) | Supported through an adapter | Supported but needs extra adapter work |
| Setup effort | Lowest: import the repo, set the root folder to `frontend`, add env var | Low | Medium |
| Gotchas | `NEXT_PUBLIC_*` values are baked in at build time, so changing one needs a redeploy; free plan is for non-commercial use | Same build-time rule; some Next.js features lag | Runtime differences from Node can break some Next.js features |

### Backend and database hosts
| | Railway | Render | Fly.io | Neon | Supabase |
|---|---|---|---|---|---|
| Role | Backend (and DB) | Backend (and DB) | Backend (and DB) | Database only | Database (plus extras) |
| Free-tier fit | Trial credits rather than a permanent free plan; confirm current terms | Free web service available | Small allowance; needs a payment card on file at signup (confirm) | Free plan suited to demos | Free plan suited to demos |
| Cold starts | Usually none while credits last | **Free web service sleeps when idle; waking takes about 50 seconds** | Can stop machines when idle and start on request (seconds) | **Auto-suspends when idle, resumes in about 1 second** | Does not sleep by minute, but see pause rule |
| Postgres support | Yes | Yes | Yes (self-managed or managed option; confirm) | Yes, Postgres 17 available | Yes |
| FastAPI support | Yes (Docker or Nixpacks) | Yes (Python web service) | Yes (Docker) | n/a | n/a (could use edge functions; not our code) |
| Setup effort | Low | Low | Medium (command-line tool, Dockerfile) | Low | Low |
| Gotchas | Credits can run out; confirm what happens then | **Free Postgres expires after 30 days**, so do not use it for the review; free web service sleeps ~50s | CLI-driven; more moving parts | Connection limits: use the pooled string; first query after idle is slightly slower | **Project pauses after 7 idle days**; must be restored manually; the hosted API is not needed for our design |

### Verdict per platform
- **Vercel**: workable for the UI, but not chosen; the UI runs on Render.
- **Netlify / Cloudflare**: acceptable alternatives; no advantage for Next.js here.
- **Neon**: use for the database (fast resume, standard Postgres, the same engine as local).
- **Render**: first choice for the API (simple). Accept the ~50 s sleep and keep it awake with an uptime monitor (see Step 7) or warm it up before the review. Do NOT use Render's free Postgres (expires after 30 days).
- **Railway**: equal alternative for the API if credits are available; avoids the sleep.
- **Fly.io**: workable, more setup than needed.
- **Supabase**: workable database, but the 7-idle-day pause is a risk if the review is delayed. Not chosen.

## 3. Step-by-step

Prerequisites: accounts on Neon and Render; the repository pushed to GitHub (`notes/` is gitignored and must not be pushed); Python 3.13 and Node 24 on the dev machine. Commands are PowerShell.

### Step 1. Create the Neon database
1. Install the Neon CLI, then run `neon login` and `neon deploy`. This pulls the connection strings and writes them to a local, gitignored env file. Never commit it.
2. The pooled string (host contains `-pooler`, keep `sslmode=require`) is for the app. The direct string is for migrations and loading.
3. If you prefer the web console: create a project (Postgres 17), open "Connect" and copy both strings.

### Step 2. Migrate and ingest against Neon from your machine
```powershell
cd F:\Interviews\Darkroom\darkroom-analytics\backend
$env:DATABASE_URL = "<your Neon direct connection string>"
python -m app.cli migrate
python -m app.cli ingest ../data/synthetic/batch_1
```
Check: both commands exit 0 (batch 1 is expected to exit 0) and `/api/v1/meta` (needs a Bearer token) later reports `data_revision`. Not verified against Neon; only the commands and paths were checked against the code.
Use Neon's direct (non-pooled) string for `migrate` and ingest, and the pooled string for the API.

Keep batch 2 for the live demo: running `python -m app.cli ingest ../data/synthetic/batch_2` from the same machine creates a new revision and **exits with code 1 on purpose** because one file is rejected (late refund restating Aurelle's earlier month, a changed order, a rejected file, a quarantined overlapping weekly file).

### Step 3. Deploy the backend (Render)
1. New > Web Service > connect the GitHub repo.
2. Root directory: `backend`. Runtime: Python.
3. Build command: `pip install -r requirements.txt`.
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
5. Environment variables (see `.env.example`):
   - `DATABASE_URL` = the Neon pooled string
   - `AUTH_SECRET` = a long random value you generate (for example 32+ random characters)
   - `AUTH_TOKEN_TTL_MINUTES` = `480`
   - `DEMO_USERNAME` = `demo`
   - `DEMO_PASSWORD` = `darkroom-demo`
   - `CORS_ORIGINS` = the frontend address; set in Step 5
   - `PORT` is provided by the platform
6. Deploy. Note the public URL, for example `https://<service>.onrender.com`.

Railway is an equal alternative for the API: root directory `backend`, same start command and variables.

Verified: `backend/requirements.txt` includes `python-multipart`, `tzdata`, `openpyxl` and `pyyaml`. **VERIFY AFTER BUILD**: that the Python version Render uses matches (set a `PYTHON_VERSION` variable if needed).

### Step 4. Deploy the frontend (Render)
1. New > Web Service > connect the GitHub repo. Root directory: `frontend`. Build command: `npm install && npm run build`. Start command: `npm start`.
2. Environment variables (see `.env.example`):
   - `NEXT_PUBLIC_API_BASE_URL` = the backend address from Step 3 (no trailing slash)
   - `NEXT_PUBLIC_DEMO_USERNAME` = `demo`
   - `NEXT_PUBLIC_DEMO_PASSWORD` = `darkroom-demo`
   - `NEXT_PUBLIC_USE_MOCKS` = `false` (`true` renders local mock JSON and needs no backend)
3. Deploy. Note the URL, for example `https://<frontend>.onrender.com`.
Remember: these values are baked in at build time; any change needs a redeploy. Never put `AUTH_SECRET` or the database string in a `NEXT_PUBLIC_*` variable (they would be exposed to every visitor).

### Step 5. Set CORS and redeploy the API
1. On the backend, set `CORS_ORIGINS` to the frontend address as one plain comma-separated string, with no spaces or trailing slash, for example `https://<frontend>.onrender.com,http://localhost:3000`.
2. Redeploy or restart the backend.

### Step 6. Smoke tests
1. `GET <backend>/healthz` returns `{"status": ...}`.
2. Open the frontend site and sign in with the demo credentials shown below the Username and Password fields (`demo` / `darkroom-demo`), then click Sign In. Check that Logout returns to the login page.
3. Overview shows 5 brands with 3 goals each; no "0" where data is missing (glowhaus videos should show stale/Unknown).
4. Click a number: the Evidence drawer opens with source file and row.
5. Creators, Samples and Data health pages load.
6. Browser developer console shows no CORS errors.
7. A call without a token returns 401.
**VERIFY AFTER BUILD**: exact response text and screen labels.

### Step 7. Cold start and keep-alive
- The frontend sends a silent request to the backend's `/healthz` every 14 minutes while the app is open in a browser tab. The backend also pings its own `/healthz` every 14 minutes, which keeps its internal connections warm.
- A Render free service sleeps after about 15 minutes without incoming traffic from outside. The backend's self-ping does not count as outside traffic. For a service that must stay awake, use a free external uptime monitor to request `https://<backend>.onrender.com/healthz` every 10 to 14 minutes.
- Otherwise, before the review: open `<backend>/healthz` (wakes a sleeping Render service, up to about 50 s), then log in and open Overview (wakes Neon, about 1 s).
- Open every screen once so the first click in front of the reviewer is fast.
- Re-run the smoke tests. Confirm the data was loaded (`/api/v1/meta` shows months and brands).
- If the Supabase option were used instead, check the project has not paused (it pauses after 7 idle days). If Render Postgres had been used, it would have expired after 30 days. Neither applies to the recommended setup.

### Step 8. Local fallback (native Postgres, no Docker)
Needs a native PostgreSQL 17 with the `darkroom` role and database created once (see the setup command in `README.md`).
```powershell
cd F:\Interviews\Darkroom\darkroom-analytics\backend
python -m app.cli migrate
python -m app.cli ingest ../data/synthetic/batch_1
uvicorn app.main:app --port 8000
# second terminal
cd ..\frontend
npm install
npm run dev
```
Open http://localhost:3000 and use `demo` / `darkroom-demo`. The local database is on port 5432 by default (set `DATABASE_URL` if yours differs). Run this once the day before to confirm it works; the batch 2 demo is the same ingest command with `batch_2` (it exits 1 by design).

## 4. Known risks and mitigations
| Risk | Mitigation |
|---|---|
| Render free service sleeps (~50 s) | External uptime monitor on `/healthz` every 10 to 14 minutes, or warm up before the review; or use Railway; or local fallback |
| Wrong CORS value causes a blank data screen | Exact origin, no trailing slash, plain string; check the console |
| `NEXT_PUBLIC_*` changed but the site shows old behaviour | Redeploy the frontend |
| Neon pooler rejects a migration | Use the direct string for migrate and ingest |
| Secrets in Git or in the browser bundle | Env vars only; no secrets in `NEXT_PUBLIC_*`; `notes/` never pushed |
| Free-tier terms change | Re-check pricing pages before the review; keep the local fallback ready |
