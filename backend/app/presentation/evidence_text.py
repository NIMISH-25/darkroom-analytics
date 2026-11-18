"""Plain-English evidence sheet text, built server-side from the metric registry, exclusions and counts."""
from __future__ import annotations

from app.presentation.humanize import GENERIC, column_label, plain_text

_NET = {"net_attributed_sales", "creator_net_sales", "creator_sales_after_costs"}

MEANS = {
    "gmv": lambda w: f"The total value of paid orders for {w} in the month so far, whether or not a creator drove them.",
    "creator_attributed_gmv": lambda w: f"The part of {w}'s sales that can be traced to a known creator through the affiliate records.",
    "net_attributed_sales": lambda w: f"What {w}'s creator-driven sales are worth after the money returned to customers is taken off.",
    "creator_net_sales": lambda w: f"What {w}'s sales are worth after refunds.",
    "videos": lambda w: f"How many videos with a known creator and a publish date {w} published in the month so far.",
    "creator_videos": lambda w: f"How many qualifying videos {w} published in the month so far.",
    "active_creators": lambda w: f"How many different creators posted at least one qualifying video for {w} in the month so far.",
    "sample_conversion_rate": lambda w: f"Of the free samples sent by {w} that have had at least 30 days to work, the share that turned into a video.",
    "creator_sales_after_costs": lambda w: f"What {w} earns after subtracting the retainer, commission and sample costs from net sales.",
    "goal_projection": lambda w: f"Where {w}'s month is heading if the pace so far continues, compared with the target.",
    "decomposition": lambda w: f"How {w}'s sales changed between the two periods, split into more creators, more videos per creator and more sales per video.",
    "creator_concentration": lambda w: f"How much of {w}'s creator-driven sales come from its few biggest creators.",
    "retainer_cadence": lambda w: f"How many posts {w}'s retainer creators delivered compared with what their contracts expect.",
    "portfolio_pacing": lambda w: f"The combined goal, pace and projection of every brand for the month.",
}
MATTERS = {
    "gmv": "It is the top line the monthly sales goal is judged against.",
    "creator_attributed_gmv": "It shows how much of the revenue creators actually drive, which is what you pay them for.",
    "net_attributed_sales": "It is the sales figure creator pay and return on spend should be judged on.",
    "creator_net_sales": "It is the revenue side of this creator's economics.",
    "videos": "Content volume is the leading signal for later sales.",
    "creator_videos": "It shows whether the creator is delivering the content they were booked for.",
    "active_creators": "It shows how wide the creator bench is, beyond total video count.",
    "sample_conversion_rate": "It tells you whether sending free product pays back in content.",
    "creator_sales_after_costs": "It tells you whether the relationship makes money, not just revenue.",
    "goal_projection": "It tells you early whether a goal will be missed, while there is still time to act.",
    "decomposition": "It points to which lever moved the number. It describes the change; it does not prove why it happened.",
    "creator_concentration": "A high share means the brand depends on a handful of people.",
    "retainer_cadence": "It shows which retainers to chase or renegotiate.",
    "portfolio_pacing": "It shows whether the whole portfolio is on track, not just single brands.",
}
HOW = {
    "gmv": "Adds up the amount paid on every order line that was paid, is not a free sample and was not cancelled.",
    "creator_attributed_gmv": "Adds up the paid order lines that the affiliate records tie to a creator on the brand's roster.",
    "net_attributed_sales": "Takes the creator-driven sales and subtracts refunds that were completed by the cutoff date.",
    "creator_net_sales": "Takes this creator's sales and subtracts refunds that were completed by the cutoff date.",
    "videos": "Counts each video once if it has a known creator and a publish date in the month.",
    "creator_videos": "Counts this creator's videos once each if they have a publish date in the month.",
    "active_creators": "Counts each creator once if they published at least one qualifying video in the month.",
    "sample_conversion_rate": "Looks at samples delivered at least 30 days ago and divides those that led to a video by those that led to a video or did not.",
    "creator_sales_after_costs": "Starts from net sales and subtracts the prorated retainer, the commission and the cost of samples sent.",
    "goal_projection": "Takes the amount so far, divides by the days gone by and scales to the full month.",
    "decomposition": "Compares the same days of the previous month and splits the difference fairly between the three drivers.",
    "creator_concentration": "Ranks creators by their sales and shows what share the top creators hold.",
    "retainer_cadence": "Compares posts published with the posts each contract expects for the months in view.",
    "portfolio_pacing": "Adds the brands' goals, projections and required daily pace.",
}
EXCL = {
    "not_eligible": lambda e, w: f"{e['count']} order {'line was' if e['count'] == 1 else 'lines were'} cancelled, unpaid or a free sample and {'is' if e['count'] == 1 else 'are'} not counted.",
    "non_usd_currency": lambda e, w: f"{e['count']} {'order' if e['count'] == 1 else 'orders'} paid in {e.get('currency') or 'another currency'}"
                                    + (f" ({e['amount_label']})" if e.get("amount_label") else "") + " are left out and not converted to dollars.",
    "no_creator_attribution": lambda e, w: f"{e['count']} order {'line has' if e['count'] == 1 else 'lines have'} no creator attached, so {'it counts' if e['count'] == 1 else 'they count'} toward total sales but not toward any creator.",
    "creator_creator_unresolved": lambda e, w: f"{e['count']} order {'line points' if e['count'] == 1 else 'lines point'} to a creator who is not on {w}'s roster.",
    "creator_unresolved": lambda e, w: f"{e['count']} order {'line points' if e['count'] == 1 else 'lines point'} to a creator who is not on {w}'s roster.",
    "creator_conflict": lambda e, w: f"{e['count']} order {'line is' if e['count'] == 1 else 'lines are'} claimed by two creators and left out.",
    "other_bucket": lambda e, w: f"{e['count']} {'line belongs' if e['count'] == 1 else 'lines belong'} to another attribution group.",
    "not_qualifying": lambda e, w: f"{e['count']} {'video has' if e['count'] == 1 else 'videos have'} no known creator or publish time and {'is' if e['count'] == 1 else 'are'} not counted.",
    "video_known": lambda e, w: f"{e['count']} {'line has' if e['count'] == 1 else 'lines have'} a video that is already in the video data.",
}


