# MarketingOS

An AI marketing department for small businesses and the agencies that serve them. One workspace covers content,
Instagram publishing, Meta and Google Ads, SEO, AI-search visibility (GEO), analytics and agency client
management. Specialised AI agents draft the work. **Nothing is published and no money is spent until a person
approves exactly what will run.**

This repository contains:

| Path | What it is |
|---|---|
| `backend/` | FastAPI + SQLAlchemy API, background worker and scheduler, Alembic migrations, 65 tests |
| `web/` | Next.js 16 web app (every web screen in the PRD) |
| `mobile/` | Expo / React Native app (Home, Create, Calendar, Campaigns, Profile, Approvals) |
| `packages/api-client/` | Typed TypeScript client shared by web and mobile |

## Quick start

### With Docker

```bash
docker compose up --build
```

Then open http://localhost:3000 and create an account. The web server forwards `/api/v1` and `/media` to the API
container, so the browser only ever talks to port 3000. The API is also published on http://localhost:8000
(OpenAPI docs at `/docs`). To load the demo agency into the containers:

```bash
docker compose exec api python -m app.seed_demo
```

### Without Docker

Backend (Python 3.12+; uses SQLite unless `DATABASE_URL` is set):

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
cd backend && .venv/bin/python -m app.seed_demo
```

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
cd backend && .venv/bin/python -m app.worker
```

Web:

```bash
cd web && npm install && npm run dev
```

Mobile (set `EXPO_PUBLIC_API_URL` to an address your phone can reach):

```bash
cd mobile && npm install && npx expo start
```

`app.seed_demo` creates a demo agency (**demo@northstar-demo.in / DemoPassw0rd!**) with one client, sandbox
integrations and 60 days of sample performance data. Every sample row is stored with `source="demo"` and the UI
shows a "demo data" notice wherever it appears.

## How it works

- **Tenancy.** Every business record carries a `workspace_id`. An agency's clients each get their own workspace.
  Organisation owners and admins see every workspace in their organisation; everyone else sees only the workspaces
  they're added to. Permissions are checked on the server for every request. Records from another tenant return
  404, so ids can't be probed.
- **Roles.** Agency Owner, Administrator, Account Manager, Marketing Manager, Content Creator, Analyst, Client
  Approver and Viewer (`backend/app/permissions.py`). Nobody can grant a role above their own.
- **Approvals.** Publishing, scheduling, launching or activating campaigns, budget increases and other changes to
  live campaigns create an approval holding the exact payload that will run. On approval the engine re-reads the
  resource and refuses to execute if it changed after the request (payload hash check). Pausing and budget
  decreases follow configurable workspace policies. Self-approval can be switched off per workspace.
- **Spend limits.** Each workspace has daily budget caps for Meta and Google. Drafts above the cap can't be
  approved, and submission re-checks the cap.
- **AI autonomy.** `backend/app/services/policy.py` classifies every action as automatic (drafting, analysing,
  recommending) or requiring approval, matching the PRD's autonomy table.
- **Credits.** Every AI operation has a configurable cost (`credit_costs` table). Users see the estimate first.
  Credits are charged only after the operation succeeds, in the same transaction that stores its output. Agencies
  can move credits to and from client wallets. Every movement is an auditable transaction.
- **Background work.** Generation, crawling, publishing, ad submission, syncing and GEO monitoring run in a
  Postgres-backed job queue (`SELECT … FOR UPDATE SKIP LOCKED`) with retries and backoff. The worker also runs a
  scheduler: due posts, scheduled GEO monitoring and reports, daily syncs and push notifications.
- **Provenance.** Analytics tag every number as *measured* (reported by a platform), *calculated*, or *internal*
  (a MarketingOS indicator such as the SEO or GEO score). The reporting assistant answers only from that data and
  labels recommendations separately. Keyword volumes, difficulty and CPC are never invented: without a data source
  they stay empty and the UI says what to connect.
- **Sandbox connections.** Instagram, Meta Ads and Google Ads can be connected in sandbox mode. This runs the whole
  approval and publishing flow but records actions locally, never calls the platform, and generates no metrics.
  The server refuses sandbox mode when `ENVIRONMENT=production`.

## Configuration

Copy `backend/.env.example` to `backend/.env`. Everything works offline by default: AI drafting uses
deterministic templates, connections can be sandboxed, and payments run in test mode. To go live:

