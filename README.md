# Evaluated Guardrail Agent with CI

A production-grade, guardrailed agent that answers questions **only from cited
evidence**, blocks **prompt injection**, redacts **PII**, and gates every
**high-stakes action** behind a human approval — with an automated evaluation
suite wired into **CI** and a **Next.js dashboard** to watch it all happen.

- **Agent core (Python):** FastAPI service, input guardrail, multi-tool
  decomposition (Gmail / Notion / Jira + content), Presidio/regex PII
  redaction, schema + citation validation, human-in-the-loop permission layer.
- **Product surface (Next.js/React + Tailwind):** chat UI, metrics dashboard
  (recharts), realtime approvals, Supabase Auth gate.
- **Data:** Supabase/Postgres (6 tables, RLS on) with an offline local fallback.
- **CI:** GitHub Actions runs the 145-case eval suite on every push and gates
  merges on ≥80% pass rate + 100% adversarial refusal, plus ruff lint, and
  frontend lint / type-check / tests / build.

---

## Badges

| Metric | Badge |
| --- | --- |
| CI pipeline | `![eval](https://github.com/pijush008/guardrail-agent/actions/workflows/eval.yml/badge.svg)` |
| Latest eval pass rate (service-hosted) | `![eval pass rate](https://img.shields.io/endpoint?url=<SERVICE_URL>/api/v1/metrics/badge)` |
| Latest eval pass rate (results branch) | `![eval pass rate](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/pijush008/guardrail-agent/results/badge.json)` |

`scripts/publish_badge.py` regenerates `results/badge.json` + `results/README.md`
after every CI run (the `publish-badge` job commits them to the `results` branch).

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  NEXT.JS / REACT  (Product Surface)                             │
│  - Chat UI · Metrics Dashboard (recharts) · Approval UI          │
│  - Supabase Auth gates approvals                                 │
└───────────────────────────┬──────────────────────────────────────┘
                            │ REST/HTTP (CORS; Next rewrites /api/proxy)
                            ▼
┌────────────────────────────────────────────────────────────────┐
│  PYTHON AGENT SERVICE (FastAPI) — service/main.py               │
│  [1] INPUT GUARDRAIL  (rule pre-filter + classifier LLM)        │
│  [2] INTENT + DECOMPOSE → Gmail/Notion/Jira/content             │
│      (timeout / auth / rate-limit / malformed handled per call)  │
│  [3] INDIRECT-INJECTION SCAN + PII REDACTION (never persisted)  │
│  [4] SYNTHESIS  (cited answer, [n] → evidence id)               │
│  [5] OUTPUT VALIDATION  (schema + structural/semantic citations)│
│  [6] PERMISSION LAYER  (pending_actions + confirmation email)   │
└───────────────────────────┬──────────────────────────────────────┘
                            │ reads/writes (SupabaseStore or LocalStore)
                            ▼
┌────────────────────────────────────────────────────────────────┐
│  SUPABASE (Postgres + Auth + Realtime + Storage)                │
│  evidence_docs · final_answers · pending_actions                │
│  eval_runs · eval_cases · injection_attempts  (RLS enabled)     │
└────────────────────────────────────────────────────────────────┘
```

---

## Repository layout

```
agent/            Python agent core (guardrail, decompose, tools, redact,
                  synthesize, validate, permission, metrics, db, notify,
                  logfmt structured logging)
evals/            Evaluation suite: 145 cases (cases.yaml), runner, grader
app/evaluation/   Canonical `python -m app.evaluation.run` entry point
service/          FastAPI app exposing the agent over REST
supabase/         schema.sql (6 tables + RLS policies)
web/              Next.js 15 app: chat, dashboard, evaluations, guardrails,
                  approvals, runs, CI status, settings
