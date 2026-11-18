-- Rulings 1, 2, 4.
--  * silver.shop_order.currency (original payment currency); non-USD orders are not eligible
--    (exclusion_reason = 'non_usd_currency'; paid_amount stays in the ORIGINAL currency, see sales_line.currency).
--  * creator ids that are not on the brand roster resolve to bucket 'creator_unresolved' (creator_id NULL,
--    creator_raw = the raw id / handle) and are listed in gold.unresolved_identity.
--  * retainer_cadence: months from the first contract/sales month, complete months relative to the request cutoff.
-- Cutoff for cutoff-aware views: session setting app.cutoff (YYYY-MM-DD), else the dataset as_of.
-- Materialized view mv_sales_line is recreated; dependents are dropped by cascade and recreated below in order.
alter table silver.shop_order add column if not exists currency text;

drop materialized view if exists gold.mv_sales_line cascade;

create materialized view gold.mv_sales_line as
with la as (
  select shop_id, order_id, line_id, count(*) n_rec,
         case when count(*) = 1 then max(creator_id) end creator_id,
         case when count(*) = 1 then max(creator_handle) end creator_handle,
         case when count(*) = 1 then max(video_id) end video_id,
         case when count(*) = 1 then max(content_type) end content_type,
         case when count(*) = 1 then max(affiliate_record_id) end affiliate_record_id,
         case when count(*) = 1 then max(source_file_id) end a_source_file_id,
         case when count(*) = 1 then max(row_num) end a_row_num
  from silver.attribution group by shop_id, order_id, line_id
),
base as (
  select b.brand_id, i.shop_id, i.order_id, i.line_id, i.product_id,
         o.paid_at, o.paid_local_date, date_trunc('month', o.paid_local_date::timestamp)::date as month,
         o.status order_status, i.item_status, i.is_sample, i.paid_amount, o.currency,
         (o.paid_at is not null and o.status not in ('UNPAID', 'CANCELLED')
          and not o.is_sample and not i.is_sample
          and (o.currency is null or o.currency = 'USD')
          and i.item_status is distinct from 'CANCELLED') as eligible,
         case when o.paid_at is null or o.status = 'UNPAID' then 'unpaid'
              when o.is_sample or i.is_sample then 'sample'
              when o.currency is not null and o.currency <> 'USD' then 'non_usd_currency'
              when o.status = 'CANCELLED' or i.item_status is not distinct from 'CANCELLED' then 'cancelled'
         end as exclusion_reason,
         la.n_rec, la.creator_id, la.creator_handle, la.video_id, la.content_type, la.affiliate_record_id,
         la.a_source_file_id, la.a_row_num,
         (la.creator_id is not null and exists (
            select 1 from silver.brand_creator bc where bc.brand_id = b.brand_id and bc.creator_id = la.creator_id)) as on_roster,
         i.source_file_id, i.row_num, sf.path as source_path
  from silver.order_item i
  join silver.shop_order o on o.shop_id = i.shop_id and o.order_id = i.order_id
  left join silver.brand b on b.shop_id = i.shop_id
  left join bronze.source_file sf on sf.source_file_id = i.source_file_id
  left join la on (la.shop_id, la.order_id, la.line_id) = (i.shop_id, i.order_id, i.line_id)
)
select base.brand_id, base.shop_id, base.order_id, base.line_id, base.product_id,
       base.paid_at, base.paid_local_date, base.paid_local_date as local_date, base.month,
       base.order_status, base.item_status, base.is_sample,
       base.paid_amount, base.eligible, base.exclusion_reason,
       case when base.eligible then base.paid_amount end as gmv,
       case when not base.eligible then null
            when base.n_rec is null then 'none'
            when base.n_rec > 1 then 'conflict'
            when not base.on_roster then 'creator_unresolved'
            else 'resolved' end as bucket,
       case when base.on_roster then base.creator_id end as creator_id,
       base.video_id, base.content_type, base.affiliate_record_id,
       (base.video_id is not null and exists (
          select 1 from silver.video v where v.brand_id = base.brand_id and v.video_id = base.video_id)) as video_known,
       base.source_file_id, base.row_num,
       base.source_path as source_file,
       'orders[' || base.row_num || '].line_items[id=' || base.line_id || ']' as source_locator,
       base.a_source_file_id as attribution_source_file_id, base.a_row_num as attribution_row_num,
       base.currency,
       case when base.n_rec = 1 then coalesce(base.creator_id, base.creator_handle) end as creator_raw
