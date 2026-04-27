"""Slack push logic for Holiday Compliance Dashboard."""

from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    pass


def build_slack_message(df: pd.DataFrame, run_ts: str | None = None) -> str:
    """Build a Slack-formatted compliance summary matching the holiday playbook layout."""
    if run_ts is None:
        run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M ET")

    # Sorted list of holidays by date
    holidays_ordered: list[str] = []
    if "holiday" in df.columns and "date" in df.columns:
        holidays_ordered = (
            df.dropna(subset=["holiday", "date"])
            .drop_duplicates("holiday")
            .sort_values("date")["holiday"]
            .tolist()
        )

    # Overall collection rate
    total_pairs = len(df)
    total_submitted = int(df["submitted"].sum()) if "submitted" in df.columns else 0
    overall_rate = total_submitted / total_pairs * 100 if total_pairs else 0.0

    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────
    holiday_label = " & ".join(re.sub(r"\s*\(.*?\)", "", h).strip() for h in holidays_ordered) if holidays_ordered else "Holiday"
    lines += [
        f"*{holiday_label.upper()} — Holiday Hours Collection Status*",
        f"_Run: {run_ts}_",
        "",
        f"Hour Collection Progress  *{overall_rate:.2f}%*",
        "",
    ]

    # ── Collection Progress by Management Type ────────────────────────────
    if "management_type" in df.columns and holidays_ordered:
        lines += ["*by Management Type*"] + _pipe_pivot(df, "management_type", "", holidays_ordered, blank_headers=["victoria"], use_nbsp=True)
        lines.append("")

    # ── Collection Progress by Risk Tier ──────────────────────────────────
    if "updated_risk_tier" in df.columns and holidays_ordered:
        lines.append("*by Risk Tier*")
        lines += _pipe_pivot(df, "updated_risk_tier", "", holidays_ordered, blank_headers=["victoria"], use_nbsp=True)
        lines.append("")

    # ── Top 10 Biz by GOV Missing Hours — per holiday ─────────────────────
    for holiday in holidays_ordered:
        hdf = df[df["holiday"] == holiday] if "holiday" in df.columns else df
        missing = hdf[hdf["submitted"] == False] if "submitted" in hdf.columns else hdf

        if missing.empty:
            lines += [f"*Top 10 Biz Missing Hours — {holiday}*", "_All stores submitted!_ :white_check_mark:", ""]
            continue

        # Aggregate to business level
        biz_missing = (
            missing.groupby(["business_name", "business_id"])
            .agg(stores_missing=("store_id", "nunique"))
            .reset_index()
        )
        biz_all = (
            hdf.groupby(["business_name", "business_id"])
            .agg(
                stores_total=("store_id", "nunique"),
                stores_submitted=("submitted", "sum"),
                l30d_gov=("l30d_gov", "sum") if "l30d_gov" in hdf.columns else ("store_id", "count"),
            )
            .reset_index()
        )
        biz = biz_all.merge(biz_missing[["business_id", "stores_missing"]], on="business_id", how="inner")
        biz["collection_pct"] = (biz["stores_submitted"] / biz["stores_total"] * 100).round(1)
        biz = biz.sort_values(["collection_pct", "l30d_gov"], ascending=[True, False]).head(10)

        NW = 30
        lines.append("*Top 10 Biz by GOV(L30D) Missing Hours*")
        for _, row in biz.iterrows():
            name = str(row["business_name"])[:NW]
            v = row["l30d_gov"] if "l30d_gov" in row else 0
            if v >= 1_000_000:
                gov = f"${v / 1_000_000:.2f}M"
            elif v >= 1_000:
                gov = f"${v / 1_000:.2f}K"
            else:
                gov = f"${v:.2f}"
            submitted = int(row["stores_submitted"])
            total = int(row["stores_total"])
            rate = f"{row['collection_pct']:.1f}%"
            lines.append(f"• {name} ({gov}) {submitted}/{total} - {rate}")
        lines.append("")

    msg = "\n".join(lines)
    # Slack workflow text block limit is ~3000 chars
    if len(msg) > 2900:
        msg = msg[:2850] + "\n…_(truncated)_"
    return msg


