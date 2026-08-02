-- =====================================================================
-- Guardrail Agent — Supabase/Postgres schema
-- Run in the Supabase SQL editor, or: supabase db push
-- =====================================================================

create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- ---------------------------------------------------------------------
-- evidence_docs : one row per retrieved tool document (REDACTED only)
-- ---------------------------------------------------------------------
create table if not exists evidence_docs (
  id uuid primary key default gen_random_uuid(),
  source text not null,                -- 'gmail' | 'notion' | 'jira' | ...
  content_redacted text not null,      -- never persist unredacted PII
  run_id uuid,
  retrieved_at timestamptz default now()
);

-- ---------------------------------------------------------------------
-- final_answers : cited answers produced by the agent
-- ---------------------------------------------------------------------
create table if not exists final_answers (
  id uuid primary key default gen_random_uuid(),
  question text not null,
  answer text not null,
  citations jsonb not null,            -- [{id, source}, ...]
  run_id uuid,
  created_at timestamptz default now()
);

-- ---------------------------------------------------------------------
-- pending_actions : human-in-the-loop gate for high-stakes actions
-- ---------------------------------------------------------------------
create table if not exists pending_actions (
  id uuid primary key default gen_random_uuid(),
  plan text not null,
  status text not null default 'pending',  -- pending | approved | denied
  created_at timestamptz default now(),
  decided_at timestamptz,
  decided_by uuid references auth.users(id)
);

-- ---------------------------------------------------------------------
-- eval_runs : one row per evaluation-suite execution
-- ---------------------------------------------------------------------
create table if not exists eval_runs (
  id uuid primary key default gen_random_uuid(),
  accuracy numeric,
  refusal_rate numeric,
  avg_latency_ms numeric,
  avg_tokens numeric,
  created_at timestamptz default now()
);

-- ---------------------------------------------------------------------
-- eval_cases : one row per test case within a run
-- ---------------------------------------------------------------------
create table if not exists eval_cases (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references eval_runs(id),
  category text not null,              -- normal | edge | adversarial | missing | failure
  input text not null,
  passed boolean not null,
  latency_ms numeric,
  tokens numeric
);

-- ---------------------------------------------------------------------
-- injection_attempts : guardrail block log (metric: "blocked X/Y")
-- ---------------------------------------------------------------------
create table if not exists injection_attempts (
  id uuid primary key default gen_random_uuid(),
  input text not null,
  blocked boolean not null,
  created_at timestamptz default now()
);

-- =====================================================================
-- Row Level Security
-- =====================================================================
alter table evidence_docs      enable row level security;
alter table final_answers      enable row level security;
alter table pending_actions    enable row level security;
alter table eval_runs          enable row level security;
alter table eval_cases         enable row level security;
alter table injection_attempts enable row level security;

-- Anyone (authenticated or anonymous) can READ the audit/metrics tables;
-- the dashboard is public-read, write is restricted to the service role.
create policy "evidence_docs public read" on evidence_docs
  for select using (true);
create policy "final_answers public read" on final_answers
  for select using (true);
create policy "eval_runs public read" on eval_runs
  for select using (true);
create policy "eval_cases public read" on eval_cases
  for select using (true);
create policy "injection_attempts public read" on injection_attempts
  for select using (true);

-- Pending actions: authenticated approvers may READ the queue...
create policy "pending_actions auth read" on pending_actions
  for select to authenticated using (true);

-- ...and only authenticated approvers may UPDATE status (approve/deny).
create policy "pending_actions approver update" on pending_actions
  for update to authenticated
  using (status = 'pending')          -- can only change undecided rows
  with check (status in ('approved', 'denied'));

-- Server-side writes (service_role key bypasses RLS; anon is blocked).
-- The FastAPI service writes via the service role key. If you prefer to
-- gate writes to authenticated users only, replace the role below.