from base;
create unique index ux_mv_sales_line_key on gold.mv_sales_line (shop_id, order_id, line_id);
create index ix_mv_sales_line_brand_month on gold.mv_sales_line (brand_id, month, order_id, line_id);
create index ix_mv_sales_line_creator on gold.mv_sales_line (brand_id, creator_id, month);
create index ix_mv_sales_line_prov on gold.mv_sales_line (source_file_id, row_num);

create or replace view gold.sales_line as
with cut as (
  select coalesce(nullif(current_setting('app.cutoff', true), '')::date, (select as_of from gold.current_as_of)) as d
),
rf as (
  select r.shop_id, r.order_id, r.line_id,
         count(*) n_completed,
         count(*) filter (where r.merch_amount is null) n_unknown,
         sum(r.merch_amount) known_sum
  from silver.refund r cross join cut
  where r.status in ('completed', 'partial') and r.completed_local_date <= cut.d
  group by r.shop_id, r.order_id, r.line_id
)
select m.brand_id, m.shop_id, m.order_id, m.line_id, m.product_id,
       m.paid_at, m.paid_local_date, m.local_date, m.month, m.order_status, m.item_status, m.is_sample,
       m.paid_amount, m.eligible, m.exclusion_reason, m.gmv, m.bucket,
       m.creator_id, m.video_id, m.content_type, m.affiliate_record_id, m.video_known,
       case when not m.eligible then null
            when rf.n_unknown > 0 then null
            else coalesce(rf.known_sum, 0) end as refunded,
       case when not m.eligible then null
            when coalesce(rf.n_completed, 0) = 0 then 'none'
            when rf.n_unknown > 0 then 'partial'
            else 'complete' end as refund_state,
       case when m.eligible and coalesce(rf.n_unknown, 0) = 0
            then m.paid_amount - coalesce(rf.known_sum, 0) end as net,
       m.source_file_id, m.row_num, m.source_file, m.source_locator,
       m.attribution_source_file_id, m.attribution_row_num,
       m.currency, m.creator_raw
from gold.mv_sales_line m
left join rf on (rf.shop_id, rf.order_id, rf.line_id) = (m.shop_id, m.order_id, m.line_id);

create or replace view gold.refund_line as
select sl.brand_id, r.shop_id, r.refund_id, r.order_id, r.line_id, r.status,
       r.merch_amount, r.completed_at, r.completed_local_date,
       sl.month, sl.paid_local_date, sl.creator_id, sl.bucket, sl.eligible, sl.gmv,
       r.source_file_id, r.row_num
from silver.refund r
left join gold.sales_line sl
  on sl.shop_id = r.shop_id and sl.order_id = r.order_id and sl.line_id = r.line_id;

create or replace view gold.commission_line as
select sl.brand_id, sl.creator_id, sl.month, sl.paid_local_date, c.commission_id, c.affiliate_record_id,
       c.rate, c.amount, c.status, sl.order_id, sl.line_id, sl.gmv,
       c.source_file_id, c.row_num
from silver.commission c
join gold.sales_line sl
  on sl.shop_id = c.shop_id and sl.affiliate_record_id = c.affiliate_record_id
