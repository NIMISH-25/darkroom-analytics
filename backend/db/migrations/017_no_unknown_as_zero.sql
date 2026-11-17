-- Unknown is NULL, never zero (CLAUDE.md; db-contract rule 7): a zero is emitted only where the relevant source
-- coverage is complete for the period counted. gold.source_month_complete says, per brand/source/month, whether the
-- source is current/suspect, covers the month start, and reaches min(month end, expected_through).
create or replace view gold.source_month_complete as
with asof as (select as_of from gold.current_as_of),
months as (
  select g::date as month_start, (g + interval '1 month - 1 day')::date as month_end
  from asof a,
       generate_series(date_trunc('month', least((select min(paid_local_date) from gold.mv_sales_line),
                                                 (select min(effective_from) from silver.contract))::timestamp),
                       date_trunc('month', a.as_of::timestamp), interval '1 month') g
)
select f.brand_id, f.source_type, m.month_start as month,
       (f.state in ('current', 'suspect')
        and (f.coverage_start is null or f.coverage_start <= m.month_start)
        and f.coverage_through >= least(m.month_end, f.expected_through)) as complete
from gold.source_freshness f cross join months m;

create or replace view gold.creator_performance as
with asof as (select as_of from gold.current_as_of),
months as (
  select m::date as m
  from asof,
       generate_series(
         (select date_trunc('month', min(paid_local_date)::timestamp) from gold.sales_line),
         date_trunc('month', asof.as_of::timestamp), interval '1 month') m
),
sl as (
  select s.* from gold.sales_line s cross join asof a
  where s.eligible and s.bucket = 'resolved' and s.paid_local_date <= a.as_of
),
u as (
  select brand_id, creator_id, month from sl
  union
  select v.brand_id, v.creator_id, v.month from gold.video_activity v cross join asof a
   where v.qualifies and v.published_local_date <= a.as_of
  union
  select bc.brand_id, bc.creator_id, mo.m
  from silver.brand_creator bc cross join months mo
  where bc.roster_active
    and (bc.effective_from is null or date_trunc('month', bc.effective_from::timestamp)::date <= mo.m)
    and (bc.effective_to is null or bc.effective_to >= mo.m)
  union
  select brand_id, creator_id, month from gold.sample_cost_line where creator_id is not null
),
vids as (
  select v.brand_id, v.creator_id, v.month, count(*)::int videos
  from gold.video_activity v cross join asof a
  where v.qualifies and v.published_local_date <= a.as_of
  group by 1, 2, 3
),
lastpost as (
  select v.brand_id, v.creator_id, max(v.published_local_date) last_post_date
  from gold.video_activity v cross join asof a
  where v.qualifies and v.published_local_date <= a.as_of
  group by 1, 2
),
sales as (
  select brand_id, creator_id, month, count(*) n,
         case when count(*) = count(gmv) then sum(gmv) end gmv,
         case when count(*) = count(refunded) then sum(refunded) end refunds,
         case when count(*) = count(net) then sum(net) end net_sales,
         count(*) filter (where refund_state = 'partial')::int unknown_refund_lines,
         count(*) filter (where not video_known) n_nv,
         count(gmv) filter (where not video_known) n_nv_gmv,
         sum(gmv) filter (where not video_known) nv_gmv
  from sl group by 1, 2, 3
),
comm as (
  select cl.brand_id, cl.creator_id, cl.month, count(*) n,
         case when count(*) = count(cl.amount) then sum(cl.amount) end amount,
         case when count(*) filter (where cl.status = 'pending') = count(cl.amount) filter (where cl.status = 'pending')
              then coalesce(sum(cl.amount) filter (where cl.status = 'pending'), 0) end pending,
         case when count(*) filter (where cl.status = 'settled') = count(cl.amount) filter (where cl.status = 'settled')
              then coalesce(sum(cl.amount) filter (where cl.status = 'settled'), 0) end settled
  from gold.commission_line cl cross join asof a
  where cl.paid_local_date <= a.as_of
  group by 1, 2, 3
),
ret as (
  select ca.brand_id, c.creator_id, mo.m as month, count(*) n,
         case when count(*) = count(
              case when ca.share is null or c.monthly_retainer is null then null
                   else round(c.monthly_retainer * ca.share
                     * greatest(0, least(coalesce(c.effective_to, (mo.m + interval '1 month - 1 day')::date),
                                         (mo.m + interval '1 month - 1 day')::date)
                                   - greatest(coalesce(c.effective_from, mo.m), mo.m) + 1)
                     / extract(day from (mo.m + interval '1 month - 1 day'))::int, 2) end)
              then sum(
              case when ca.share is null or c.monthly_retainer is null then null
                   else round(c.monthly_retainer * ca.share
                     * greatest(0, least(coalesce(c.effective_to, (mo.m + interval '1 month - 1 day')::date),
                                         (mo.m + interval '1 month - 1 day')::date)
                                   - greatest(coalesce(c.effective_from, mo.m), mo.m) + 1)
                     / extract(day from (mo.m + interval '1 month - 1 day'))::int, 2) end)
         end amount
  from silver.contract c
  join silver.contract_allocation ca on ca.contract_id = c.contract_id
  cross join months mo
  group by 1, 2, 3
),
samp as (
  select brand_id, creator_id, month, count(*) n,
         case when count(*) = count(cost) then sum(cost) end amount
  from gold.sample_cost_line cl cross join asof a
  where creator_id is not null and shipped_at <= a.as_of
  group by 1, 2, 3
),
r as (
  select u.brand_id, u.creator_id, u.month,
         bc.contract_type, coalesce(bc.roster_active, false) as roster_active,
         coalesce(bc.handle, cr.handle) as handle,
         case when vids.videos is not null then vids.videos when cmv.complete then 0 end as videos,
         lp.last_post_date,
         case when sales.n is not null then sales.gmv when cmo.complete and cma.complete then 0 end as gmv,
         case when sales.n is not null then sales.refunds when cmo.complete and cma.complete and cmr.complete then 0 end as refunds,
         case when sales.n is not null then sales.net_sales when cmo.complete and cma.complete and cmr.complete then 0 end as net_sales,
         coalesce(sales.unknown_refund_lines, 0) as unknown_refund_lines,
         case when coalesce(sales.n_nv, 0) = 0 then (case when cmo.complete and cma.complete then 0 end)
              when sales.n_nv = sales.n_nv_gmv then sales.nv_gmv end as unresolved_gmv,
         case when ret.n is not null then ret.amount
              when bc.contract_type = 'affiliate' then 0 end as retainer_cost,
         case when comm.n is not null then comm.amount when cma.complete then 0 end as commission_cost,
         case when comm.n is not null then comm.pending when cma.complete then 0 end as commission_pending,
         case when comm.n is not null then comm.settled when cma.complete then 0 end as commission_settled,
         case when samp.n is not null then samp.amount when cms.complete then 0 end as sample_cost
  from u
  left join silver.brand_creator bc on bc.brand_id = u.brand_id and bc.creator_id = u.creator_id
  left join silver.creator cr on cr.creator_id = u.creator_id
  left join vids on (vids.brand_id, vids.creator_id, vids.month) = (u.brand_id, u.creator_id, u.month)
  left join lastpost lp on lp.brand_id = u.brand_id and lp.creator_id = u.creator_id
  left join sales on (sales.brand_id, sales.creator_id, sales.month) = (u.brand_id, u.creator_id, u.month)
  left join comm on (comm.brand_id, comm.creator_id, comm.month) = (u.brand_id, u.creator_id, u.month)
  left join ret on (ret.brand_id, ret.creator_id, ret.month) = (u.brand_id, u.creator_id, u.month)
  left join samp on (samp.brand_id, samp.creator_id, samp.month) = (u.brand_id, u.creator_id, u.month)
  left join gold.source_month_complete cmo on (cmo.brand_id, cmo.month, cmo.source_type) = (u.brand_id, u.month, 'orders')
  left join gold.source_month_complete cma on (cma.brand_id, cma.month, cma.source_type) = (u.brand_id, u.month, 'affiliate_orders')
  left join gold.source_month_complete cmr on (cmr.brand_id, cmr.month, cmr.source_type) = (u.brand_id, u.month, 'returns')
  left join gold.source_month_complete cmv on (cmv.brand_id, cmv.month, cmv.source_type) = (u.brand_id, u.month, 'videos_weekly')
  left join gold.source_month_complete cms on (cms.brand_id, cms.month, cms.source_type) = (u.brand_id, u.month, 'samples')
)
select r.*,
       (select case f.state when 'current' then 'current' when 'suspect' then 'current' when 'stale' then 'stale'
                            when 'incomplete' then 'partial' else 'unavailable' end
          from gold.source_freshness f where f.brand_id = r.brand_id and f.source_type = 'videos_weekly') as coverage_status,
       case when r.net_sales is null or r.retainer_cost is null or r.commission_cost is null or r.sample_cost is null
            then null
            else r.net_sales - r.retainer_cost - r.commission_cost - r.sample_cost end as sales_after_costs
