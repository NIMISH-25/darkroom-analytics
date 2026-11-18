"""Ingest one batch folder: register files by sha256, parse, store bronze, quarantine/reject, rebuild silver, publish."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from .parsers import PARSER_VERSION, Parsed, parse_file, row_hash, sha256_bytes
from .silver import BRANDS, rebuild_silver

KINDS = {"orders": "increment", "affiliate_orders": "increment", "returns": "increment",
         "videos_weekly": "increment", "products": "snapshot", "roster": "snapshot",
         "samples": "snapshot", "plans": "snapshot"}
GLOBAL_SCOPE = {"roster", "samples"}
TABLES = ["brand", "creator", "creator_alias", "brand_creator", "product", "shop_order", "order_item", "attribution",
          "commission", "refund", "video", "video_snapshot", "sample_shipment", "sample_item", "goal", "contract",
          "contract_allocation"]


@dataclass
class Report:
    batch_id: str = ""
    as_of: str = ""
    new: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    quarantined: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    unlisted: list = field(default_factory=list)
    issues: dict = field(default_factory=dict)
    revision_id: int | None = None
    revision_created: bool = False

    def render(self) -> str:
        L = [f"Batch {self.batch_id} (as_of {self.as_of})",
             f"  new accepted : {len(self.new)}", f"  unchanged    : {len(self.unchanged)}",
             f"  quarantined  : {len(self.quarantined)}", f"  rejected     : {len(self.rejected)}",
             f"  missing      : {len(self.missing)}",
             f"  rows left out: {sum(n for _, n, _ in self.excluded)}", f"  unlisted     : {len(self.unlisted)}"]
        for p, n, tot in self.excluded:
            L.append(f"    [Rows left out] {p}: {n} of {tot} rows left out; the file stays loaded")
        for title, items in (("Quarantined", self.quarantined), ("Rejected", self.rejected),
                             ("Missing", self.missing), ("Unlisted (ignored)", self.unlisted)):
            for p, e in items:
                L.append(f"    [{title}] {p}: {e}")
        if self.issues:
            L.append("  quality issues (silver): " + ", ".join(f"{k}={v}" for k, v in sorted(self.issues.items())))
        L.append(f"  dataset revision: {self.revision_id} ({'created' if self.revision_created else 'unchanged'})")
        return "\n".join(L)


def _d(v):
    return dt.date.fromisoformat(v) if v else None


def _ts(v):
    if not v:
        return None
    return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def _scope(entry: dict) -> str:
    st = entry["source_type"]
    if st in GLOBAL_SCOPE:
        return "all"
    if entry.get("brand_id"):
        return entry["brand_id"]
    parts = Path(entry["path"]).parts
    if len(parts) >= 2 and st == "products":
        return Path(parts[-1]).stem
    return parts[1] if len(parts) >= 3 else "all"


class _State:
    """Per-batch prefetched lookups: registered files, accepted weekly coverage, known file issues (no per-file SELECT)."""

    def __init__(self, conn) -> None:
        self.files: dict[tuple, tuple] = {}
        self.weekly: dict[str, list[tuple]] = {}
        for fid, st, scope, cs, ce, sha, pv, status, err in conn.execute(
                "select source_file_id, source_type, scope_key, coverage_start, coverage_end, sha256, parser_version, status, error "
                "from bronze.source_file"):
            self.files[(st, scope, cs, ce, sha, pv)] = (fid, status, err)
            if status == "accepted" and st == "videos_weekly":
                self.weekly.setdefault(scope, []).append((fid, cs, ce))
        self.issues: set[tuple] = set(conn.execute(
            "select code, entity_ref from meta.quality_issue where origin='file'").fetchall())

    def overlap(self, scope, start, end):
        for fid, cs, ce in self.weekly.get(scope, []):
            if cs <= end and ce >= start:
                return (fid, cs, ce)
        return None


def _insert_file(conn, st: _State, run_id, batch_id, entry, scope, start, end, sha, status, error, upd, nrows, path, excluded=0):
    """Insert with ON CONFLICT DO NOTHING RETURNING; returns the new id, or None when the file is a replay."""
    row = conn.execute(
        "insert into bronze.source_file (batch_id, run_id, path, source_type, scope_key, coverage_start, coverage_end, kind,"
        " sha256, parser_version, status, error, row_count, src_updated_at, excluded_rows) values "
        "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing returning source_file_id",
        (batch_id, run_id, path, entry["source_type"], scope, start, end, KINDS.get(entry["source_type"], "increment"), sha,
         PARSER_VERSION, status, error, nrows, upd, excluded)).fetchone()
    if row is None:
        return None
    st.files[(entry["source_type"], scope, start, end, sha, PARSER_VERSION)] = (row[0], status, error)
    if status == "accepted" and entry["source_type"] == "videos_weekly":
        st.weekly.setdefault(scope, []).append((row[0], start, end))
    return row[0]


def _issue(conn, st: _State, code, ref, sev, msg, fid=None, brand=None, src=None):
    if (code, ref) not in st.issues:
        conn.execute("insert into meta.quality_issue (code, entity_ref, source_file_id, brand_id, source_type, severity, message, origin)"
                     " values (%s,%s,%s,%s,%s,%s,%s,'file')", (code, ref, fid, brand, src, sev, msg))
        st.issues.add((code, ref))


_BRANDS = {b[0] for b in BRANDS}


def _brand_scope(scope):
    return scope if scope in _BRANDS else None


def _file_issue(conn, st, status, path, error, fid, scope, source_type):
    """Failed files become quality issues attributed to the file's brand scope (NULL for shared 'all' scope)."""
    code = {"rejected": "file_rejected", "quarantined": "file_quarantined", "missing": "file_missing"}[status]
    _issue(conn, st, code, path, "error" if status != "quarantined" else "warn", error or code, fid,
           _brand_scope(scope), source_type)