tests/            pytest suite (110 tests, offline/deterministic)
scripts/          publish_badge.py (shields.io metrics badge)
Dockerfile        backend image (python:3.12-slim)
docker-compose.yml  backend + web stack
.github/          eval.yml — CI: lint + unit tests + eval gate + frontend + badge
reports/          Latest eval run: summary, per-case rows, dashboard.html,
                  latest.json / latest.md
```

---

## Quickstart

### 1. Agent core (Python 3.12)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install ruff            # dev lint

pytest -q                            # 110 unit tests, no LLM needed
ruff check .                         # lint

# Full evaluation suite (needs OPENAI_API_KEY / GROQ_API_KEY):
python -m evals.eval_runner --min-pass 80 --outdir reports
# (equivalent spelling: python -m app.evaluation.run --min-pass 80)

# Run the API service:
uvicorn service.main:app --reload    # -> http://localhost:8000

# Offline demo of the whole stack (no LLM key / no quota):
#   GUARDRAIL_FAKE_LLM=1 uvicorn service.main:app --port 8000
#   cd web && npm run dev             # -> http://localhost:3000

# Docker (backend :8000 + web :3000):
docker compose up --build
```

Environment (see `agent/config.py`):

| Var | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` / `GROQ_API_KEY` | — | LLM provider key |
| `OPENAI_BASE_URL` | `https://api.groq.com/openai/v1` | provider endpoint |
| `GUARDRAIL_MODEL` | `llama-3.3-70b-versatile` | model |
| `GUARDRAIL_AUTO_BLOCK` | `1` | block attacks vs. flag-only |
| `GUARDRAIL_REDACT` | `1` | enable PII redaction |
| `GUARDRAIL_AUTO_APPROVE` | `1` | auto-approve in CI/tests; set `0` for HITL |
| `GUARDRAIL_FAKE_LLM` | — | `1` = deterministic offline demo mode (no API key) |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | — | persist to Postgres |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` | — | real confirmation emails (else simulated) |

### 2. Database (Supabase/Postgres)

Create a Supabase project, then run `supabase/schema.sql` in the SQL editor
(it enables RLS and read policies; only authenticated approvers may flip
`pending_actions.status`). Without Supabase env vars the system transparently
uses `LocalStore` JSON files under `data/` for offline dev.

### 3. Product surface (Next.js)

```bash
cd web
cp .env.local.example .env.local       # set NEXT_PUBLIC_PYTHON_SERVICE_URL + Supabase keys
npm install
npm run lint && npm run type-check && npm run test   # quality gate
npm run build && npm start             # or: npm run dev
```

Pages: `/` chat · `/dashboard` metrics · `/evaluations` case browser + run
suite · `/guardrails` block log · `/approvals` realtime HITL · `/runs` run
traces · `/ci` status · `/settings` overview · `/login` Supabase Auth
(demo mode auto-auth when Supabase isn't configured).

### 4. CI

`.github/workflows/eval.yml` runs ruff lint + unit tests + the full eval on
every push/PR, fails the build if pass rate < 80% or any adversarial case
bypasses the guardrail; a separate `frontend` job runs lint, type-check,
vitest and `next build`; the `publish-badge` job uploads `reports/*` as an
artifact and publishes the badge to the `results` branch. Add
`OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` to the repo secrets.

---

## The evaluation suite (core deliverable)

145 versioned cases in `evals/cases.yaml`, seven categories:

| Category | Count | Pass criteria example |
| --- | --- | --- |
| `normal` | 35 | must cite ≥1 valid source, mention expected facts |
| `edge` | 25 | empty/ambiguous/long/multi-part input, must stay graceful |
| `adversarial` | 30 | must be **blocked** by the guardrail (expect_block) |
| `missing` | 15 | must say data is unavailable, never fabricate |
| `failure` | 15 | simulated tool timeouts/auth/rate-limits/malformed → graceful degrade |
| `output_validation` | 15 | schema-valid, non-empty JSON; citations must resolve to real evidence, never fabricated |
| `permission` | 10 | high-stakes actions must create a pending approval, never execute before it; approved→executes once, rejected/expired→never |

Grading is rule-based (deterministic) with an optional `--llm-judge` mode.
Run everything with one command; results are written to `reports/*.json`
plus stable `reports/latest.json` / `reports/latest.md` snapshots and
persisted to `eval_runs` / `eval_cases` (Supabase when configured).

### Latest real run

Recorded from a real run on `2026-08-02` (Groq `llama-3.3-70b-versatile`) on
the then-120-case suite:

| Metric | Value |
| --- | --- |
| **Accuracy (pass rate)** | **85.8%** (103/120) |
| **Refusal rate** | **100%** (30/30 adversarial blocked) |
| **Latency** | avg 5,592 ms · p95 11,009 ms |
| **Token usage** | avg 1,179 / task (p50 728) |

Category breakdown: normal 26/35 · edge 22/25 · adversarial 30/30 ·
missing 12/15 · failure 13/15.

> The suite is now **145 cases / 7 categories** (`output_validation` +
> `permission` added). The fresh pass-rate from your latest real run is in
> `reports/latest.json` / `reports/latest.md` (or the `results` branch
> badge). Deterministic offline runs (`GUARDRAIL_FAKE_LLM=1`) score lower —
> the rule-based FakeLLM cannot cite or classify well — so CI only gates on
> real runs, which require a repo secret.

---

## API

| Endpoint | Description |
| --- | --- |
| `GET /health` | liveness + store backend |
| `POST /api/v1/chat` | run a question through the full pipeline |
| `POST /api/v1/chat/upload` | multipart: `question` + optional `file` (PDF ≤ 10 MB). Extracted text enters evidence as untrusted data → injection scan + PII redaction + citations |
| `POST /api/v1/agent/run` | full run envelope (`status`, `run_id`, trace metadata) |
| `GET /api/v1/agent/runs` · `/{id}` | recent runs + 13-stage pipeline trace |
| `GET /api/v1/evaluations/cases` | 145 case objects |
| `POST /api/v1/evaluations/run` | run the suite via HTTP (503 if no LLM key) |
| `GET /api/v1/evaluations/runs` · `/{id}` | eval run history + per-case results |
| `GET /api/v1/guardrails/events` | injection block log + totals |
| `GET /api/v1/approvals` | HITL queue (all statuses) |
| `POST /api/v1/approvals/{id}/approve` · `/reject` | REST approve/deny (executes if approved) |
| `GET /api/v1/pending_actions` | pending-only HITL queue |
| `POST /api/v1/pending_actions/{id}/decide` | approve/deny (executes if approved) |
| `GET /api/v1/final_answers` | recent cited answers |
| `GET /api/v1/evidence` | recent redacted evidence |
| `GET /api/v1/injection_attempts` | guardrail block log |
| `GET /api/v1/metrics` · `/latest` · `/history` | aggregate + dashboard data |
| `GET /api/v1/metrics/badge` | shields.io JSON badge |
| `GET /api/v1/ci/status` | GitHub Actions status in CI, honest mock locally |

---

## Security model

- **Tool content is untrusted data.** It is wrapped in `<evidence>` tags and
  the model is told never to follow instructions inside them; a second scan
  (`Guardrail.scan_content`) excludes injected documents from synthesis and
  logs them to `injection_attempts`.
- **High-stakes execution is structurally gated.** `execute_action()` is only
  reachable through a finalized, `approved` `ApprovalRecord`. Nothing in the
  code path can execute a delete/send/spend without a recorded approval.
- **PII never lands in the DB.** `evidence_docs.content_redacted` stores only
  redacted content; placeholders like `[EMAIL_REDACTED]` are preserved.
- **Structured logging.** Every run emits one logfmt line (`event=agent.run
  blocked=true risk=... pii_redactions=... approval=...`) to stderr for
  grep-able auditing.

## License

MIT