where sl.eligible and sl.bucket = 'resolved';

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
         coalesce(vids.videos, 0) as videos,
         lp.last_post_date,
         case when sales.n is null then 0 else sales.gmv end as gmv,
         case when sales.n is null then 0 else sales.refunds end as refunds,
         case when sales.n is null then 0 else sales.net_sales end as net_sales,
         coalesce(sales.unknown_refund_lines, 0) as unknown_refund_lines,
         case when coalesce(sales.n_nv, 0) = 0 then 0
              when sales.n_nv = sales.n_nv_gmv then sales.nv_gmv end as unresolved_gmv,
         case when ret.n is not null then ret.amount
              when bc.contract_type = 'affiliate' then 0 end as retainer_cost,
         case when comm.n is null then 0 else comm.amount end as commission_cost,
         case when comm.n is null then 0 else comm.pending end as commission_pending,
         case when comm.n is null then 0 else comm.settled end as commission_settled,
         case when samp.n is null then 0 else samp.amount end as sample_cost
  from u
  left join silver.brand_creator bc on bc.brand_id = u.brand_id and bc.creator_id = u.creator_id
  left join silver.creator cr on cr.creator_id = u.creator_id
  left join vids on (vids.brand_id, vids.creator_id, vids.month) = (u.brand_id, u.creator_id, u.month)
  left join lastpost lp on lp.brand_id = u.brand_id and lp.creator_id = u.creator_id
  left join sales on (sales.brand_id, sales.creator_id, sales.month) = (u.brand_id, u.creator_id, u.month)
  left join comm on (comm.brand_id, comm.creator_id, comm.month) = (u.brand_id, u.creator_id, u.month)
  left join ret on (ret.brand_id, ret.creator_id, ret.month) = (u.brand_id, u.creator_id, u.month)
  left join samp on (samp.brand_id, samp.creator_id, samp.month) = (u.brand_id, u.creator_id, u.month)
)
select r.*,
       (select case f.state when 'current' then 'current' when 'suspect' then 'current' when 'stale' then 'stale'
                            when 'incomplete' then 'partial' else 'unavailable' end
          from gold.source_freshness f where f.brand_id = r.brand_id and f.source_type = 'videos_weekly') as coverage_status,
       case when r.net_sales is null or r.retainer_cost is null or r.commission_cost is null or r.sample_cost is null
            then null
            else r.net_sales - r.retainer_cost - r.commission_cost - r.sample_cost end as sales_after_costs
from r;

create materialized view gold.mv_goal_progress as
with asof as (select as_of from gold.current_as_of),
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
           else round(g5.actual::numeric / g5.elapsed_days * g5.days_in_month, 2)
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

create unique index ux_mv_goal_progress_key on gold.mv_goal_progress (brand_id, month, metric_key, scope);
create or replace view gold.goal_progress as select * from gold.mv_goal_progress;

-- ---------------------------------------------------------------- refresh (dependency order)
-- CONCURRENTLY so readers are never blocked while the publish transaction refreshes.
create or replace function gold.refresh_materialized() returns void
language plpgsql as $$
begin
  refresh materialized view concurrently gold.mv_sales_line;
  refresh materialized view concurrently gold.mv_video_activity;
  refresh materialized view concurrently gold.mv_sample_funnel;
  refresh materialized view concurrently gold.mv_goal_progress;
end;
$$;

create or replace view gold.chart_daily as
with asof as (select as_of from gold.current_as_of),
cut as (
  select coalesce(nullif(current_setting('app.cutoff', true), '')::date, (select as_of from asof)) as d
),
days as (
  select b.brand_id, g::date as day
  from silver.brand b
  cross join lateral generate_series(
      (select date_trunc('month', min(paid_local_date)::timestamp) from gold.mv_sales_line),
      (select date_trunc('month', as_of::timestamp) + interval '1 month' - interval '1 day' from asof),
      interval '1 day') g
),
cov as (
  select brand_id,
         max(coverage_through) filter (where source_type = 'orders') as c_orders,
         max(coverage_through) filter (where source_type = 'affiliate_orders') as c_aff,
         max(coverage_through) filter (where source_type = 'returns') as c_ret,
         max(state_rank) filter (where source_type in ('orders', 'affiliate_orders', 'returns')) as worst_rank,
         bool_and(state in ('current', 'suspect')) filter (where source_type = 'returns') as ret_ok
  from gold.source_freshness group by brand_id
),
s as (
  select brand_id, local_date as day,
         count(*) n, count(gmv) n_gmv, sum(gmv) gmv,
         count(*) filter (where bucket <> 'none') na,
         count(gmv) filter (where bucket <> 'none') na_gmv,
         sum(gmv) filter (where bucket <> 'none') agmv,
         count(refunded) filter (where bucket <> 'none') na_ref,
         sum(refunded) filter (where bucket <> 'none') aref
  from gold.sales_line where eligible group by brand_id, local_date
),
p as (
  select brand_id, completed_local_date as day, count(*) n, count(merch_amount) nm, sum(merch_amount) m
  from gold.refund_line, cut
  where eligible and bucket <> 'none' and status in ('completed', 'partial') and completed_local_date <= cut.d
  group by brand_id, completed_local_date
)
select d.brand_id, d.day,
       case when d.day <= cov.c_orders then
            case when s.n is null then 0 when s.n = s.n_gmv then s.gmv end end as gross_gmv,
       case when cov.c_orders is not null and cov.c_aff is not null and d.day <= least(cov.c_orders, cov.c_aff) then
            case when s.na is null then 0 when s.na = s.na_gmv then s.agmv end end as creator_attributed_gmv,
       case when cov.c_orders is not null and cov.c_aff is not null and d.day <= least(cov.c_orders, cov.c_aff)
                 and cov.ret_ok then
            case when s.na is null then 0 when s.na = s.na_ref then s.aref end end as refunds_cohort,
       case when d.day <= cov.c_ret then
            case when p.n is null then 0 when p.n = p.nm then p.m end end as refunds_processed,
       case when cov.worst_rank is null or cov.worst_rank = 5 then 'unavailable'
            when d.day <= least(cov.c_orders, cov.c_aff, cov.c_ret) then 'current'
            when d.day <= greatest(cov.c_orders, cov.c_aff, cov.c_ret) and d.day <= (select as_of from asof) then 'partial'
            when cov.worst_rank >= 4 then 'unavailable'
            when d.day <= (select as_of from asof) then 'stale'
            else 'unavailable' end as status
