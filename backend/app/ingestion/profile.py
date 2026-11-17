"""Read-only profiling of a batch folder (no DB writes)."""
from __future__ import annotations

import json
from pathlib import Path

from .parsers import parse_file, sha256_bytes


def profile_batch(batch_dir: Path) -> str:
    manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8-sig"))
    lines = [f"Profile of {manifest.get('batch_id')} (as_of {manifest.get('as_of')}), {len(manifest.get('files', []))} manifest files"]
    for e in manifest.get("files", []):
        p = batch_dir / e["path"]
        if not p.is_file():
            lines.append(f"  MISSING {e['path']}")
            continue
        data = p.read_bytes()
        r = parse_file(e["source_type"], p, data)
        extra = f" unknown_headers={r.unknown_headers}" if r.unknown_headers else ""
        alias = {k: v for k, v in r.mapping.items() if k != v}
        lines.append(f"  {r.status.upper():11} {e['path']} rows={len(r.records)} sha={sha256_bytes(data)[:10]}"
                     f"{extra}{' aliased=' + str(alias) if alias else ''}{' error=' + r.error if r.error else ''}")
    return "\n".join(lines)
