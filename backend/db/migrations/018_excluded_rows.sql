-- Faulty rows are left out on their own (ruling 7): the file stays accepted, the brand stays current.
alter table bronze.source_file add column if not exists excluded_rows int not null default 0;

create table if not exists bronze.excluded_row (
  source_file_id bigint not null references bronze.source_file,
  row_num        int not null,
  reason_code    text not null,
  detail         text,
  primary key (source_file_id, row_num)
);

-- One row per accepted file with left-out rows; brand_id is NULL for shared trackers (roster, samples).
create or replace view gold.excluded_rows_by_brand as
select case when f.scope_key in (select brand_id from silver.brand) then f.scope_key end as brand_id,
       f.source_type,
       f.path as file_label,
       f.excluded_rows as rows_excluded,
       f.row_count + f.excluded_rows as rows_total,
       f.source_file_id
from bronze.source_file f
where f.status = 'accepted' and f.excluded_rows > 0;