from r;

-- Evaluate the actual/curve subqueries once per goal (not once per output column).
create or replace view gold.goal_progress as
with asof as (
  select coalesce(nullif(current_setting('app.cutoff', true), '')::date, (select as_of from gold.current_as_of)) as as_of
),
g0 as (
  select g.*, a.as_of,
         g.month as month_start,
         (g.month + interval '1 month - 1 day')::date as month_end,
         extract(day from (g.month + interval '1 month - 1 day'))::int as days_in_month,
         case when g.metric_key = 'gmv'
              then array['orders']
                   || case when g.scope = 'creator_attributed' then array['affiliate_orders'] else array[]::text[] end
                   || case when g.basis = 'net' then array['returns'] else array[]::text[] end
              else array['videos_weekly'] end as sources
  from silver.goal g cross join asof a
  where g.active
),
g1 as (
  select g0.*,
         (select max(f.state_rank) from gold.source_freshness f
           where f.brand_id = g0.brand_id and f.source_type = any (g0.sources)) as worst_rank,
         (select min(f.coverage_through) from gold.source_freshness f
           where f.brand_id = g0.brand_id and f.source_type = any (g0.sources)) as coverage_through,
         (select bool_or(f.coverage_through is null) from gold.source_freshness f
           where f.brand_id = g0.brand_id and f.source_type = any (g0.sources)) as any_null_cov,
         (select string_agg(f.source_type || ':' || f.state, ', ' order by f.source_type)
            from gold.source_freshness f
           where f.brand_id = g0.brand_id and f.source_type = any (g0.sources)) as source_states
  from g0
),
g2 as (
  select g1.*,
         case g1.worst_rank when 5 then 'missing' when 4 then 'incomplete' when 3 then 'stale'
                            when 2 then 'suspect' when 1 then 'current' end as state,
         case when g1.any_null_cov or g1.coverage_through is null then null
              else least(g1.as_of, g1.month_end, g1.coverage_through) end as cutoff_date
  from g1
),
g3 as (
  select g2.*,
         case when g2.cutoff_date >= g2.month_start then (g2.cutoff_date - g2.month_start + 1) end as elapsed_days,
         (g2.state in ('missing', 'incomplete') or g2.cutoff_date is null or g2.cutoff_date < g2.month_start) as unusable
  from g2
),
gmv_a as materialized (
  select g3.brand_id, g3.month, g3.metric_key, g3.scope,
         count(*) n,
         count(case when g3.basis = 'net' then s.net else s.gmv end) nv,
         sum(case when g3.basis = 'net' then s.net else s.gmv end) sm
  from g3
  join gold.sales_line s on s.brand_id = g3.brand_id and s.eligible
       and s.paid_local_date between g3.month_start and g3.cutoff_date
       and (g3.scope <> 'creator_attributed' or s.bucket <> 'none')
  where g3.metric_key = 'gmv' and g3.elapsed_days is not null and g3.state <> 'missing'
  group by 1, 2, 3, 4
),
vid_a as materialized (
  select g3.brand_id, g3.month, g3.metric_key, g3.scope,
         count(*) n, count(distinct v.creator_id) nc
  from g3
  join gold.video_activity v on v.brand_id = g3.brand_id and v.qualifies
       and v.published_local_date between g3.month_start and g3.cutoff_date
  where g3.metric_key in ('videos', 'active_creators') and g3.elapsed_days is not null and g3.state <> 'missing'
  group by 1, 2, 3, 4
),
g4 as materialized (
  select g3.*,
    case when g3.elapsed_days is null or g3.state = 'missing' then null
         when g3.metric_key = 'gmv' then
              case when ga.n is null then (case when g3.state in ('current', 'suspect') then 0 end)   -- verified zero only under complete coverage
                   when ga.n = ga.nv then ga.sm end
         when g3.metric_key = 'videos' then (case when va.n is not null then va.n when g3.state in ('current', 'suspect') then 0 end)
         when g3.metric_key = 'active_creators' then (case when va.nc is not null then va.nc when g3.state in ('current', 'suspect') then 0 end)
    end as actual,
    case when g3.metric_key = 'active_creators' and g3.elapsed_days is not null then (
      select jsonb_build_object('n', count(*), 'median', percentile_cont(0.5) within group (order by q.frac))
      from (
        select pm.m,
               (count(distinct v.creator_id) filter (where v.published_local_date <= pm.m + (g3.elapsed_days - 1)))::numeric
                 / nullif(count(distinct v.creator_id), 0) as frac
        from (select gs::date as m from generate_series(g3.month_start - interval '12 months',
                                                         g3.month_start - interval '1 month', interval '1 month') gs) pm
        join gold.source_coverage vc on vc.brand_id = g3.brand_id and vc.source_type = 'videos_weekly'
             and vc.n_islands = 1 and vc.coverage_start <= pm.m
             and vc.coverage_through >= (pm.m + interval '1 month - 1 day')::date
        join gold.video_activity v on v.brand_id = g3.brand_id and v.qualifies and v.month = pm.m
        group by pm.m
        having count(distinct v.creator_id) > 0
      ) q) end as curve
  from g3
  left join gmv_a ga using (brand_id, month, metric_key, scope)
  left join vid_a va using (brand_id, month, metric_key, scope)
),
g5 as (
  select g4.*,
         (g4.curve ->> 'n')::int as curve_months,
         (g4.curve ->> 'median')::numeric as curve_median
  from g4
),
g6 as materialized (
  select g5.*,
         g5.days_in_month - g5.elapsed_days as remaining_days,
         case
           when g5.actual is null or g5.unusable then null
           when g5.metric_key = 'active_creators' then
                case when g5.cutoff_date >= g5.month_end then g5.actual
                     when g5.actual = 0 or g5.curve_months < 3 or coalesce(g5.curve_median, 0) <= 0 then null
                     else greatest(g5.actual, round(g5.actual / g5.curve_median)) end
           when g5.cutoff_date >= g5.month_end then g5.actual
           when g5.metric_key = 'gmv' then round(g5.actual / g5.elapsed_days * g5.days_in_month, 2)
           else round(g5.actual::numeric / g5.elapsed_days * g5.days_in_month, 4)
         end as projection
  from g5
)
select g6.brand_id, g6.month, g6.metric_key, g6.scope, g6.basis, g6.definition_version, g6.definition,
       g6.target_value, g6.as_of,
       g6.actual, g6.projection,
       case when g6.metric_key = 'active_creators' or g6.actual is null or g6.unusable
                 or g6.remaining_days <= 0 or g6.target_value is null then null
            else round(greatest(0, g6.target_value - g6.actual) / g6.remaining_days, 2) end as required_pace,
       case when g6.projection is null or g6.target_value is null then 'unknown'
            when g6.projection >= g6.target_value then 'on_track'
            when g6.projection >= 0.9 * g6.target_value then 'at_risk'
            else 'off_track' end as pace_status,
       g6.state, g6.coverage_through, g6.cutoff_date, g6.elapsed_days, g6.remaining_days,
       g6.days_in_month, g6.sources, g6.source_states,
       case when g6.actual is not null and g6.elapsed_days > 0 and g6.metric_key <> 'active_creators'
            then round(g6.actual::numeric / g6.elapsed_days, 4) end as daily_average,
       g6.curve_months, g6.curve_median,
       case when g6.state = 'missing' then 'Required source is missing'
            when g6.cutoff_date is null or g6.cutoff_date < g6.month_start then 'No covered days in this month'
            when g6.state = 'incomplete' then 'Source coverage has gaps or rejected/quarantined files'
            when g6.state = 'stale' then 'Data only through ' || g6.cutoff_date
       end as status_reason,
       g6.source_file_id, g6.row_num,
       g6.metric_key || ':' || g6.scope as goal_id,
       initcap(replace(g6.metric_key, '_', ' ')) || case g6.scope when 'shop' then ' (shop-wide' else ' (creator-attributed' end
         || ', ' || g6.basis || ')' as label,
       case when g6.projection is null then 'unavailable'
            else case g6.state when 'missing' then 'unavailable' when 'incomplete' then 'partial' when 'stale' then 'stale' else 'current' end
       end as status,
       case when g6.metric_key = 'active_creators' and g6.projection is null and g6.state in ('current','stale','suspect')
              and g6.actual is not null then 'Needs at least 3 complete prior months of history'
            else null end as status_reason_extra,
       case
         when g6.actual is null then 'Actual is unknown: ' || coalesce(
              case when g6.state = 'missing' then 'required source is missing'
                   else 'source coverage does not include this month' end, 'no coverage')
         when g6.metric_key = 'active_creators' then
              g6.actual || ' distinct creators with a qualifying video through ' || g6.cutoff_date
              || coalesce('; median completion share over ' || g6.curve_months || ' prior months = ' || round(g6.curve_median, 3)
                          || ', projection = actual / share = ' || g6.projection, '; projection unavailable (needs 3+ complete prior months)')
         else 'Actual ' || g6.actual || ' through ' || g6.cutoff_date || ' (' || g6.elapsed_days || ' of ' || g6.days_in_month
              || ' days). ' || case when g6.projection is null then 'Projection unavailable because source coverage is ' || g6.state || '.'
                   else 'Projection = actual / elapsed days x days in month = ' || g6.projection || '. Required pace = max(0, target - actual) / '
                        || g6.remaining_days || ' remaining days.' end
       end as reasoning
