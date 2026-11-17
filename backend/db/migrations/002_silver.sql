-- Silver: typed, normalized, natural-key PKs. NULL = unknown. Soft links only (no FKs).
create table silver.brand (
  brand_id text primary key, shop_id text not null, name text not null,
  reporting_tz text not null, currency text not null,
  source_file_id bigint, row_num int, row_hash text
);
create table silver.creator (
  creator_id text primary key, handle text,
  source_file_id bigint, row_num int, row_hash text
);
create table silver.creator_alias (
  namespace text not null, alias_norm text not null, valid_from date not null,
  creator_id text, reviewed boolean not null default false, n_creators int not null default 1,
  source_file_id bigint, row_num int, row_hash text,
  primary key (namespace, alias_norm, valid_from)
);
create table silver.brand_creator (
  brand_id text not null, creator_id text not null,
  roster_active boolean not null, handle text, contract_type text, status text,
  effective_from date, effective_to date,
  source_file_id bigint, row_num int, row_hash text,
  primary key (brand_id, creator_id)
);
create table silver.product (
  shop_id text not null, product_id text not null,
  sku_id text, name text, list_price numeric(14,2), unit_cost numeric(14,2),
  active boolean not null default true,
  source_file_id bigint, row_num int, row_hash text,
  primary key (shop_id, product_id)
);
create table silver.shop_order (
  shop_id text not null, order_id text not null,
  paid_at timestamptz, paid_local_date date, status text not null,
  is_sample boolean not null, src_updated_at timestamptz,
  source_file_id bigint, row_num int, row_hash text,
  primary key (shop_id, order_id)
);
create table silver.order_item (
  shop_id text not null, order_id text not null, line_id text not null,
  product_id text, paid_amount numeric(14,2), item_status text, is_sample boolean not null,
  source_file_id bigint, row_num int, row_hash text,
  primary key (shop_id, order_id, line_id)
);
create table silver.attribution (
  shop_id text not null, affiliate_record_id text not null,
  order_id text not null, line_id text not null, creator_id text, creator_handle text,
  video_id text, content_type text, src_updated_at timestamptz,
  source_file_id bigint, row_num int, row_hash text,
  primary key (shop_id, affiliate_record_id)
);
create table silver.commission (
  shop_id text not null, commission_id text not null,
  affiliate_record_id text not null, rate numeric(8,4), amount numeric(14,2),
  status text not null check (status in ('pending','settled')),
  source_file_id bigint, row_num int, row_hash text,
  primary key (shop_id, commission_id)
);
create table silver.refund (
  shop_id text not null, refund_id text not null, line_id text not null,
  order_id text not null, merch_amount numeric(14,2), tax_amount numeric(14,2),
  status text not null check (status in ('requested','completed','partial','rejected')),
  completed_at timestamptz, completed_local_date date, src_updated_at timestamptz,
  source_file_id bigint, row_num int, row_hash text,
  primary key (shop_id, refund_id, line_id)
);
create table silver.video (
  brand_id text not null, video_id text not null,
  creator_id text, creator_handle text, product_id text,
  published_at timestamptz, published_local_date date,
  source_file_id bigint, row_num int, row_hash text,
  primary key (brand_id, video_id)
);
create table silver.video_snapshot (
  brand_id text not null, video_id text not null, period_start date not null,
  period_end date, views bigint, gmv_reported numeric(14,2), items_sold int, observed_at timestamptz,
  source_file_id bigint, row_num int, row_hash text,
  primary key (brand_id, video_id, period_start)
);
create table silver.sample_shipment (
  brand_id text not null, shipment_id text not null,
  creator_id text, creator_handle text, shipped_at date, delivered_at date,
  status_text text, shipping_cost numeric(14,2), active boolean not null default true,
  source_file_id bigint, row_num int, row_hash text,
  primary key (brand_id, shipment_id)
);
create table silver.sample_item (
  brand_id text not null, shipment_id text not null, line_no int not null,
  product_id text, qty int, linked_video_id text, active boolean not null default true,
  source_file_id bigint, row_num int, row_hash text,
  primary key (brand_id, shipment_id, line_no)
);
create table silver.goal (
  brand_id text not null, month date not null, metric_key text not null, scope text not null,
  basis text not null, definition_version text not null, definition text, target_value numeric,
  active boolean not null default true,
  source_file_id bigint, row_num int, row_hash text,
  primary key (brand_id, month, metric_key, scope)
);
create table silver.contract (
  contract_id text primary key, creator_id text not null,
  monthly_retainer numeric(14,2), posts_per_month int,
  effective_from date, effective_to date,
  source_file_id bigint, row_num int, row_hash text
);
create table silver.contract_allocation (
  contract_id text not null, brand_id text not null, share numeric(8,6),
  source_file_id bigint, row_num int, row_hash text,
  primary key (contract_id, brand_id)
);