_SALES_COLS = ["amount", "bucket", "creator_id", "creator_raw", "currency", "eligible", "gmv", "line_id", "local_date", "net",
               "order_id", "order_status", "product_id", "refunded", "refund_state", "video_known"]
_VIDEO_COLS = ["creator_id", "creator_handle", "local_date", "product_id", "published_at", "qualifies", "video_id", "views_total"]
_SAMPLE_COLS = ["creator_id", "delivered_date", "delivery_to_video_days", "handle", "matched_video_id", "product_sku", "sample_id",
                "sent_date", "state"]
DEFAULT_COLUMNS = {  # shown as table headers even when there are no records
    "gmv": _SALES_COLS, "creator_attributed_gmv": _SALES_COLS, "net_attributed_sales": _SALES_COLS, "creator_net_sales": _SALES_COLS,
    "creator_sales_after_costs": ["amount", "component"], "videos": _VIDEO_COLS, "creator_videos": _VIDEO_COLS,
    "active_creators": _VIDEO_COLS, "sample_conversion_rate": _SAMPLE_COLS,
}


def _excl_sentence(e, who):
    r = e["reason"]
    if r.startswith("immature_or_unobservable:"):
        st = {"pending": "still pending", "in_transit": "still in transit", "unknown": "of unknown outcome"}.get(r.split(":", 1)[1], "too recent")
        return f"{e['count']} {'sample is' if e['count'] == 1 else 'samples are'} {st} and too recent to judge."
    fn = EXCL.get(r)
    if fn:
        return fn(e, who)
    return f"{e['count']} {'record was' if e['count'] == 1 else 'records were'} left out."


def build(key, part, label, brand, creator, exclusions, n_included, n_total, status, reason, data_note, columns, ctx) -> dict:
    reason = plain_text(reason, ctx) if reason else reason
    who = creator + (f" at {brand}" if brand else "") if creator else (brand or "the portfolio")
    means = MEANS.get(key, lambda w: f"{label} for {w}.")(who)
    if part == "refunds":
        means = f"The refunds completed by the cutoff date on {who}'s sales."
    elif part == "unresolved":
        means = f"Sales for {who} whose video is not in the video data."
    elif part in ("retainer_cost", "commission_cost", "sample_cost"):
        means = {"retainer_cost": "The retainer owed for the month, prorated to the days the contract was active.",
                 "commission_cost": "The commission owed on this creator's sales.",
                 "sample_cost": "The cost of the samples and shipping sent to this creator."}[part]
    elif part == "progress":
        means = f"How far {who}'s goal is along: the amount so far divided by the target, capped at 150%."
    elif part == "target":
        means = f"The target set for {who} in the goal plan."
    elif part == "required_pace":
        means = f"The amount {who} needs to add each remaining day to reach the target."
    matters = MATTERS.get(key, "It supports a decision about the creator programme.")
    watch = [_excl_sentence(e, brand or "the brand") for e in exclusions or []]
    if key in _NET or part == "refunds":
        watch.append("Refunds that finish after the cutoff date are not subtracted yet, so net figures can still fall.")
    if data_note:
        watch.append(data_note)
    incomplete = reason if status and status != "current" else None
    if incomplete:
        watch.append(incomplete)
    if not watch:
        watch.append("Nothing unusual: every record behind this number was counted." if n_total else
                     f"No records were found for {who} in this period.")
    elif n_total == 0 and not exclusions:
        watch.insert(0, f"No records were found for {who} in this period.")
    how = HOW.get(key, "Built from the records listed below.")
    if part in ("retainer_cost", "commission_cost", "sample_cost"):
        how = "Taken from the creator's contract, commission and sample records."
    parts = [how]
    if exclusions:
        parts.append("Left out: " + " ".join(_excl_sentence(e, brand or "the brand") for e in exclusions))
    rows = ("Each line below is a real record from the brand's files. Counted lines add up to the number; lines marked as not counted show what was left out, "
            "and every line names the file it came from so the original can be checked.") if n_total else \
        "This number is worked out from other figures rather than individual records, so there are no separate lines to list."
    out = {
        "what_this_means": means, "why_it_matters": matters, "what_to_watch": " ".join(watch),
        "incomplete_reason": incomplete, "data_note": data_note,
        "columns_plain": [{"key": c, "label": column_label(c)} for c in (columns or DEFAULT_COLUMNS.get(key, []))],
    }
    out["explainer"] = {"what_it_means": means, "why_it_matters": matters, "how_calculated": " ".join(parts), "what_rows_prove": rows}
    return {k: (plain_text(v, ctx) if isinstance(v, str) and k in ("what_to_watch", "incomplete_reason", "data_note") else v)
            for k, v in out.items()}