from g6;

create or replace view gold.chart_sample_funnel as
with f as (select * from gold.sample_funnel),
c as (
  select brand_id, 'sent'::text stage, null::text lag_bucket, count(*) n from f group by brand_id
  union all select brand_id, 'delivered', null, count(*) from f where delivered_date is not null group by brand_id
  union all select brand_id, 'mature', null, count(*) from f where mature group by brand_id
  union all select brand_id, 'in_transit', null, count(*) from f where state = 'in_transit' group by brand_id
  union all select brand_id, 'pending', null, count(*) from f where state = 'pending' group by brand_id
  union all select brand_id, 'converted', null, count(*) from f where state = 'matched' group by brand_id
  union all select brand_id, 'no_video_mature', null, count(*) from f where state = 'no_video' group by brand_id
  union all select brand_id, 'unknown', null, count(*) from f where state = 'unknown' group by brand_id
  union all
  select brand_id, 'converted',
         case when delivery_to_video_days <= 7 then '0-7' when delivery_to_video_days <= 14 then '8-14'
              when delivery_to_video_days <= 21 then '15-21' else '22-30' end, count(*)
  from f where state = 'matched' and delivery_to_video_days is not null group by 1, 3
),
grid(stage, lag_bucket) as (
  values ('sent', null), ('delivered', null), ('mature', null), ('in_transit', null), ('pending', null),
         ('converted', null), ('no_video_mature', null), ('unknown', null),
         ('converted', '0-7'), ('converted', '8-14'), ('converted', '15-21'), ('converted', '22-30')
)
select b.brand_id, g.stage, g.lag_bucket,
       case when c.n is not null then c.n::int when fr.state in ('current', 'suspect') then 0 end as count
from silver.brand b
cross join grid g
left join gold.source_freshness fr on fr.brand_id = b.brand_id and fr.source_type = 'samples'
left join c on c.brand_id = b.brand_id and c.stage = g.stage and c.lag_bucket is not distinct from g.lag_bucket;

-- mv_goal_progress is superseded by the plain, cutoff-aware gold.goal_progress; drop it and refresh the others.
drop materialized view if exists gold.mv_goal_progress;
create or replace function gold.refresh_materialized() returns void
language plpgsql as $$
begin
  refresh materialized view concurrently gold.mv_sales_line;
  refresh materialized view concurrently gold.mv_video_activity;
  refresh materialized view concurrently gold.mv_sample_funnel;
end;
$$;
select gold.refresh_materialized();
