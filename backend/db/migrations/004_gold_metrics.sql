-- Gold, part 2: creator_performance, sample_funnel, goal_progress, needs_attention.

create or replace view gold.sample_funnel as
with asof as (select as_of from gold.current_as_of),
it as (
  select si.brand_id, si.shipment_id, si.line_no, sh.creator_id, sh.creator_handle, si.product_id,
         p.sku_id, p.name as product_name, si.qty, si.linked_video_id,
         sh.shipped_at, sh.delivered_at, sh.status_text, sh.shipping_cost,
         si.source_file_id, si.row_num
  from silver.sample_item si
  join silver.sample_shipment sh on sh.brand_id = si.brand_id and sh.shipment_id = si.shipment_id
  left join silver.brand b on b.brand_id = si.brand_id
  left join silver.product p on p.shop_id = b.shop_id and p.product_id = si.product_id
  where si.active and sh.active
),
cand as (
  select it.brand_id, it.shipment_id, it.line_no, v.video_id, v.published_local_date,
         count(*) over (partition by it.brand_id, it.shipment_id, it.line_no) n_cand,
         count(*) over (partition by it.brand_id, v.video_id) n_items
  from it
  join gold.video_activity v
    on v.brand_id = it.brand_id and v.creator_id = it.creator_id and v.product_id = it.product_id
   and v.qualifies and it.delivered_at is not null
   and v.published_local_date >= it.delivered_at
   and v.published_local_date < it.delivered_at + 30
  cross join asof a
  where v.published_local_date <= a.as_of
),
pick as (
  select brand_id, shipment_id, line_no,
         max(video_id) filter (where n_cand = 1 and n_items = 1) video_id,
         bool_or(n_cand > 1 or n_items > 1) ambiguous
  from cand group by brand_id, shipment_id, line_no
),
x as (
  select it.*, a.as_of,
         ev.video_id as explicit_video_id, ev.published_local_date as explicit_date,
         pk.video_id as pick_video_id, coalesce(pk.ambiguous, false) as ambiguous,
         vf.coverage_through as video_coverage_through, vf.n_gaps as video_gaps, vf.state as video_state,
         c.handle as creator_handle_resolved
  from it
  cross join asof a
  left join gold.video_activity ev on ev.brand_id = it.brand_id and ev.video_id = it.linked_video_id
  left join pick pk on pk.brand_id = it.brand_id and pk.shipment_id = it.shipment_id and pk.line_no = it.line_no
  left join gold.source_freshness vf on vf.brand_id = it.brand_id and vf.source_type = 'videos_weekly'
  left join silver.creator c on c.creator_id = it.creator_id
),
y as (
  select x.*,
    case
      when x.explicit_video_id is not null then 'matched'
      when x.linked_video_id is not null then 'unknown'
      when x.delivered_at is null then case when x.status_text in ('Returned', 'Delivered') then 'unknown' else 'in_transit' end
      when x.creator_id is null then 'unknown'
      when x.pick_video_id is not null then 'matched'
      when x.ambiguous then 'unknown'
      when x.as_of < x.delivered_at + 30 then 'pending'
      when coalesce(x.video_gaps, 1) = 0 and x.video_state in ('current', 'stale', 'suspect')
           and x.video_coverage_through >= x.delivered_at + 29 then 'no_video'
      else 'unknown'
    end as state
  from x
)
select y.brand_id, y.shipment_id, y.line_no,
       y.shipment_id || ':' || y.line_no as sample_id,
       y.creator_id, coalesce(y.creator_handle_resolved, y.creator_handle) as handle,
       y.product_id, coalesce(y.sku_id, y.product_id) as product_sku, y.product_name, y.qty,
       y.shipped_at as sent_date, y.delivered_at as delivered_date, y.status_text,
       y.state,
       case
         when y.explicit_video_id is not null then 'explicit_link'
         when y.linked_video_id is not null then 'linked_video_not_found'
         when y.state = 'unknown' and y.delivered_at is null then 'delivery_unconfirmed'
         when y.state = 'unknown' and y.creator_id is null then 'creator_unresolved'
         when y.state = 'unknown' and y.ambiguous then 'ambiguous_match'
         when y.state = 'unknown' then 'video_coverage_incomplete'
         when y.state = 'matched' then 'exact_match'
       end as state_reason,
       case when y.state = 'matched' then coalesce(y.explicit_video_id, y.pick_video_id) end as matched_video_id,
       case when y.state = 'matched'
            then coalesce(y.explicit_date, (select v.published_local_date from gold.video_activity v
                                            where v.brand_id = y.brand_id and v.video_id = y.pick_video_id)) - y.delivered_at
       end as delivery_to_video_days,
       (y.delivered_at is not null and y.as_of >= y.delivered_at + 30) as mature,
       case when y.delivered_at is not null then y.as_of - y.delivered_at end as days_since_delivery,
       (y.state = 'matched') as converted,
       (y.delivered_at is not null and y.as_of >= y.delivered_at + 30 and y.state in ('matched', 'no_video')) as in_rate_denominator,
       y.as_of,
       y.source_file_id, y.row_num, sf.path as source_file,
       'sheet "Samples" row ' || y.row_num as source_locator
