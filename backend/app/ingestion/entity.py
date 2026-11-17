"""Creator identity resolution: stable ids first, then explicit (observed, dated) handle aliases.

A wrong merge is worse than an unresolved row: ambiguous or unknown handles resolve to None.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

NAMESPACE = "handle"


def norm_handle(h: object) -> str | None:
    if h is None:
        return None
    s = str(h).strip().lower().lstrip("@").strip()
    return s or None


def blank(v: object) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


@dataclass
class Observation:
    creator_id: str
    handle: str
    observed: dt.datetime  # when the source said so (file version time)


@dataclass
class CreatorIndex:
    obs: list[Observation] = field(default_factory=list)
    ids: dict[str, dt.datetime] = field(default_factory=dict)  # creator_id -> latest observation
    _alias: dict[str, set[str]] = field(default_factory=dict)
    _alias_from: dict[tuple[str, str], dt.date] = field(default_factory=dict)
    _latest_handle: dict[str, tuple[dt.datetime, str]] = field(default_factory=dict)

    def see(self, creator_id: object, handle: object, observed: dt.datetime) -> None:
        if blank(creator_id):
            return
        cid = str(creator_id).strip()
        if cid not in self.ids or observed > self.ids[cid]:
            self.ids[cid] = observed
        a = norm_handle(handle)
        if a:
            self._alias.setdefault(a, set()).add(cid)
            k = (a, cid)
            d = observed.date()
            if k not in self._alias_from or d < self._alias_from[k]:
                self._alias_from[k] = d
            cur = self._latest_handle.get(cid)
            if cur is None or observed >= cur[0]:
                self._latest_handle[cid] = (observed, str(handle).strip())

    def resolve(self, creator_id: object, handle: object) -> str | None:
        if not blank(creator_id):
            return str(creator_id).strip()
        a = norm_handle(handle)
        if a is None:
            return None
        c = self._alias.get(a, set())
        return next(iter(c)) if len(c) == 1 else None

    def is_ambiguous(self, handle: object) -> bool:
        a = norm_handle(handle)
        return a is not None and len(self._alias.get(a, set())) > 1

    def latest_handle(self, creator_id: str) -> str | None:
        v = self._latest_handle.get(creator_id)
        return v[1] if v else None

    def alias_rows(self) -> list[tuple]:
        rows = []
        for a, cids in sorted(self._alias.items()):
            if len(cids) == 1:
                c = next(iter(cids))
                rows.append((NAMESPACE, a, self._alias_from[(a, c)], c, False, 1))
            else:
                vf = min(self._alias_from[(a, c)] for c in cids)
                rows.append((NAMESPACE, a, vf, None, False, len(cids)))
        return rows