def _record_excluded(conn, st, fid, path, scope, source_type, res) -> None:
    """Developer table of every bad row plus one plain quality issue per file (code rows_excluded)."""
    with conn.cursor() as cur:
        cur.executemany("insert into bronze.excluded_row (source_file_id, row_num, reason_code, detail) values (%s,%s,%s,%s) "
                        "on conflict do nothing", [(fid, rn, code, detail) for rn, code, detail in res.excluded])
    n, total = len(res.excluded), res.rows_total
    reasons = sorted({c for _, c, _ in res.excluded})
    _issue(conn, st, "rows_excluded", path, "warn",
           f"{n} of {total} rows in {path} were left out ({', '.join(reasons)}); the rest of the file is loaded, totals may be low.",
           fid, _brand_scope(scope), source_type)


def _copy_records(conn, fid, records) -> None:
    with conn.cursor() as cur:
        with cur.copy("copy bronze.source_record (source_file_id, row_num, payload, row_hash) from stdin") as cp:
            for rn, p in records:
                cp.write_row((fid, rn, Jsonb(p), row_hash(p)))


def digest(conn: psycopg.Connection, as_of: dt.date) -> dict:
    summ: dict = {"as_of": str(as_of), "tables": {}}
    for t in TABLES:
        n, d = conn.execute(
            f"select count(*), md5(coalesce(string_agg(x, ',' order by x), '')) from "
            f"(select (to_jsonb(t) - 'source_file_id' - 'row_num')::text x from silver.{t} t) q").fetchone()
        summ["tables"][t] = {"rows": n, "digest": d}
    summ["quality"] = conn.execute(
        "select md5(coalesce(string_agg(x, ',' order by x), '')) from (select concat_ws('|', code, entity_ref, severity, message, origin) x "
        "from meta.quality_issue) q").fetchone()[0]
    summ["files"] = conn.execute(
        "select md5(coalesce(string_agg(x, ',' order by x), '')) from (select concat_ws('|', source_type, scope_key, coverage_start, coverage_end, sha256, status) x "
        "from bronze.source_file) q").fetchone()[0]
    return summ


