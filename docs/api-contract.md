# API contract - FROZEN

Base: `http://localhost:8000/api/v1`. JSON, snake_case, no trailing slashes. Money/decimals are STRINGS; counts are numbers; unknown = `null`; dates `YYYY-MM-DD`; datetimes ISO-8601 with offset. Errors `{"detail": ...}`. No pagination. All routes are GET + Bearer token except `/healthz` (at root, `GET /healthz`) and `POST /api/v1/auth/token`. Data routes accept `month=YYYY-MM` (default 2026-10) and `cutoff=YYYY-MM-DD` (default 2026-10-15) and return `data_revision`.

## Auth
`POST /api/v1/auth/token` form-encoded `username`,`password` -> `{"access_token","token_type":"bearer","expires_at"}`; HS256 JWT, 8h. Demo user `demo` / `darkroom-demo` (from env `DEMO_USERNAME`/`DEMO_PASSWORD`). `GET /auth/me` -> `{"username"}`. Wrong credentials -> 401. UI stores the token in `localStorage["darkroom_auth"]`, sends `Authorization: Bearer`, on 401 clears it and goes to `/login`. Login page has a "Use demo account" one-click button.

## MetricValue envelope (MV)
`{"metric_key","value"(string|number|null),"unit"("USD"|"count"|"ratio"|"days"|"USD_per_day"|"count_per_day"),"as_of","coverage_through"(date|null),"status"("current"|"partial"|"stale"|"unavailable"),"status_reason"(string|null),"evidence_url"(string, API-relative, opaque)}`. `*` below means MV; `?` nullable.

## Endpoints
- `GET /healthz` -> `{status}`
- `GET /api/v1/meta` -> `{default_month, default_cutoff, months[], brands[{brand_id,name,timezone}], data_revision}`
- `GET /api/v1/overview` -> `{data_revision, brands[{brand_id,name,goals[{goal_id,label,definition,scope,basis,target*,actual*,projection*,required_pace*?,pace_status("on_track"|"at_risk"|"off_track"|"unknown"),reasoning(string)}]}]}`
- `GET /api/v1/brands/{brand_id}/creators?q&contract_type&status&sort(handle|videos|gmv|net_sales|sales_after_costs|last_post_date)&order(asc|desc)` (nulls last) -> `{data_revision, contract_types[], items[{creator_id,handle,contract_type,last_post_date?,coverage_status,videos*,gmv*,refunds*,net_sales*,retainer_cost*,commission_cost*,sample_cost*,sales_after_costs*,unresolved_gmv*}]}`
- `GET /api/v1/brands/{brand_id}/samples?status&creator_id` -> `{data_revision, counts{sent*,delivered*,matched*,pending*,no_video*,unknown*,conversion_rate*}, items[{sample_id,creator_id,handle,product_sku,sent_date,delivered_date?,status("in_transit"|"pending"|"matched"|"no_video"|"unknown"),video_id?,delivery_to_video_days?,evidence_url}]}`
- `GET /api/v1/metrics/{metric_key}/evidence?{same filters as the metric: brand_id, creator_id, month, cutoff...}&revision=N` -> `{label,definition,definition_version,period_start,period_end,timezone,result*,calculation{kind("sum"|"distinct_count"|"ratio"|"forecast"|"goal"),formula,inputs[{label,value,unit}]},exclusions[{reason,count,amount}],warnings[],columns[],records[{source_file,source_locator,included,values{}}],records_truncated}`. If `revision` differs from current -> `409 {"detail":{"code":"refresh_required","current_revision":N}}`. `evidence_url` values in MVs are complete relative URLs of this route.
- `GET /api/v1/data-health?brand_id` -> `{data_revision, sources[{brand_id,source,status,coverage_through?,last_ingested_at?,message?}], runs[{run_id,started_at,status,files_failed}], failed_files[{run_id,file_name,error}], unresolved_identities[{brand_id,source,raw_identifier,occurrences}]}`
- `GET /api/v1/attention?brand_id&kind&followup_days` -> `{data_revision, items[{item_id,kind("quiet_retainer"|"sample_no_video"|"missing_source"),brand_id,title,rule,period_start,period_end,evidence_url}]}`

metric_keys for evidence: `gmv`, `creator_attributed_gmv`, `net_attributed_sales`, `videos`, `active_creators`, `goal_projection`, `creator_videos`, `creator_net_sales`, `sample_conversion_rate`, `creator_sales_after_costs`.

## Config
API env: `DATABASE_URL` (default `postgresql://darkroom:darkroom@localhost:5432/darkroom`), `CORS_ORIGINS` (a plain comma-separated STRING `http://localhost:3000,http://127.0.0.1:3000`; do not type as a list), `AUTH_SECRET`, `AUTH_TOKEN_TTL_MINUTES=480`, `DEMO_USERNAME=demo`, `DEMO_PASSWORD=darkroom-demo`, `PORT=8000`. CORS: GET/POST, headers Authorization+Content-Type, no credentials. Requires `python-multipart`, `tzdata`.
Web env: `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`, `NEXT_PUBLIC_DEMO_USERNAME=demo`, `NEXT_PUBLIC_DEMO_PASSWORD=darkroom-demo`, `NEXT_PUBLIC_USE_MOCKS` (true -> render from local mock JSON built from these shapes). Port 3000.

## Screens (ui worker)
Login; Overview (5 brands x 3 goals, actual, projection, reasoning, freshness badge, Needs-attention strip); Brand creators table (search, filter, sort, per-row freshness, evidence links); Samples (counts + items); Data health; a reusable Evidence drawer opened from ANY MV (shows definition, formula, inputs, exclusions, warnings, records with source_file/source_locator; handles 409 refresh_required by refetching). Null value renders as "Unknown" with the status reason, never `0`.

> Amendment 2 (remediation wave): see docs/api-contract-amendment-2.md. It wins where it differs.
