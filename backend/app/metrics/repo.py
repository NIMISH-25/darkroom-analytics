"""SQL data layer. Reads gold views (plus meta.dataset_revision / meta.ingest_run for health and
app.creator_note for notes). Everything returns plain dicts so the service layer can be tested with a
stub implementing the same methods.

One PgRepo instance serves one request on ONE connection (REPEATABLE READ, read-only), so the
revision and every number in a response come from the same snapshot. Functions of the dataset
revision only (brands, freshness, creator performance, ...) are cached per revision.
"""
from __future__ import annotations

from datetime import date

import psycopg

from app.metrics import cache
from app.metrics.conn import current_cutoff


def month_start(month: str) -> date:
    return date(int(month[:4]), int(month[5:7]), 1)


def _d(s):
    return s if isinstance(s, date) else date.fromisoformat(s)


class PgRepo:
    def __init__(self, conn):
        self.conn = conn
        self._rk = None

    def _q(self, sql: str, params: tuple | list = ()) -> list[dict]:
        return list(self.conn.execute(sql, params).fetchall())

    # ---------- revision ----------
    def revision_key(self):
        if self._rk is None:
            rows = self._q("SELECT revision_id, created_at FROM meta.dataset_revision ORDER BY revision_id DESC LIMIT 1")
            self._rk = (int(rows[0]["revision_id"]), rows[0]["created_at"].isoformat()) if rows else (0, None)
        return self._rk

    def revision(self) -> int:
        return self.revision_key()[0]

    def _rev(self, name, args, fn):
        """Cache a function of (dataset revision, args) across requests."""
        return cache.rev_cached(self.revision_key(), (name, args, current_cutoff()), fn)  # gold views read app.cutoff

    # ---------- reference data (revision-cached) ----------
    def brands(self) -> list[dict]:
        return self._rev("brands", (), lambda: self._q(
            "SELECT brand_id, name, reporting_tz AS timezone FROM silver.brand ORDER BY brand_id"))

    def months(self) -> list[str]:
        def go():
            rows = self._q(
                "SELECT DISTINCT to_char(month::date, 'YYYY-MM') AS m FROM gold.goal_progress "
                "UNION SELECT DISTINCT to_char(month::date, 'YYYY-MM') FROM gold.creator_performance ORDER BY 1")
            return [r["m"] for r in rows]
        return self._rev("months", (), go)

    def freshness(self, brand_id=None) -> list[dict]:
        # gold.source_freshness(brand_id, source_type, state, coverage_through, expected_through, last_ingested_at, message)
        def go():
            if brand_id:
                return self._q("SELECT * FROM gold.source_freshness WHERE brand_id = %s ORDER BY 1,2", (brand_id,))
            return self._q("SELECT * FROM gold.source_freshness ORDER BY 1,2")
        return self._rev("freshness", (brand_id,), go)

    def creators(self, brand_id, month) -> list[dict]:
        # gold.creator_performance(brand_id, creator_id, month, handle, contract_type, last_post_date, coverage_status,
        #   retainer_cost, commission_cost, sample_cost, ...)
        return self._rev("creators", (brand_id, month), lambda: self._q(
            "SELECT * FROM gold.creator_performance WHERE brand_id = %s AND month = %s ORDER BY handle",
            (brand_id, month_start(month))))

    def creator_map(self, brand_id, month) -> dict:
        return self._rev("creator_map", (brand_id, month),
                         lambda: {c["creator_id"]: c for c in self.creators(brand_id, month)})

    def creator_handles(self) -> dict:
        return self._rev("handles", (), lambda: {
            r["creator_id"]: r["handle"] for r in self._q("SELECT creator_id, handle FROM silver.creator")})

    def goals(self, brand_id, month) -> list[dict]:
        # gold.goal_progress + plan file path for the target evidence record
        def go():
            where, p = ["g.month = %s"], [month_start(month)]
            if brand_id:
                where.append("g.brand_id = %s"); p.append(brand_id)
            return self._q(
                "SELECT g.*, sf.path AS plan_file FROM gold.goal_progress g "
                "LEFT JOIN bronze.source_file sf ON sf.source_file_id = g.source_file_id "
                f"WHERE {' AND '.join(where)} ORDER BY g.brand_id, g.metric_key, g.scope", p)
        return self._rev("goals", (brand_id, month), go)

    def sample_rows(self, brand_id, creator_id, status=None) -> list[dict]:
        # gold.sample_funnel(brand_id, sample_id, creator_id, handle, product_sku, sent_date, delivered_date, state,
        #   matched_video_id, delivery_to_video_days, mature, video_coverage_complete, source_file, source_locator, row_num)
        def go():
            where, p = ["true"], []
            if brand_id:
                where.append("brand_id = %s"); p.append(brand_id)
            return self._q(
                f"SELECT * FROM gold.sample_funnel WHERE {' AND '.join(where)} ORDER BY sent_date, sample_id", p)
        rows = self._rev("samples", (brand_id,), go)
        if creator_id:
            rows = [r for r in rows if r["creator_id"] == creator_id]
        if status:
            rows = [r for r in rows if r["state"] == status]
        return rows

    def sample_costs(self, brand_id=None) -> dict:
        """shipment_id -> cost (None when unknown)."""
        def go():
            sql, p = "SELECT brand_id, shipment_id, cost FROM gold.sample_cost_line", ()
            if brand_id:
                sql, p = sql + " WHERE brand_id = %s", (brand_id,)
            return {(r["brand_id"], r["shipment_id"]): r["cost"] for r in self._q(sql, p)}
        return self._rev("sample_costs", (brand_id,), go)

    def attention(self, brand_id=None) -> list[dict]:
        # gold.needs_attention(brand_id, kind, entity_ref, reason, title, period_start, period_end, creator_id, days_waiting)
        def go():
            if brand_id:
                return self._q("SELECT * FROM gold.needs_attention WHERE brand_id = %s ORDER BY 1,2,3", (brand_id,))
            return self._q("SELECT * FROM gold.needs_attention ORDER BY 1,2,3")
        return self._rev("attention", (brand_id,), go)

    # ---------- data health (brand scoped) ----------
    def last_run_id(self):
        """Latest ingest run id (not revision-cached: a replay adds a run but no revision)."""
        if not hasattr(self, "_lri"):
            rows = self._q("SELECT max(run_id) AS r FROM meta.ingest_run")
            self._lri = rows[0]["r"] if rows else None
        return self._lri

    def shared_types(self) -> set:
        """Source types tracked by ONE cross-brand file (scope_key 'all'): only roster and samples (plans are per brand)."""
        return {"roster", "samples"}

    def runs(self, brand_id=None) -> list[dict]:
        def go():
            if not brand_id:
                return self._q("SELECT run_id, started_at, status, files_failed FROM meta.ingest_run "
                               "ORDER BY started_at DESC LIMIT 20")
            return self._q(
                "SELECT r.run_id, r.started_at, "
                "CASE WHEN count(*) FILTER (WHERE f.status IN ('rejected','quarantined')) > 0 THEN r.status "
                "     WHEN r.status = 'failed' THEN 'failed' ELSE 'succeeded' END AS status, "
                "count(*) FILTER (WHERE f.status IN ('rejected','quarantined'))::int AS files_failed "
                "FROM meta.ingest_run r JOIN bronze.source_file f ON f.run_id = r.run_id "
                "AND f.scope_key IN (%s, 'all') GROUP BY r.run_id, r.started_at, r.status "
                "ORDER BY r.started_at DESC LIMIT 20", (brand_id,))
        return self._rev("runs", (brand_id, self.last_run_id()), go)

    def failed_files(self, brand_id=None) -> list[dict]:
        def go():
            sql = ("SELECT f.run_id, f.path AS file_name, f.error, f.scope_key, f.source_type, f.status "
                   "FROM bronze.source_file f WHERE f.status IN ('rejected','quarantined')")
            p: tuple = ()
            if brand_id:
                sql, p = sql + " AND f.scope_key IN (%s, 'all')", (brand_id,)
            return self._q(sql + " ORDER BY f.ingested_at DESC, f.source_file_id DESC LIMIT 100", p)
        return self._rev("failed", (brand_id, self.last_run_id()), go)

    def _cols(self, schema, table) -> set:
        return self._rev("cols", (schema, table), lambda: {r["column_name"] for r in self._q(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s", (schema, table))})

    def excluded_notes(self) -> list[dict]:
        """Rows left out of loaded files, per brand and source (migration 018); empty until it exists."""
        def go():
            out = []
            cols = self._cols("meta", "quality_issue")
            if "brand_id" in cols and "code" in cols:
                out = self._q("SELECT brand_id, source_type, max(message) AS message, count(*)::int AS n FROM meta.quality_issue "
                              "WHERE code = 'rows_excluded' AND state = 'open' AND brand_id IS NOT NULL "
                              "GROUP BY brand_id, source_type")
            if not out and self._q("SELECT to_regclass('gold.excluded_rows_by_brand') AS t")[0]["t"]:
                for r in self._q("SELECT * FROM gold.excluded_rows_by_brand"):
                    n = next((r[k] for k in ("excluded_rows", "rows_excluded", "n_excluded", "n", "count") if k in r and r[k] is not None), None)
                    if n:
                        out.append({"brand_id": r.get("brand_id"), "source_type": r.get("source_type"), "message": None, "n": int(n)})
            return out
        return self._rev("excluded_notes", (self.last_run_id(),), go)

    def files_with_exclusions(self, brand_id=None) -> list[dict]:
        def go():
            if "excluded_rows" not in self._cols("bronze", "source_file"):
                return []
            sql = ("SELECT f.run_id, f.path AS file_name, f.scope_key, f.source_type, f.excluded_rows AS rows_excluded "
                   "FROM bronze.source_file f WHERE f.excluded_rows > 0 AND f.status = 'accepted'")
            p: tuple = ()
            if brand_id:
                sql, p = sql + " AND f.scope_key IN (%s, 'all')", (brand_id,)
            return self._q(sql + " ORDER BY f.ingested_at DESC, f.source_file_id DESC LIMIT 100", p)
        return self._rev("files_excl", (brand_id, self.last_run_id()), go)

    def open_issue_count(self, brand_id=None) -> int:
        """Open quality issues of the brand plus shared ones (brand_id null); defensive if brand_id is absent."""
        def go():
            cols = {r["column_name"] for r in self._q(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='meta' AND table_name='quality_issue'")}
            if brand_id and "brand_id" in cols:
                return self._q("SELECT count(*) AS n FROM meta.quality_issue WHERE state = 'open' "
                               "AND (brand_id = %s OR brand_id IS NULL)", (brand_id,))[0]["n"]
            return self._q("SELECT count(*) AS n FROM meta.quality_issue WHERE state = 'open'")[0]["n"]
        return self._rev("issues", (brand_id, self.last_run_id()), go)

    def unresolved_identities(self, brand_id=None) -> list[dict]:
        def go():
            sql, p = "SELECT * FROM gold.unresolved_identity", ()
            if brand_id:
                sql, p = sql + " WHERE brand_id = %s", (brand_id,)
            return self._q(sql, p)
        return self._rev("unresolved", (brand_id,), go)

    # ---------- request-parameter dependent (not cached across requests; the response cache covers them) ----------
    def sales_rows(self, brand_id, creator_id, month, cutoff) -> list[dict]:
        # gold.sales_line + refunds re-derived from gold.refund_line at the REQUEST cutoff
        # (rule 4: only refunds with completed_local_date <= cutoff restate the original month).
        ms, co = month_start(month), _d(cutoff)
        where, p = ["sl.month = %s", "sl.local_date <= %s"], [ms, co]
        rwhere, rp = ["month = %s", "status IN ('completed','partial')", "completed_local_date <= %s"], [ms, co]
        if brand_id:
            where.append("sl.brand_id = %s"); p.append(brand_id)
            rwhere.append("brand_id = %s"); rp.append(brand_id)
        if creator_id:
            where.append("sl.creator_id = %s"); p.append(creator_id)
        rows = self._q(
            "SELECT sl.*, r.n AS _rn, r.n_unknown AS _ru, r.known_sum AS _rs FROM gold.sales_line sl "
            "LEFT JOIN (SELECT shop_id, order_id, line_id, count(*) n, "
            "count(*) FILTER (WHERE merch_amount IS NULL) n_unknown, sum(merch_amount) known_sum "
            f"FROM gold.refund_line WHERE {' AND '.join(rwhere)} "
            "GROUP BY 1,2,3) r USING (shop_id, order_id, line_id) "
            f"WHERE {' AND '.join(where)} ORDER BY sl.source_file, sl.row_num, sl.line_id", rp + p)
        for r in rows:
            n, nu, ks = r.pop("_rn"), r.pop("_ru"), r.pop("_rs")
            if not r["eligible"]:
                r["refunded"], r["refund_state"], r["net"] = None, None, None
            elif n is None:
                r["refunded"], r["refund_state"], r["net"] = 0, "none", r["gmv"]
            elif nu:
                r["refunded"], r["refund_state"], r["net"] = None, "partial", None
            else:
                r["refunded"], r["refund_state"] = ks, "complete"
                r["net"] = None if r["gmv"] is None else r["gmv"] - ks
        return rows

    def video_rows(self, brand_id, creator_id, month, cutoff) -> list[dict]:
        # gold.video_activity(brand_id, video_id, creator_id, month, local_date, qualifies, source_file, source_locator, row_num)
        where, p = ["month = %s", "local_date <= %s"], [month_start(month), _d(cutoff)]
        if brand_id:
            where.append("brand_id = %s"); p.append(brand_id)
        if creator_id:
            where.append("creator_id = %s"); p.append(creator_id)
        return self._q(
            f"SELECT * FROM gold.video_activity WHERE {' AND '.join(where)} ORDER BY source_file, row_num", p)

    # ---------- notes (app.creator_note; table is created by migration 007) ----------
    def notes(self, brand_id, creator_id) -> list[dict]:
        return self._q(
            "SELECT note_id, brand_id, creator_id, author, body, created_at FROM app.creator_note "
            "WHERE brand_id = %s AND creator_id = %s AND deleted_at IS NULL ORDER BY created_at DESC, note_id DESC",
            (brand_id, creator_id))
