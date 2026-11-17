-- Schemas, bronze (raw, append-only) and meta tables.
create schema if not exists bronze;
create schema if not exists silver;
create schema if not exists gold;
create schema if not exists meta;

create table meta.source_contract (
  source_type text primary key,
  kind        text not null check (kind in ('increment','snapshot')),
  cadence     text not null check (cadence in ('daily','weekly','snapshot')),
  lag_days    int  not null
);
-- expected_through = last period_end with period_end + lag_days <= as_of
insert into meta.source_contract values
  ('orders','increment','daily',1),
  ('affiliate_orders','increment','daily',1),
  ('returns','increment','daily',1),
  ('videos_weekly','increment','weekly',1),
  ('products','snapshot','snapshot',60),
  ('roster','snapshot','snapshot',45),
  ('samples','snapshot','snapshot',45),
  ('plans','snapshot','snapshot',60);

create table meta.ingest_run (
  run_id       bigserial primary key,
  batch_id     text not null,
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  status       text not null check (status in ('running','succeeded','partial','failed')),
  files_failed int not null default 0,
  counts       jsonb
);

create table bronze.source_file (
  source_file_id bigserial primary key,
  batch_id       text not null,
  run_id         bigint,
  path           text,
  source_type    text not null,
  scope_key      text not null,
  coverage_start date,
  coverage_end   date,
  kind           text not null check (kind in ('increment','snapshot')),
  sha256         text not null,
  parser_version text not null,
  status         text not null check (status in ('accepted','quarantined','rejected')),
  error          text,
  row_count      int,
  ingested_at    timestamptz not null default now(),
  src_updated_at timestamptz,
  unique nulls not distinct (source_type, scope_key, coverage_start, coverage_end, sha256, parser_version)
);
create index on bronze.source_file (source_type, scope_key, status);

create table bronze.source_record (
  source_file_id bigint not null references bronze.source_file,
  row_num        int not null,
  payload        jsonb not null,
  row_hash       text not null,
  primary key (source_file_id, row_num)
);

create table meta.dataset_revision (
  revision_id bigserial primary key,
  as_of       date not null,
  created_at  timestamptz not null default now(),
  summary     jsonb not null
);

create table meta.quality_issue (
  issue_id       bigserial primary key,
  code           text not null,
  entity_ref     text not null,
  source_file_id bigint,
  row_num        int,
  brand_id       text,
  source_type    text,
  severity       text not null check (severity in ('info','warn','suspect','error')),
  state          text not null default 'open' check (state in ('open','resolved')),
  message        text,
  origin         text not null check (origin in ('file','silver')),
  created_at     timestamptz not null default now()
);
create index on meta.quality_issue (origin, code);