from days d
join cov using (brand_id)
left join s on s.brand_id = d.brand_id and s.day = d.day
left join p on p.brand_id = d.brand_id and p.day = d.day;

-- ------------------------------------------------------------------ chart_reconciliation
create or replace view gold.chart_reconciliation as
with cut as (
  select coalesce(nullif(current_setting('app.cutoff', true), '')::date, (select as_of from gold.current_as_of)) as d
),
mo as (select distinct brand_id, month from gold.mv_sales_line where brand_id is not null),
bk as (select unnest(array['resolved', 'creator_unresolved', 'none', 'conflict']) as bucket),
a as (
  select brand_id, month, bucket, count(*) n, count(gmv) ng, sum(gmv) s
  from gold.mv_sales_line, cut
  where eligible and paid_local_date <= cut.d
  group by brand_id, month, bucket
),
cov as (
  select brand_id,
         max(coverage_through) filter (where source_type = 'orders') c_orders,
         max(coverage_through) filter (where source_type = 'affiliate_orders') c_aff
  from gold.source_freshness group by brand_id
)
select mo.brand_id, mo.month, bk.bucket,
       case when a.n is not null then (case when a.n = a.ng then a.s end)
            when k.known then 0 end as amount,
       case when a.n is not null then a.n when k.known then 0 end as order_items
from mo
cross join bk
cross join cut
join cov on cov.brand_id = mo.brand_id
cross join lateral (
  select coalesce(cov.c_orders >= least((mo.month + interval '1 month - 1 day')::date, cut.d)
              and cov.c_aff >= least((mo.month + interval '1 month - 1 day')::date, cut.d), false) as known
) k
left join a on a.brand_id = mo.brand_id and a.month = mo.month and a.bucket = bk.bucket;

-- ------------------------------------------------------------------ creator_concentration (Lorenz)
-- share is a 0..1 ratio; *_pct columns are percentages 0..100 (1 decimal). unresolved = the brand's GMV in the
-- creator_unresolved bucket (repeated on each row of the brand). Roster creators without sales appear with zero
-- only when orders and affiliate_orders coverage is current.
create or replace view gold.creator_concentration as
with cut as (
  select coalesce(nullif(current_setting('app.cutoff', true), '')::date, (select as_of from gold.current_as_of)) as d
),
cov as (
  select brand_id, bool_and(state in ('current', 'suspect')) as complete
  from gold.source_freshness where source_type in ('orders', 'affiliate_orders') group by brand_id
),
per as (
  select s.brand_id, s.creator_id,
         case when count(*) = count(s.gmv) then sum(s.gmv) end as gross_gmv,
         case when count(*) = count(s.net) then sum(s.net) end as net_sales
  from gold.sales_line s, cut
  where s.eligible and s.bucket = 'resolved' and s.paid_local_date <= cut.d
  group by s.brand_id, s.creator_id
),
allc as (
  select * from per
  union all
  select bc.brand_id, bc.creator_id, 0::numeric, 0::numeric
  from silver.brand_creator bc join cov using (brand_id)
  where bc.roster_active and cov.complete
    and not exists (select 1 from per p where p.brand_id = bc.brand_id and p.creator_id = bc.creator_id)
),
tot as (
  select brand_id, count(*) n_creators,
         case when count(*) = count(gross_gmv) then sum(gross_gmv) end as brand_gmv
  from allc group by brand_id
),
unr as (
  select s.brand_id, case when count(*) = count(s.gmv) then sum(s.gmv) end as unresolved
  from gold.mv_sales_line s, cut
  where s.eligible and s.bucket = 'creator_unresolved' and s.paid_local_date <= cut.d
  group by s.brand_id
),
r as (
  select a.*, t.n_creators, t.brand_gmv,
         row_number() over (partition by a.brand_id order by a.gross_gmv desc nulls last, a.creator_id) as rank
  from allc a join tot t using (brand_id)
)
select r.brand_id, r.rank::int as rank, r.creator_id, c.handle, r.gross_gmv,
       case when r.brand_gmv > 0 then round(r.gross_gmv / r.brand_gmv, 6) end as share,
       round(100.0 * r.rank / r.n_creators, 1) as cum_creator_pct,
       case when r.brand_gmv > 0 then
            round(100 * sum(r.gross_gmv) over (partition by r.brand_id order by r.rank) / r.brand_gmv, 1) end as cum_gmv_pct,
       r.net_sales,
       case when u.brand_id is not null then u.unresolved
            when cv.complete then 0 end as unresolved