def _analyze(conn: psycopg.Connection) -> None:
    """Refresh planner statistics after a bulk load, including materialized views (cannot run inside the publish transaction)."""
    conn.autocommit = True
    try:
        tables = conn.execute(
            "select n.nspname, c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where c.relkind in ('r','m') and n.nspname in ('bronze','silver','meta','gold')").fetchall()
        for sch, t in tables:
            conn.execute(f'analyze "{sch}"."{t}"')
    finally:
        conn.autocommit = False


def ingest_batch(conn: psycopg.Connection, batch_dir: Path) -> Report:
    batch_dir = Path(batch_dir)
    mpath = batch_dir / "manifest.json"
    if not mpath.is_file():
        raise SystemExit(f"manifest.json not found in {batch_dir}")
    manifest = json.loads(mpath.read_text(encoding="utf-8-sig"))
    rep = Report(batch_id=str(manifest.get("batch_id", batch_dir.name)), as_of=str(manifest.get("as_of", "")))
    as_of = _d(manifest.get("as_of"))
    if as_of is None:
        raise SystemExit("manifest.json lacks as_of")
    run_id = conn.execute("insert into meta.ingest_run (batch_id, status) values (%s,'running') returning run_id",
                          (rep.batch_id,)).fetchone()[0]
    conn.commit()
    listed: set[str] = set()
    n_new = 0
    st = _State(conn)
    try:
        for entry in manifest.get("files", []):
            path = str(entry.get("path", ""))
            listed.add(Path(path).as_posix())
            if entry.get("source_type") not in KINDS or not path:
                sha = sha256_bytes(json.dumps(entry, sort_keys=True).encode())
                if _insert_file(conn, st, run_id, rep.batch_id, {"source_type": "invalid"}, "all", None, None, sha,
                                "rejected", "invalid manifest entry", None, None, path) is not None:
                    n_new += 1
                rep.rejected.append((path or "(no path)", "invalid manifest entry"))
                _file_issue(conn, st, "rejected", path or "(no path)", "invalid manifest entry", None, "all", None)
                conn.commit()
                continue
            scope = _scope(entry)
            start, end = _d(entry.get("period_start")), _d(entry.get("period_end"))
            upd = _ts(entry.get("src_updated_at"))
            fpath = batch_dir / path
            if not fpath.is_file():
                sha = sha256_bytes(f"missing:{path}".encode())
                if _insert_file(conn, st, run_id, rep.batch_id, entry, scope, start, end, sha, "rejected",
                                "file listed in manifest but missing", upd, None, path) is not None:
                    n_new += 1
                rep.missing.append((path, "listed in manifest but file does not exist"))
                _file_issue(conn, st, "missing", path, "file listed in manifest but missing", None, scope, entry["source_type"])
                conn.commit()
                continue
            data = fpath.read_bytes()
            sha = sha256_bytes(data)
            key = (entry["source_type"], scope, start, end, sha, PARSER_VERSION)
            prev = st.files.get(key)
            if prev is not None:
                if prev[1] == "accepted":
                    rep.unchanged.append((path, "replay"))
                elif prev[1] == "rejected":
                    rep.rejected.append((path, f"{prev[2]} (previously recorded)"))
                    _file_issue(conn, st, "rejected", path, prev[2], prev[0], scope, entry["source_type"])
                else:
                    rep.quarantined.append((path, f"{prev[2]} (previously recorded)"))
                    _file_issue(conn, st, "quarantined", path, prev[2], prev[0], scope, entry["source_type"])
                continue
            res: Parsed = parse_file(entry["source_type"], fpath, data)
            status, error = res.status, res.error
            if status == "accepted" and KINDS[entry["source_type"]] == "increment" and (start is None or end is None):
                status, error = "rejected", "manifest entry lacks period_start/period_end"
            if status == "accepted" and entry["source_type"] == "videos_weekly":
                ov = st.overlap(scope, start, end)
                if ov:
                    status, error = "quarantined", f"period {start}..{end} overlaps accepted file {ov[0]} ({ov[1]}..{ov[2]})"
            fid = _insert_file(conn, st, run_id, rep.batch_id, entry, scope, start, end, sha, status, error, upd,
                               len(res.records) if status == "accepted" else None, path,
                               len(res.excluded) if status == "accepted" else 0)
            if fid is None:  # replay (concurrent writer registered this exact file first)
                rep.unchanged.append((path, "replay"))
                conn.commit()
                continue
            n_new += 1
            if status == "accepted":
                _copy_records(conn, fid, res.records)
                if res.unknown_headers:
                    _issue(conn, st, "unknown_extra_column", path, "info", f"extra columns kept in bronze only: {res.unknown_headers}", fid, _brand_scope(scope), entry["source_type"])
                rep.new.append((path, f"{len(res.records)} rows"))
                if res.excluded:
                    _record_excluded(conn, st, fid, path, scope, entry["source_type"], res)
                    rep.excluded.append((path, len(res.excluded), res.rows_total))
            elif status == "quarantined":
                rep.quarantined.append((path, error))
                _file_issue(conn, st, "quarantined", path, error, fid, scope, entry["source_type"])
            else:
                rep.rejected.append((path, error))
                _file_issue(conn, st, "rejected", path, error, fid, scope, entry["source_type"])
            conn.commit()
        for f in sorted(p for p in batch_dir.rglob("*") if p.is_file() and p.name != "manifest.json"):
            rel = f.relative_to(batch_dir).as_posix()
            if rel not in listed:
                rep.unlisted.append((rel, "not in manifest; ignored"))
                parts = rel.split("/")
                _issue(conn, st, "unlisted_file", rel, "warn", "File present in batch folder but absent from manifest; ignored.",
                       None, _brand_scope(parts[1].split(".")[0]) if len(parts) > 1 else None)
        conn.commit()
        have_rev = conn.execute("select count(*) from meta.dataset_revision").fetchone()[0] > 0
        did_rebuild = bool(n_new or rep.unlisted or not have_rev)
        if did_rebuild:
            with conn.transaction():
                rebuild_silver(conn)
                prev_asof = conn.execute("select max(as_of) from meta.dataset_revision").fetchone()[0]
                eff = max(as_of, prev_asof) if prev_asof else as_of
                summ = digest(conn, eff)
                last = conn.execute("select revision_id, summary from meta.dataset_revision order by revision_id desc limit 1").fetchone()
                if last is None or last[1] != summ:
                    rep.revision_id = conn.execute(
                        "insert into meta.dataset_revision (as_of, summary) values (%s,%s) returning revision_id",
                        (eff, Jsonb(summ))).fetchone()[0]
                    rep.revision_created = True
                    if conn.execute("select to_regprocedure('gold.refresh_materialized()')").fetchone()[0] is not None:
                        conn.execute("select gold.refresh_materialized()")
                else:
                    rep.revision_id = last[0]
        else:
            rep.revision_id = conn.execute("select max(revision_id) from meta.dataset_revision").fetchone()[0]
        rep.issues = dict(conn.execute("select code, count(*) from meta.quality_issue where state='open' group by code").fetchall())
        failed = len(rep.rejected) + len(rep.quarantined) + len(rep.missing)
        status = "succeeded" if failed == 0 else "partial"
        if n_new:
            conn.execute("update meta.ingest_run set finished_at=now(), status=%s, files_failed=%s, counts=%s where run_id=%s",
                         (status, failed, Jsonb({"new": len(rep.new), "unchanged": len(rep.unchanged), "rejected": len(rep.rejected),
                                                 "quarantined": len(rep.quarantined), "missing": len(rep.missing)}), run_id))
        else:
            conn.execute("delete from meta.ingest_run where run_id=%s", (run_id,))
        conn.commit()
        if did_rebuild:
            _analyze(conn)
    except BaseException:
        conn.rollback()
        conn.execute("update meta.ingest_run set finished_at=now(), status='failed' where run_id=%s", (run_id,))
        conn.commit()
        raise
    return rep
