-- Creator notes: app schema, survives Silver rebuilds and reset (reset --purge-notes drops it).
create schema if not exists app;
create table if not exists app.creator_note (
  note_id    bigint generated always as identity primary key,
  brand_id   text not null,
  creator_id text not null,
  body       text not null,
  author     text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);
create index if not exists ix_creator_note_lookup
  on app.creator_note (brand_id, creator_id, created_at desc) where deleted_at is null;