| Capability | Set |
|---|---|
| AI writing and images | `AI_PROVIDER=openai`, `OPENAI_API_KEY` |
| GEO monitoring | `OPENAI_API_KEY` (Responses API web search) and/or `PERPLEXITY_API_KEY` |
| Instagram publishing, Meta Ads | `META_APP_ID`, `META_APP_SECRET` (the app needs Meta's review for the listed permissions) |
| Google Ads, Search Console, GA4, Google sign-in | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_ADS_DEVELOPER_TOKEN` |
| Keyword metrics without Google Ads | `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` |
| Payments | `PAYMENTS_MODE=razorpay`, `RAZORPAY_*`, and a Razorpay plan id per plan |
| Email | `EMAIL_BACKEND=smtp`, `SMTP_*` |

`PUBLIC_API_URL` must be reachable from the internet in production: Instagram fetches media from it, and OAuth
callbacks return to it.

## Status against the PRD

### Built and covered by automated tests

Run against SQLite and PostgreSQL 16; the web flows were also driven end to end in a browser.

- Registration, login, refresh-token rotation with reuse detection, email verification, password reset, TOTP
  two-factor authentication, rate limiting on auth endpoints.
- Workspaces, members and invitations, agency clients, client isolation, role checks, credit allocation, audit log.
- Brand memory, used by every generation. Prohibited claims block approval.
- Content Studio: 14 content types, variations, versions, section regeneration, quality checks against platform
  limits, export, approval.
- Instagram: scheduling and publishing via approvals, retries on temporary failures, cancel and reschedule,
  re-approval after edits. The live Graph API sequence is tested against mocked responses.
- Meta and Google Ads: drafts, the step-by-step wizard, AI-generated drafts, validation, launch approval, budget
  increase approval, configurable pause policy, spend caps, campaign discovery and insights sync, and an optimiser
  whose recommendations cite measured numbers. Meta submission is tested against mocked Graph API responses.
- SEO: a robots.txt-respecting crawler, 38 issue types across technical, on-page, content and performance,
  an internal health score, recommendations with reason, impact and steps, competitor audits, keyword tracking
  with intent estimates and clustering, plan limits.
- GEO: projects, prompt library and suggestions, monitoring with per-query charging (failed queries are free),
  mention, citation, position and sentiment extraction, share of voice, competitor visibility, content-gap
  recommendations, and manual import for engines without an API.
- Analytics: cross-channel KPIs with period comparison, channel comparison, ROI with an attribution note, client
  comparison for agencies, the reporting assistant, PDF and CSV reports, white-label branding, scheduled reports.
- AI agents: plan preview with a credit estimate, an orchestrated run (strategy, SEO, GEO, content, creative,
  social, Meta Ads, SEM), grouped approvals with "approve all", cancellation, per-agent enable switches, a live log
  (polling and WebSocket).
- Billing: plans, subscriptions and credit packs in test mode; Razorpay webhook with signature verification and
  idempotency; invoices; usage.

### Built against official API documentation but not yet verified with live accounts

These need real app credentials (and, for Meta and Google Ads, platform review) before launch:

- Meta Graph API: Facebook Login, Instagram content publishing, insights, Marketing API campaign, ad set, creative
  and ad creation, insights sync.
- Google: OAuth, Google Ads REST (`googleAds:mutate`, `googleAds:search`, Keyword Planner), Search Console, GA4
  Data API, Google sign-in.
- OpenAI (Chat Completions with JSON schema, Images, Responses with web search), Perplexity Sonar, PageSpeed
  Insights, DataForSEO, Razorpay orders and subscriptions, WordPress and Shopify credential checks, Expo push.

### Deliberate deviations and gaps

- **Job queue:** Postgres instead of Celery or Temporal. Only `services/jobs.py` and the worker would change to switch.
- **Agent orchestration:** an in-house step runner instead of LangGraph.
- **Brand memory:** the brand profile is passed directly into the prompt; there is no pgvector retrieval yet.
- **Tenant isolation:** enforced in the application (every query is scoped, cross-tenant ids return 404, covered by
  tests). PostgreSQL row-level security policies are not added yet.
- **File storage:** local disk under `STORAGE_DIR`, behind a small interface. S3 needs a mounted bucket or a new backend.
- **Not built:** video generation (Reel scripts and storyboards are generated), publishing to WordPress or
  Shopify (connection only), and the Google Ads search-terms report.
- **Credit expiry:** credits don't expire, and plans state this.
- **Offline AI mode:** writes English regardless of the language selected; non-English output needs an AI provider.
- **Mobile:** account creation happens on the web. Detailed creative editing, SEO audits, campaign set-up and
  agency administration are web-only, as the PRD allows.
- **Deployment:** the Docker stack (Postgres, Redis, API, worker, web) has been built and run end to end: migrations,
  demo data, sign-in, content and image generation through the worker, and an agent run.

## Development

```bash
cd backend && .venv/bin/ruff check app tests && .venv/bin/pytest -q
```

```bash
cd backend && DATABASE_URL=postgresql+psycopg://user:pass@localhost/marketingos_test .venv/bin/pytest -q
```

```bash
cd web && npx tsc --noEmit && npx next build
```

```bash
cd mobile && npx tsc --noEmit
```

After changing models, generate a migration:

```bash
cd backend && .venv/bin/alembic revision --autogenerate -m "describe the change"
```

CI (`.github/workflows/ci.yml`) runs lint, both test suites, the migration drift check, the web build and the
mobile typecheck.

## Security notes

- Integration tokens are encrypted at rest (Fernet) and never returned by the API.
- Access tokens last 15 minutes. Refresh tokens rotate, and reusing one signs out every session of that user.
- Uploads are checked against an allow-list, by content signature as well as declared type. SVGs containing
  scripts are rejected, and SVGs are served with a restrictive Content-Security-Policy.
- Razorpay webhooks are verified with HMAC-SHA256 and processed once.
- Production refuses to start with development secrets, sandbox connections or test payments.
- The web app keeps its session in `localStorage`. For stricter XSS isolation, move to httpOnly cookies behind a
  same-site backend-for-frontend.
