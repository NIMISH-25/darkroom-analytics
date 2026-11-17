-- Brand-scope quality issues. Files for roster/samples have scope_key 'all' (shared); plans and every other source
-- are per brand (scope_key = brand_id). Backfill brand_id from the source file, then add missing file-failure issues.
update meta.quality_issue q
set brand_id = f.scope_key
from bronze.source_file f
where q.source_file_id = f.source_file_id and q.brand_id is null
  and f.scope_key in (select brand_id from silver.brand);

insert into meta.quality_issue (code, entity_ref, source_file_id, brand_id, source_type, severity, message, origin)
select 'file_' || f.status, coalesce(f.path, f.source_type || '/' || f.scope_key), f.source_file_id,
       case when f.scope_key in (select brand_id from silver.brand) then f.scope_key end,
       f.source_type, case when f.status = 'quarantined' then 'warn' else 'error' end,
       coalesce(f.error, 'file ' || f.status), 'file'
from bronze.source_file f
where f.status in ('rejected', 'quarantined')
  and not exists (select 1 from meta.quality_issue q where q.origin = 'file'
                  and q.code = 'file_' || f.status and q.entity_ref = coalesce(f.path, f.source_type || '/' || f.scope_key));
