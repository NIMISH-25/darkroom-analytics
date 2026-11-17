-- Zero-total brands have no concentration rows; samples naming a creator that is not on the brand roster are unresolved identities.
-- ------------------------------------------------------------------ creator_concentration (Lorenz)
-- Brands whose total attributed GMV is zero have no curve: no rows (never a chart of zeros).
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
left join cov cv on cv.brand_id = r.brand_id
where r.brand_gmv is null or r.brand_gmv > 0;

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
select sh.brand_id, 'samples',
       case when sh.creator_id is not null then sh.creator_id || coalesce(' (' || sh.creator_handle || ')', '')
            else coalesce(sh.creator_handle, '(no creator id or handle)') end,
       count(*)::int
from silver.sample_shipment sh
where sh.creator_id is null
   or not exists (select 1 from silver.brand_creator bc where bc.brand_id = sh.brand_id and bc.creator_id = sh.creator_id)
group by 1, 2, 3;
