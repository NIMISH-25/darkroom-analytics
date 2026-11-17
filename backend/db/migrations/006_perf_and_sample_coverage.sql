-- Indexes on silver/bronze join keys used by the gold views.
create index if not exists ix_attribution_line on silver.attribution (shop_id, order_id, line_id);
create index if not exists ix_refund_line on silver.refund (shop_id, order_id, line_id);
create index if not exists ix_order_item_order on silver.order_item (shop_id, order_id);
create index if not exists ix_video_creator on silver.video (brand_id, creator_id);
create index if not exists ix_video_snapshot_video on silver.video_snapshot (brand_id, video_id);
create index if not exists ix_sample_item_ship on silver.sample_item (brand_id, shipment_id);
create index if not exists ix_commission_rec on silver.commission (shop_id, affiliate_record_id);
create index if not exists ix_issue_open on meta.quality_issue (state, severity, brand_id, source_type);

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
       'sheet "Samples" row ' || y.row_num as source_locator,
       -- verified zero / rate needs complete video coverage; consumers must treat partial/stale as unknown
       y.video_state as video_coverage_state,
       (coalesce(y.video_gaps, 1) = 0 and y.video_state in ('current', 'suspect')) as video_coverage_complete
from y
left join bronze.source_file sf on sf.source_file_id = y.source_file_id;