from r
left join silver.creator c on c.creator_id = r.creator_id
left join unr u on u.brand_id = r.brand_id
left join cov cv on cv.brand_id = r.brand_id;

-- ------------------------------------------------------------------ diagnostic_period
-- period = 'current' (1st of the cutoff month .. cutoff) or 'baseline' (same days of the previous month).
-- Per (brand, period): one totals row (product_id NULL: active_creators, videos, linked_videos, linked_gmv,
-- unlinked_older_gmv) plus one row per product (product_id, product_gmv; other measures NULL).
-- linked_gmv = attributed GMV on eligible lines whose video was published inside the same period;
-- unlinked_older_gmv = attributed GMV minus linked_gmv (lines with no video or an older/unknown video).
create or replace view gold.diagnostic_period as
with cut as (
  select coalesce(nullif(current_setting('app.cutoff', true), '')::date, (select as_of from gold.current_as_of)) as d
),
per as (
  select 'current'::text as period, date_trunc('month', d::timestamp)::date as p_start, d as p_end from cut
  union all
  select 'baseline', (date_trunc('month', d::timestamp) - interval '1 month')::date,
         least((date_trunc('month', d::timestamp) - interval '1 month')::date + (extract(day from d)::int - 1),
               (date_trunc('month', d::timestamp) - interval '1 day')::date)
  from cut
),
bp as (select b.brand_id, per.* from silver.brand b cross join per),
cov as (
  select brand_id,
         max(state_rank) as worst_rank,
         min(coverage_through) as min_cov
  from gold.source_freshness where source_type in ('orders', 'affiliate_orders', 'videos_weekly')
  group by brand_id
),
st as (
  select bp.brand_id, bp.period,
         case when cov.worst_rank is null or cov.worst_rank = 5 then 'unavailable'
              when cov.min_cov < bp.p_start then 'unavailable'
              when cov.worst_rank = 4 then 'partial'
              when cov.min_cov < bp.p_end or cov.worst_rank = 3 then 'stale'
              else 'current' end as coverage_status,
         (cov.worst_rank <= 2 and cov.min_cov >= bp.p_end) as full
  from bp join cov using (brand_id)
),
vid as (
  select bp.brand_id, bp.period, count(distinct v.creator_id) active_creators, count(*) videos
  from bp join gold.mv_video_activity v
    on v.brand_id = bp.brand_id and v.qualifies and v.published_local_date between bp.p_start and bp.p_end
  group by bp.brand_id, bp.period
),
att as (
  select bp.brand_id, bp.period, count(*) n, count(s.gmv) ng, sum(s.gmv) gmv
  from bp join gold.mv_sales_line s
    on s.brand_id = bp.brand_id and s.eligible and s.bucket <> 'none'
   and s.paid_local_date between bp.p_start and bp.p_end
  group by bp.brand_id, bp.period
),
lnk as (
  select bp.brand_id, bp.period, count(*) n, count(s.gmv) ng, sum(s.gmv) gmv, count(distinct s.video_id) videos
  from bp
  join gold.mv_sales_line s
    on s.brand_id = bp.brand_id and s.eligible and s.bucket <> 'none' and s.video_id is not null
   and s.paid_local_date between bp.p_start and bp.p_end
  join gold.mv_video_activity v
    on v.brand_id = s.brand_id and v.video_id = s.video_id and v.qualifies
   and v.published_local_date between bp.p_start and bp.p_end
  group by bp.brand_id, bp.period
),
prod as (
  select bp.brand_id, bp.period, s.product_id, count(*) n, count(s.gmv) ng, sum(s.gmv) gmv
  from bp join gold.mv_sales_line s
    on s.brand_id = bp.brand_id and s.eligible and s.bucket <> 'none'
   and s.paid_local_date between bp.p_start and bp.p_end
  group by bp.brand_id, bp.period, s.product_id
)
select st.brand_id, st.period,
       case when vid.brand_id is not null then vid.active_creators when st.full then 0 end::int as active_creators,
       case when vid.brand_id is not null then vid.videos when st.full then 0 end::int as videos,
       case when lnk.brand_id is not null then lnk.videos when st.full then 0 end::int as linked_videos,
       case when lnk.brand_id is not null then (case when lnk.n = lnk.ng then lnk.gmv end) when st.full then 0 end as linked_gmv,
       case when att.brand_id is not null and lnk.brand_id is not null
                 then (case when att.n = att.ng and lnk.n = lnk.ng then att.gmv - lnk.gmv end)
            when att.brand_id is not null and lnk.brand_id is null
                 then (case when att.n = att.ng and st.full then att.gmv end)
            when att.brand_id is null and st.full then 0 end as unlinked_older_gmv,
       null::text as product_id, null::numeric as product_gmv, st.coverage_status