from y
left join bronze.source_file sf on sf.source_file_id = y.source_file_id;

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

create or replace view gold.goal_progress as
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
g4 as (
  select g3.*,
    case when g3.elapsed_days is null or g3.state = 'missing' then null
         when g3.metric_key = 'gmv' then (
           select case when count(*) = 0 then 0
                       when count(*) = count(case when g3.basis = 'net' then s.net else s.gmv end)
                       then sum(case when g3.basis = 'net' then s.net else s.gmv end) end
           from gold.sales_line s
           where s.brand_id = g3.brand_id and s.eligible
             and s.paid_local_date between g3.month_start and g3.cutoff_date
             and (g3.scope <> 'creator_attributed' or s.bucket <> 'none'))
         when g3.metric_key = 'videos' then (
           select count(*) from gold.video_activity v
           where v.brand_id = g3.brand_id and v.qualifies
             and v.published_local_date between g3.month_start and g3.cutoff_date)
         when g3.metric_key = 'active_creators' then (
           select count(distinct v.creator_id) from gold.video_activity v
           where v.brand_id = g3.brand_id and v.qualifies
             and v.published_local_date between g3.month_start and g3.cutoff_date)
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
),
g5 as (
  select g4.*,
         (g4.curve ->> 'n')::int as curve_months,
         (g4.curve ->> 'median')::numeric as curve_median
  from g4
),
g6 as (
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

create or replace view gold.needs_attention as
with asof as (select as_of from gold.current_as_of)
select bc.brand_id, 'quiet_retainer'::text as kind, bc.creator_id as entity_ref,
       'Retainer creator with no qualifying video in the 10 days ending ' || f.coverage_through
         || ' (video coverage complete)' as reason,
       (f.coverage_through - 9) as period_start, f.coverage_through as period_end,
       'quiet_retainer:' || bc.brand_id || ':' || bc.creator_id as item_id,
       bc.creator_id, null::int as days_since_delivery, null::int as followup_days,
       'Quiet retainer creator: ' || bc.creator_id as title, null::int as days_waiting
from silver.brand_creator bc
cross join asof a
join silver.contract c on c.creator_id = bc.creator_id
join silver.contract_allocation ca on ca.contract_id = c.contract_id and ca.brand_id = bc.brand_id
join gold.source_freshness f on f.brand_id = bc.brand_id and f.source_type = 'videos_weekly'
where bc.roster_active and bc.contract_type = 'retainer'
  and (c.effective_from is null or c.effective_from <= f.coverage_through - 9)
  and (c.effective_to is null or c.effective_to >= a.as_of)
  and f.state in ('current', 'suspect')
  and not exists (
    select 1 from gold.video_activity v
    where v.brand_id = bc.brand_id and v.creator_id = bc.creator_id and v.qualifies
      and v.published_local_date between f.coverage_through - 9 and f.coverage_through)
union all
select sf.brand_id, 'sample_no_video', sf.sample_id,
       'Delivered ' || sf.delivered_date || ' (' || sf.days_since_delivery || ' days ago), no qualifying video from the creator for this product',
       sf.delivered_date, sf.as_of,
       'sample_no_video:' || sf.brand_id || ':' || sf.sample_id,
       sf.creator_id, sf.days_since_delivery, 14,
       'Sample with no video: ' || sf.sample_id, sf.days_since_delivery
from gold.sample_funnel sf
where sf.state in ('pending', 'no_video') and sf.days_since_delivery >= 14
union all
select f.brand_id, 'missing_source', f.source_type,
       f.source_type || ' is ' || f.state || ': ' || coalesce(f.message, ''),
       f.coverage_through + 1, f.expected_through,
       'missing_source:' || f.brand_id || ':' || f.source_type,
       null::text, null::int, null::int,
       'Source ' || f.state || ': ' || f.source_type, null::int
from gold.source_freshness f
where f.state in ('missing', 'incomplete');
