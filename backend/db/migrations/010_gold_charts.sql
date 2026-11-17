-- Gold chart series (plain views). NULL = unknown; SUMs guarded by count(*) = count(col);
-- a zero is emitted only where source coverage makes it verifiable. Business dates are America/Los_Angeles
-- (already applied in Silver). Cutoff = session setting app.cutoff (YYYY-MM-DD) when set, else the dataset as_of.
-- The two analysis drafts (creator_concentration, retainer_cadence) had different column sets, so they are
-- dropped first (CREATE OR REPLACE cannot change columns); nothing else depends on them.
drop view if exists gold.creator_concentration;
drop view if exists gold.retainer_cadence;
drop view if exists gold.diagnostic_period;

-- ------------------------------------------------------------------ chart_daily
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

-- ------------------------------------------------------------------ chart_sample_funnel
-- Stage rows have lag_bucket NULL. Lag rows use stage = 'converted' with lag_bucket in (0-7, 8-14, 15-21, 22-30);
-- they sum to converted (negative lags fall in 0-7, lags above 21 in 22-30).
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
       case when fr.state = 'missing' then null else coalesce(c.n, 0)::int end as count
from silver.brand b
cross join grid g
left join gold.source_freshness fr on fr.brand_id = b.brand_id and fr.source_type = 'samples'
left join c on c.brand_id = b.brand_id and c.stage = g.stage and c.lag_bucket is not distinct from g.lag_bucket;

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

-- ------------------------------------------------------------------ retainer_cadence
-- Complete calendar months only. expected_posts and retainer_allocated are prorated by contract days in month
-- and allocation share. posts / attainment_pct are NULL unless the brand weekly video coverage is gap-free
-- and reaches month end (a zero is verified only then).
create or replace view gold.retainer_cadence as
with asof as (select as_of from gold.current_as_of),
months as (
  select g::date as month_start, (g + interval '1 month - 1 day')::date as month_end,
         extract(day from (g + interval '1 month - 1 day'))::int as dim
  from asof a,
       generate_series((select date_trunc('month', min(paid_local_date)::timestamp) from gold.mv_sales_line),
                       date_trunc('month', a.as_of::timestamp), interval '1 month') g
  where (g + interval '1 month - 1 day')::date <= a.as_of
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
  from gold.mv_video_activity v, asof a
  where v.qualifies and v.published_local_date <= a.as_of
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
