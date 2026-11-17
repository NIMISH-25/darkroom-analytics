-- Materialized gold: depend on the dataset revision, not on the request. Refresh with gold.refresh_materialized().
-- Rule 8 amendment: materialized views are dropped/recreated by migrations; public views keep names and columns.

-- ---------------------------------------------------------------- sales_line (everything except refund-derived columns)
create materialized view gold.mv_sales_line as
with la as (
  select shop_id, order_id, line_id, count(*) n_rec,
         case when count(*) = 1 then max(creator_id) end creator_id,
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
         o.status order_status, i.item_status, i.is_sample, i.paid_amount,
         (o.paid_at is not null and o.status not in ('UNPAID', 'CANCELLED')
          and not o.is_sample and not i.is_sample
          and i.item_status is distinct from 'CANCELLED') as eligible,
         case when o.paid_at is null or o.status = 'UNPAID' then 'unpaid'
              when o.is_sample or i.is_sample then 'sample'
              when o.status = 'CANCELLED' or i.item_status is not distinct from 'CANCELLED' then 'cancelled'
         end as exclusion_reason,
         la.n_rec, la.creator_id, la.video_id, la.content_type, la.affiliate_record_id,
         la.a_source_file_id, la.a_row_num,
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
            when base.creator_id is null then 'creator_unresolved'
            else 'resolved' end as bucket,
       base.creator_id, base.video_id, base.content_type, base.affiliate_record_id,
       (base.video_id is not null and exists (
          select 1 from silver.video v where v.brand_id = base.brand_id and v.video_id = base.video_id)) as video_known,
       base.source_file_id, base.row_num,
       base.source_path as source_file,
       'orders[' || base.row_num || '].line_items[id=' || base.line_id || ']' as source_locator,
       base.a_source_file_id as attribution_source_file_id, base.a_row_num as attribution_row_num
from base;
create unique index ux_mv_sales_line_key on gold.mv_sales_line (shop_id, order_id, line_id);
create index ix_mv_sales_line_brand_month on gold.mv_sales_line (brand_id, month, order_id, line_id);
create index ix_mv_sales_line_creator on gold.mv_sales_line (brand_id, creator_id, month);
create index ix_mv_sales_line_prov on gold.mv_sales_line (source_file_id, row_num);

-- Public view: refunds completed up to the request cutoff are applied per request.
-- Cutoff = session setting app.cutoff (YYYY-MM-DD) when present, else the dataset as_of.
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
       m.attribution_source_file_id, m.attribution_row_num
from gold.mv_sales_line m
left join rf on (rf.shop_id, rf.order_id, rf.line_id) = (m.shop_id, m.order_id, m.line_id);

-- ---------------------------------------------------------------- video_activity
create materialized view gold.mv_video_activity as
select v.brand_id, v.video_id, v.creator_id, v.creator_handle, v.product_id,
       v.published_at, v.published_local_date, v.published_local_date as local_date,
       date_trunc('month', v.published_local_date::timestamp)::date as month,
       (v.creator_id is not null and v.published_at is not null) as qualifies,
       case when v.published_at is null then 'no_post_time'
            when v.creator_id is null then 'creator_unresolved' end as disqualify_reason,
       s.n_snapshots,
       case when s.n_snapshots = s.n_views then s.views_total end as views_total,
       case when s.n_snapshots = s.n_gmv then s.gmv_total end as gmv_reported_total,
       v.source_file_id, v.row_num, sf.path as source_file,
       'sheet "Video performance" row ' || v.row_num as source_locator
from silver.video v
left join bronze.source_file sf on sf.source_file_id = v.source_file_id
left join (
  select brand_id, video_id, count(*) n_snapshots, count(views) n_views, sum(views) views_total,
         count(gmv_reported) n_gmv, sum(gmv_reported) gmv_total
  from silver.video_snapshot group by brand_id, video_id
) s using (brand_id, video_id);
create unique index ux_mv_video_activity_key on gold.mv_video_activity (brand_id, video_id);
create index ix_mv_video_activity_month on gold.mv_video_activity (brand_id, month, video_id);
create index ix_mv_video_activity_creator on gold.mv_video_activity (brand_id, creator_id, month);
create index ix_mv_video_activity_prov on gold.mv_video_activity (source_file_id, row_num);

create or replace view gold.video_activity as select * from gold.mv_video_activity;

-- ---------------------------------------------------------------- sample_funnel
create materialized view gold.mv_sample_funnel as
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
       'sheet "Samples" row ' || y.row_num as source_locator,
       -- verified zero / rate needs complete video coverage; consumers must treat partial/stale as unknown
       y.video_state as video_coverage_state,
       (coalesce(y.video_gaps, 1) = 0 and y.video_state in ('current', 'suspect')) as video_coverage_complete
from y
left join bronze.source_file sf on sf.source_file_id = y.source_file_id;

create unique index ux_mv_sample_funnel_key on gold.mv_sample_funnel (brand_id, shipment_id, line_no);
create index ix_mv_sample_funnel_brand on gold.mv_sample_funnel (brand_id, creator_id);
create or replace view gold.sample_funnel as select * from gold.mv_sample_funnel;

-- ---------------------------------------------------------------- goal_progress
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
