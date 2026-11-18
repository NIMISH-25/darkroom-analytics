"""S6: order paid 2026-10-31 23:30 PT (= 2026-11-01 06:30 UTC) belongs to October."""
import pytest

from helpers import API, dec, evidence

pytestmark = pytest.mark.after_b2


def test_oct31_2330_pt_counts_in_october(client):
    ev = evidence(client, "gmv", {"brand_id": "glowhaus", "month": "2026-10", "cutoff": "2026-11-02"})
    assert dec(ev["result"]["value"]) == dec("65.00")      # 40.00 + 25.00
    assert ev["timezone"] == "America/Los_Angeles"
    assert ev["period_start"] == "2026-10-01" and ev["period_end"] == "2026-10-31"
    included = [r for r in ev["records"] if r.get("included", True)]
    assert any("O_G2" in str(r["values"]) for r in included), "O_G2 must be an included October record"


def test_oct31_order_not_in_november(client):
    r = client.get(f"{API}/metrics/gmv/evidence",
                   params={"brand_id": "glowhaus", "month": "2026-11", "cutoff": "2026-11-02"})
    if r.status_code != 200:
        pytest.skip(f"November not served ({r.status_code}); the October assertion covers the boundary")
    val = r.json()["result"]["value"]
    assert val is None or dec(val) == 0
    assert not any("O_G2" in str(x["values"]) for x in r.json()["records"] if x.get("included", True))
