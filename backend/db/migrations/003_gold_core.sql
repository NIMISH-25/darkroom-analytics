-- Gold, part 1: as-of, freshness, row-level sales/video/sample views.
-- Views only (CREATE OR REPLACE). Aggregates guard SUM with count(*) = count(col).

create or replace view gold.current_as_of as
select revision_id, as_of
from meta.dataset_revision
order by revision_id desc
limit 1;

-- Contiguous manifest-declared coverage per (brand, source). Never derived from event dates.
create or replace view gold.source_coverage as
with scoped as (
  select b.brand_id, f.source_type, f.kind, f.status, f.coverage_start, f.coverage_end,
         f.src_updated_at, f.ingested_at
  from silver.brand b
  join bronze.source_file f on f.scope_key in (b.brand_id, b.shop_id, 'all')
),
acc as (
  select brand_id, source_type, coverage_start s, coverage_end e
  from scoped
  where status = 'accepted' and kind = 'increment'
    and coverage_start is not null and coverage_end is not null
),
ord as (
  select brand_id, source_type, s, e,
         max(e) over (partition by brand_id, source_type order by s, e
                      rows between unbounded preceding and 1 preceding) prev_e
  from acc
),
isl as (
  select *, sum(case when prev_e is null or s > prev_e + 1 then 1 else 0 end)
              over (partition by brand_id, source_type order by s, e) grp
  from ord
),
inc as (
  select brand_id, source_type,
         min(s) as coverage_start,
         max(e) filter (where grp = 1) as coverage_through,
         max(grp)::int as n_islands
  from isl group by brand_id, source_type
),
snap as (
  select brand_id, source_type,
         null::date as coverage_start,
         max((coalesce(src_updated_at, ingested_at) at time zone 'America/Los_Angeles')::date) as coverage_through,
         1 as n_islands
  from scoped
  where status = 'accepted' and kind = 'snapshot'
  group by brand_id, source_type
)
select * from inc union all select * from snap;

create or replace view gold.source_freshness as
with asof as (select as_of from gold.current_as_of),
stats as (
  select b.brand_id, c.source_type, c.cadence, c.lag_days,
         count(f.source_file_id) filter (where f.status = 'accepted') n_accepted,
         count(f.source_file_id) filter (where f.status = 'quarantined') n_quarantined,
         count(f.source_file_id) filter (where f.status = 'rejected') n_rejected,
         max(f.ingested_at) filter (where f.status = 'accepted') last_ingested_at,
         (array_agg(f.error order by f.source_file_id desc) filter (where f.status <> 'accepted'))[1] last_error
  from silver.brand b
  cross join meta.source_contract c
  left join bronze.source_file f
    on f.source_type = c.source_type and f.scope_key in (b.brand_id, b.shop_id, 'all')
  group by b.brand_id, c.source_type, c.cadence, c.lag_days
),
susp as (
  select brand_id, source_type, count(*) n
  from meta.quality_issue where state = 'open' and severity = 'suspect'
  group by brand_id, source_type
),
x as (
  select s.*, a.as_of, cov.coverage_through, cov.coverage_start,
         coalesce(cov.n_islands, 0) n_islands, coalesce(su.n, 0) n_suspect,
         case s.cadence
           when 'weekly' then (a.as_of - s.lag_days) - (extract(isodow from (a.as_of - s.lag_days))::int % 7)
           else a.as_of - s.lag_days
         end as expected_through
  from stats s
  cross join asof a
  left join gold.source_coverage cov using (brand_id, source_type)
  left join susp su using (brand_id, source_type)
),
y as (
  select x.*,
    case when n_accepted = 0 then 'missing'
         when n_islands > 1 or n_quarantined > 0 or n_rejected > 0 then 'incomplete'
         when coverage_through is null or coverage_through < expected_through then 'stale'
         when n_suspect > 0 then 'suspect'
         else 'current' end as state
  from x
)
select brand_id, source_type, as_of, state, coverage_through, expected_through, coverage_start,
       greatest(n_islands - 1, 0) as n_gaps, n_accepted, n_quarantined, n_rejected, n_suspect,
       last_ingested_at,
       case state
         when 'missing' then 'No accepted ' || source_type || ' files'
         when 'incomplete' then source_type || ': ' || greatest(n_islands - 1, 0) || ' coverage gap(s), '
              || n_quarantined || ' quarantined, ' || n_rejected || ' rejected file(s)'
              || coalesce('; last error: ' || last_error, '')
         when 'stale' then source_type || ' covered through ' || coalesce(coverage_through::text, 'unknown')
              || ', expected through ' || expected_through
         when 'suspect' then n_suspect || ' open anomaly(ies) on ' || source_type
         else null end as message,
       case state when 'missing' then 5 when 'incomplete' then 4 when 'stale' then 3
                  when 'suspect' then 2 else 1 end as state_rank
