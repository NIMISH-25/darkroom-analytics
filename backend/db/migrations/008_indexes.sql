-- Composite and provenance indexes. Equivalents created in 006 are not duplicated:
--   attribution(shop_id, order_id, line_id) = ix_attribution_line; order_item(shop_id, order_id) = ix_order_item_order
--   (also the PK prefix); video(brand_id, creator_id) = ix_video_creator; refund(shop_id, order_id, line_id) = ix_refund_line.
create index if not exists ix_shop_order_paid on silver.shop_order (shop_id, paid_local_date);
create index if not exists ix_refund_completed on silver.refund (shop_id, completed_local_date);
create index if not exists ix_video_published on silver.video (brand_id, published_local_date);
create index if not exists ix_attribution_creator on silver.attribution (creator_id);
create index if not exists ix_sample_shipment_creator on silver.sample_shipment (brand_id, creator_id);
-- provenance (source_file_id, row_num) on every Silver fact table
create index if not exists ix_prov_brand_creator on silver.brand_creator (source_file_id, row_num);
create index if not exists ix_prov_product on silver.product (source_file_id, row_num);
create index if not exists ix_prov_shop_order on silver.shop_order (source_file_id, row_num);
create index if not exists ix_prov_order_item on silver.order_item (source_file_id, row_num);
create index if not exists ix_prov_attribution on silver.attribution (source_file_id, row_num);
create index if not exists ix_prov_commission on silver.commission (source_file_id, row_num);
create index if not exists ix_prov_refund on silver.refund (source_file_id, row_num);
create index if not exists ix_prov_video on silver.video (source_file_id, row_num);
create index if not exists ix_prov_video_snapshot on silver.video_snapshot (source_file_id, row_num);
create index if not exists ix_prov_sample_shipment on silver.sample_shipment (source_file_id, row_num);
create index if not exists ix_prov_sample_item on silver.sample_item (source_file_id, row_num);
create index if not exists ix_prov_goal on silver.goal (source_file_id, row_num);
create index if not exists ix_prov_contract on silver.contract (source_file_id, row_num);
create index if not exists ix_prov_contract_allocation on silver.contract_allocation (source_file_id, row_num);
