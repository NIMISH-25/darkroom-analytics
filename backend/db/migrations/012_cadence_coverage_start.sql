-- Verified zero requires coverage that starts on or before the month start (ruling 4 / amendment rule).
-- ------------------------------------------------------------------ retainer_cadence (ruling 4)
-- One point for every complete month (relative to the cutoff) in which a contract is effective for any day.
-- expected_posts = posts_per_month x share x effective days / days in month. posts / attainment_pct are NULL
-- unless the brand weekly video coverage is gap-free and spans the whole month (start <= month start, through >= month end); a verified zero is posts 0, attainment 0.
create or replace view gold.retainer_cadence as
with cut as (
  select coalesce(nullif(current_setting('app.cutoff', true), '')::date, (select as_of from gold.current_as_of)) as d
),
months as (
  select g::date as month_start, (g + interval '1 month - 1 day')::date as month_end,
         extract(day from (g + interval '1 month - 1 day'))::int as dim
  from cut c,
       generate_series(
         date_trunc('month', least((select min(effective_from) from silver.contract),
                                   (select min(paid_local_date) from gold.mv_sales_line))::timestamp),
         date_trunc('month', c.d::timestamp), interval '1 month') g
  where (g + interval '1 month - 1 day')::date <= c.d
),
k as (
  select c.contract_id, c.creator_id, c.posts_per_month, c.monthly_retainer, c.effective_from, c.effective_to,
         al.brand_id, al.share
  from silver.contract c join silver.contract_allocation al using (contract_id)
  where c.posts_per_month is not null
),
kk as (
  select k.*, m.month_start, m.month_end, m.dim,
         greatest(0, least(coalesce(k.effective_to, m.month_end), m.month_end)
                     - greatest(coalesce(k.effective_from, m.month_start), m.month_start) + 1) as days
  from k cross join months m
),
vc as (select brand_id, coverage_start, coverage_through, n_gaps from gold.source_freshness where source_type = 'videos_weekly'),
pc as (
  select v.brand_id, v.creator_id, v.month, count(*) posts
  from gold.mv_video_activity v, cut c
  where v.qualifies and v.published_local_date <= c.d
  group by v.brand_id, v.creator_id, v.month
)
select kk.brand_id, kk.creator_id, cr.handle, kk.month_start as month,
       case when kk.share is not null then round(kk.posts_per_month * kk.share * kk.days / kk.dim, 2) end as expected_posts,
       case when vc.n_gaps = 0 and vc.coverage_start <= kk.month_start and vc.coverage_through >= kk.month_end then coalesce(pc.posts, 0) end as posts,
       case when vc.n_gaps = 0 and vc.coverage_start <= kk.month_start and vc.coverage_through >= kk.month_end
                 and kk.share is not null and kk.posts_per_month * kk.share * kk.days > 0
            then round(100.0 * coalesce(pc.posts, 0) / (kk.posts_per_month * kk.share * kk.days / kk.dim), 0) end as attainment_pct,
       case when kk.share is not null and kk.monthly_retainer is not null
            then round(kk.monthly_retainer * kk.share * kk.days / kk.dim, 2) end as retainer_allocated,
       vc.n_gaps, vc.coverage_through
from kk
left join vc on vc.brand_id = kk.brand_id
left join pc on pc.brand_id = kk.brand_id and pc.creator_id = kk.creator_id and pc.month = kk.month_start
left join silver.creator cr on cr.creator_id = kk.creator_id
where kk.days > 0;