from y;

-- One row per order line; the evidence row for every sales number.
create or replace view gold.sales_line as
with asof as (select as_of from gold.current_as_of),
la as (
  select shop_id, order_id, line_id, count(*) n_rec,
         case when count(*) = 1 then max(creator_id) end creator_id,
         case when count(*) = 1 then max(video_id) end video_id,
         case when count(*) = 1 then max(content_type) end content_type,
         case when count(*) = 1 then max(affiliate_record_id) end affiliate_record_id,
         case when count(*) = 1 then max(source_file_id) end a_source_file_id,
         case when count(*) = 1 then max(row_num) end a_row_num
  from silver.attribution group by shop_id, order_id, line_id
),
rf as (
  select r.shop_id, r.order_id, r.line_id,
         count(*) n_completed,
         count(*) filter (where r.merch_amount is null) n_unknown,
         sum(r.merch_amount) known_sum
  from silver.refund r cross join asof a
  where r.status in ('completed', 'partial') and r.completed_local_date <= a.as_of
  group by r.shop_id, r.order_id, r.line_id
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
         rf.n_completed, rf.n_unknown, rf.known_sum,
         i.source_file_id, i.row_num, sf.path as source_path
  from silver.order_item i
  join silver.shop_order o on o.shop_id = i.shop_id and o.order_id = i.order_id
  left join silver.brand b on b.shop_id = i.shop_id
  left join bronze.source_file sf on sf.source_file_id = i.source_file_id
  left join la on (la.shop_id, la.order_id, la.line_id) = (i.shop_id, i.order_id, i.line_id)
  left join rf on (rf.shop_id, rf.order_id, rf.line_id) = (i.shop_id, i.order_id, i.line_id)
)
select base.brand_id, base.shop_id, base.order_id, base.line_id, base.product_id,
       base.paid_at, base.paid_local_date, base.paid_local_date as local_date, base.month, base.order_status, base.item_status, base.is_sample,
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
       case when not base.eligible then null
            when base.n_unknown > 0 then null
            else coalesce(base.known_sum, 0) end as refunded,
       case when not base.eligible then null
            when coalesce(base.n_completed, 0) = 0 then 'none'
            when base.n_unknown > 0 then 'partial'
            else 'complete' end as refund_state,
       case when base.eligible and coalesce(base.n_unknown, 0) = 0
            then base.paid_amount - coalesce(base.known_sum, 0) end as net,
       base.source_file_id, base.row_num,
       base.source_path as source_file,
       'orders[' || base.row_num || '].line_items[id=' || base.line_id || ']' as source_locator,
       base.a_source_file_id as attribution_source_file_id, base.a_row_num as attribution_row_num
from base;

-- Completed refunds with their own dates so any cutoff can be applied (cohort view).
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

create or replace view gold.video_activity as
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

create or replace view gold.sample_cost_line as
select sh.brand_id, sh.shipment_id, sh.creator_id, sh.shipped_at,
       date_trunc('month', sh.shipped_at::timestamp)::date as month,
       it.n_items, it.items_cost, sh.shipping_cost,
       case when it.items_cost is not null and sh.shipping_cost is not null
            then it.items_cost + sh.shipping_cost end as cost,
       sh.source_file_id, sh.row_num
from silver.sample_shipment sh
left join (
  select si.brand_id, si.shipment_id, count(*) n_items,
         case when count(*) = count(si.qty * p.unit_cost) then sum(si.qty * p.unit_cost) end items_cost
  from silver.sample_item si
  join silver.brand b on b.brand_id = si.brand_id
  left join silver.product p on p.shop_id = b.shop_id and p.product_id = si.product_id
  where si.active
  group by si.brand_id, si.shipment_id
) it using (brand_id, shipment_id)
where sh.active;

create or replace view gold.unresolved_identity as
select b.brand_id, 'affiliate_orders'::text as source, a.creator_handle as raw_identifier, count(*)::int as occurrences
from silver.attribution a join silver.brand b on b.shop_id = a.shop_id
where a.creator_id is null group by 1, 2, 3
union all
select brand_id, 'videos_weekly', creator_handle, count(*)::int
from silver.video where creator_id is null group by 1, 2, 3
union all
select brand_id, 'samples', creator_handle, count(*)::int
from silver.sample_shipment where creator_id is null group by 1, 2, 3;