def _submission_pivot(df: pd.DataFrame, group_col: str, holidays: list[str]) -> pd.DataFrame:
    """Returns a pivot of submission rate (%) by group_col × holiday, plus __total__ column."""
    rows = {}
    for grp, gdf in df.groupby(group_col):
        row: dict = {}
        for h in holidays:
            hdf = gdf[gdf["holiday"] == h] if "holiday" in gdf.columns else gdf
            total = hdf["store_id"].nunique()
            submitted = int(hdf["submitted"].sum()) if "submitted" in hdf.columns else 0
            row[h] = round(submitted / total * 100, 1) if total else 0.0
        total_all = gdf["store_id"].nunique()
        sub_all = int(gdf["submitted"].sum()) if "submitted" in gdf.columns else 0
        row["__total__"] = round(sub_all / total_all * 100, 1) if total_all else 0.0
        rows[grp] = row
    return pd.DataFrame(rows).T


def _grand_total_row(df: pd.DataFrame, holidays: list[str]) -> dict:
    result = {}
    for h in holidays:
        hdf = df[df["holiday"] == h] if "holiday" in df.columns else df
        total = hdf["store_id"].nunique()
        submitted = int(hdf["submitted"].sum()) if "submitted" in hdf.columns else 0
        result[h] = round(submitted / total * 100, 1) if total else 0.0
    return result


def _pipe_row(cells: list[str], widths: list[int], header: bool = False, aligns: list[str] | None = None) -> str:
    """Format one row of a pipe-delimited table."""
    if aligns is None:
        aligns = ["<" if i == 0 else ">" for i in range(len(cells))]
    parts = [f"{c:{a}{w}}" for c, a, w in zip(cells, aligns, widths)]
    return "  ".join(parts)


def _pipe_sep(widths: list[int]) -> str:
    """Separator row for a pipe-delimited table."""
    return "|-" + "-|-".join("-" * w for w in widths) + "-|"


def _pipe_pivot(df: pd.DataFrame, group_col: str, label: str, holidays: list[str], blank_headers: list[str] | None = None, use_nbsp: bool = False) -> list[str]:
    """Build pipe-table lines for a submission-rate pivot."""
    label_w = 22
    col_w = 13
    abbrevs = [
        "" if (blank_headers and any(b.lower() in h.lower() for b in blank_headers)) else _abbrev_holiday(h, col_w)
        for h in holidays
    ]
    widths = [label_w] + [col_w] * len(holidays)

    lines = []
    if any([label] + abbrevs):
        lines.append(_pipe_row([label] + abbrevs, widths, header=True))
    pivot = _submission_pivot(df, group_col, holidays)
    for grp, row in pivot.iterrows():
        if use_nbsp:
            name = str(grp)
            rates = "  ".join(f"{row.get(h, 0.0):.1f}%" for h in holidays)
            lines.append(f"• {name} — {rates}")
        else:
            cells = [str(grp)] + [f"{row.get(h, 0.0):.1f}%" for h in holidays]
            lines.append(_pipe_row(cells, widths, aligns=["<"] + [">"] * len(holidays)))
    return lines


def _abbrev_holiday(name: str, max_len: int) -> str:
    """Strip parenthetical suffix (e.g. '(VD) 2026') then truncate to max_len."""
    short = re.sub(r"\s*\(.*", "", name).strip()
    return short[:max_len]


def _progress_bar(pct: float, width: int = 8) -> str:
    filled = round(pct / 100 * width)
    return "▓" * filled + "░" * (width - filled)


def post_via_webhook(message: str, webhook_url: str) -> dict:
    """Post message via Slack webhook URL. Returns status dict."""
    import urllib.request
    import urllib.error
    import json

    payload = json.dumps({"Message": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return {"ok": True, "response": body}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8')}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def post_to_slack(message: str, webhook_url: str = "", bot_token: str = "", channel_id: str = "") -> dict:
    """Post message to Slack — prefers webhook URL, falls back to bot token."""
    if webhook_url:
        return post_via_webhook(message, webhook_url)

    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    client = WebClient(token=bot_token)
    try:
        response = client.chat_postMessage(channel=channel_id, text=message, mrkdwn=True)
        return {"ok": True, "ts": response["ts"]}
    except SlackApiError as e:
        return {"ok": False, "error": str(e)}