from st
left join vid on vid.brand_id = st.brand_id and vid.period = st.period
left join att on att.brand_id = st.brand_id and att.period = st.period
left join lnk on lnk.brand_id = st.brand_id and lnk.period = st.period
union all
select st.brand_id, st.period, null, null, null, null, null,
       p.product_id, case when p.n = p.ng then p.gmv end, st.coverage_status
from prod p join st on st.brand_id = p.brand_id and st.period = p.period;

-- ------------------------------------------------------------------ retainer_cadence (ruling 4)
-- One point for every complete month (relative to the cutoff) in which a contract is effective for any day.
-- expected_posts = posts_per_month x share x effective days / days in month. posts / attainment_pct are NULL
-- unless the brand weekly video coverage is gap-free through month end; a verified zero is posts 0, attainment 0.
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
vc as (select brand_id, coverage_through, n_gaps from gold.source_freshness where source_type = 'videos_weekly'),
pc as (
  select v.brand_id, v.creator_id, v.month, count(*) posts
  from gold.mv_video_activity v, cut c
  where v.qualifies and v.published_local_date <= c.d
  group by v.brand_id, v.creator_id, v.month
)
select kk.brand_id, kk.creator_id, cr.handle, kk.month_start as month,
       case when kk.share is not null then round(kk.posts_per_month * kk.share * kk.days / kk.dim, 2) end as expected_posts,
       case when vc.n_gaps = 0 and vc.coverage_through >= kk.month_end then coalesce(pc.posts, 0) end as posts,
       case when vc.n_gaps = 0 and vc.coverage_through >= kk.month_end
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

-- ------------------------------------------------------------------ unresolved_identity (ruling 1)
-- Attribution creator ids that are not on the brand roster (or have no id) are unresolved; raw identifier shown as
-- "<id> (<handle>)". Videos and samples without a resolvable creator are listed as before.
create or replace view gold.unresolved_identity as
select brand_id, 'affiliate_orders'::text as source, raw_identifier, count(*)::int as occurrences
from (
  select b.brand_id,
         case when a.creator_id is not null
              then a.creator_id || coalesce(' (' || a.creator_handle || ')', '')
              else coalesce(a.creator_handle, '(no creator id or handle)') end as raw_identifier
  from silver.attribution a
  join silver.brand b on b.shop_id = a.shop_id
  where a.creator_id is null
     or not exists (select 1 from silver.brand_creator bc where bc.brand_id = b.brand_id and bc.creator_id = a.creator_id)
) x
group by brand_id, raw_identifier
union all
select brand_id, 'videos_weekly', coalesce(creator_handle, '(no creator id or handle)'), count(*)::int
from silver.video where creator_id is null group by 1, 2, 3
union all
select brand_id, 'samples', coalesce(creator_handle, '(no creator id or handle)'), count(*)::int
from silver.sample_shipment where creator_id is null group by 1, 2, 3;

select gold.refresh_materialized();
