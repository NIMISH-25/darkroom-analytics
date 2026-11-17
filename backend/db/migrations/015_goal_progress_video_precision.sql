-- Video projections keep 4 decimals (GMV stays at cents).
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
              case when ga.n is null then 0   -- covered days, no eligible lines: verified zero
                   when ga.n = ga.nv then ga.sm end
         when g3.metric_key = 'videos' then coalesce(va.n, 0)
         when g3.metric_key = 'active_creators' then coalesce(va.nc, 0)
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

