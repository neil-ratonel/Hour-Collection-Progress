"""Holiday Special Hours Compliance Dashboard — Streamlit app."""

from __future__ import annotations

import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import get_slack_config
from data_access import fetch_compliance_data
from slack_notifier import build_slack_message, post_to_slack

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Holiday Special Hours Compliance",
    page_icon="🍁",
    layout="wide",
)

st.title("🍁 Canada Holiday Special Hours Compliance")
st.caption("Tracks which Canadian restaurant stores have submitted special hours for upcoming holidays.")

st.markdown("""
<style>
/* ── Headings ── */
h1 { font-size: 28px !important; }
h2 { font-size: 20px !important; }
h3 { font-size: 16px !important; }

/* ── KPI metrics ── */
[data-testid="stMetricValue"] { font-size: 36px !important; }
[data-testid="stMetricLabel"] { font-size: 13px !important; }

/* ── Dataframe table ── */
[data-testid="stDataFrame"] td,
[data-testid="stDataFrame"] .dvn-cell { font-size: 13px !important; }
[data-testid="stDataFrame"] th         { font-size: inherit !important; }

/* ── Captions / footer ── */
[data-testid="stCaptionContainer"] p,
.stCaption, small { font-size: 12px !important; }

/* ── Badges (tab labels, status chips) ── */
[data-testid="stTab"] button p,
[data-testid="stMarkdownContainer"] code { font-size: 11px !important; }

/* ── Sidebar filter labels ── */
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stRadio label { font-size: 0.8rem !important; }
</style>
""", unsafe_allow_html=True)

# ── Load data ────────────────────────────────────────────────────────────────
with st.spinner("Loading data from Snowflake…"):
    df_raw = fetch_compliance_data()

if df_raw.empty:
    st.error("No data returned from Snowflake. Check your SQL and credentials.")
    st.stop()

# ── Sidebar — Filters ────────────────────────────────────────────────────────
st.sidebar.header("Filters")

# Holiday
all_holidays = (
    df_raw.dropna(subset=["holiday", "date"])
    .drop_duplicates(subset=["holiday"])
    .sort_values("date")["holiday"]
    .tolist()
) if "holiday" in df_raw.columns else []
selected_holiday = st.sidebar.selectbox("Holiday", ["All"] + all_holidays)

# Management type
mgmt_types = sorted(df_raw["management_type"].dropna().unique().tolist()) if "management_type" in df_raw.columns else []
selected_mgmt = st.sidebar.selectbox("Management Type", ["All"] + mgmt_types)

# Account Owner
all_aos = sorted(df_raw["account_owner"].dropna().unique().tolist()) if "account_owner" in df_raw.columns else []
selected_ao = st.sidebar.selectbox("Account Owner", ["All"] + all_aos)

# Updated Risk Tier (from NEILRATONEL.RISK_TIERS_VICTORIA_DAY_2026)
risk_tiers = sorted(df_raw["updated_risk_tier"].dropna().unique().tolist()) if "updated_risk_tier" in df_raw.columns else []
selected_risk_tier = st.sidebar.selectbox("Updated Risk Tier", ["All"] + risk_tiers)

# POS Integration
pos_filter = st.sidebar.selectbox(
    "POS Integration",
    ["All", "Integrated (special hours)", "Integrated (regular hours)", "Not Integrated"],
)

st.sidebar.divider()

# ── Slack Push ───────────────────────────────────────────────────────────────
st.sidebar.header("Slack Push")
slack_cfg = get_slack_config()
slack_ready = bool(slack_cfg.webhook_url or (slack_cfg.bot_token and slack_cfg.channel_id))

if not slack_ready:
    st.sidebar.caption("Set SLACK_WEBHOOK_URL in .env to enable.")

if st.sidebar.button("📤 Push to Slack", disabled=not slack_ready):
    with st.spinner("Sending to Slack…"):
        msg = build_slack_message(df_raw)
        result = post_to_slack(msg, webhook_url=slack_cfg.webhook_url, bot_token=slack_cfg.bot_token, channel_id=slack_cfg.channel_id)
    if result.get("ok"):
        st.sidebar.success(f"Sent! ts={result['ts']}")
    else:
        st.sidebar.error(f"Failed: {result.get('error')}")

st.sidebar.divider()
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# ── Apply filters ────────────────────────────────────────────────────────────
df = df_raw.copy()

if selected_holiday != "All":
    df = df[df["holiday"] == selected_holiday]
if selected_mgmt != "All" and "management_type" in df.columns:
    df = df[df["management_type"] == selected_mgmt]
if selected_ao != "All" and "account_owner" in df.columns:
    df = df[df["account_owner"] == selected_ao]
if selected_risk_tier != "All" and "updated_risk_tier" in df.columns:
    df = df[df["updated_risk_tier"] == selected_risk_tier]

if pos_filter == "Integrated (special hours)" and "integrated_special_hours_via_special_hours" in df.columns:
    df = df[df["integrated_special_hours_via_special_hours"] == True]
elif pos_filter == "Integrated (regular hours)" and "integrated_special_hours_via_regular_hours" in df.columns:
    df = df[df["integrated_special_hours_via_regular_hours"] == True]
elif pos_filter == "Not Integrated" and "integrated_special_hours_via_special_hours" in df.columns:
    df = df[
        (df["integrated_special_hours_via_special_hours"] == False)
        & (df["integrated_special_hours_via_regular_hours"] == False)
    ]

if df.empty:
    st.warning("No data matches the current filters.")
    st.stop()

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_overview, tab_ao, tab_business, tab_cohort, tab_stores = st.tabs([
    "📊 Holiday Overview",
    "👤 By Account Owner",
    "🏢 By Business",
    "🎯 By Risk Tier",
    "🔍 Store Detail",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — Holiday Overview
# ─────────────────────────────────────────────────────────────────────────────
with tab_overview:
    holiday_agg = (
        df.groupby(["date", "holiday"])
        .agg(
            total_stores=("store_id", "nunique"),
            submitted_stores=("submitted", "sum"),
        )
        .reset_index()
        .sort_values("date")
    )
    holiday_agg["not_submitted"] = holiday_agg["total_stores"] - holiday_agg["submitted_stores"]
    holiday_agg["submission_rate"] = (
        holiday_agg["submitted_stores"] / holiday_agg["total_stores"] * 100
    ).round(1)

    # KPI row — overall stats
    total_store_holiday_pairs = len(df)
    total_submitted = int(df["submitted"].sum())
    overall_rate = total_submitted / total_store_holiday_pairs * 100 if total_store_holiday_pairs else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Store × Holiday Pairs", f"{total_store_holiday_pairs:,}")
    k2.metric("Submitted", f"{total_submitted:,}")
    k3.metric("Not Submitted", f"{total_store_holiday_pairs - total_submitted:,}")
    k4.metric("Overall Submission Rate", f"{overall_rate:.1f}%")

    st.divider()

    # Progress bars per holiday
    st.subheader("Submission Rate by Holiday")
    for _, row in holiday_agg.iterrows():
        rate = row["submission_rate"]
        label = f"**{row['holiday']}** ({row['date']})"
        col_lbl, col_bar, col_pct = st.columns([3, 5, 1])
        with col_lbl:
            st.markdown(label)
        with col_bar:
            color = "green" if rate >= 80 else "orange" if rate >= 50 else "red"
            st.progress(rate / 100)
        with col_pct:
            st.markdown(f"**{rate:.1f}%**")
        st.caption(
            f"&nbsp;&nbsp;&nbsp;{int(row['submitted_stores']):,} submitted / "
            f"{int(row['total_stores']):,} total — "
            f"{int(row['not_submitted']):,} not submitted"
        )

    st.divider()

    # Bar chart
    fig = go.Figure()
    fig.add_bar(
        x=holiday_agg["holiday"],
        y=holiday_agg["submitted_stores"],
        name="Submitted",
        marker_color="#2ecc71",
    )
    fig.add_bar(
        x=holiday_agg["holiday"],
        y=holiday_agg["not_submitted"],
        name="Not Submitted",
        marker_color="#e74c3c",
    )
    fig.update_layout(
        barmode="stack",
        title="Stores by Holiday",
        xaxis_title="",
        yaxis_title="Stores",
        legend=dict(orientation="h", y=-0.2),
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Summary table
    st.subheader("Summary Table")
    display_cols = ["holiday", "date", "total_stores", "submitted_stores", "not_submitted", "submission_rate"]
    st.dataframe(
        holiday_agg[display_cols].rename(columns={
            "holiday": "Holiday",
            "date": "Date",
            "total_stores": "Total Stores",
            "submitted_stores": "Submitted",
            "not_submitted": "Not Submitted",
            "submission_rate": "Rate (%)",
        }),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    # ── Breakdown pivot tables ────────────────────────────────────────────────
    def make_pivot(group_col: str, label: str) -> None:
        if group_col not in df.columns:
            return
        agg = (
            df.groupby([group_col, "holiday"])
            .agg(total=("store_id", "nunique"), submitted=("submitted", "sum"))
            .reset_index()
        )
        agg["rate"] = (agg["submitted"] / agg["total"] * 100).round(1)

        # Sort holidays by date
        holiday_order = holiday_agg.sort_values("date")["holiday"].tolist()

        pivot = (
            agg.pivot(index=group_col, columns="holiday", values="rate")
            .reindex(columns=holiday_order)
            .fillna(0)
            .round(1)
        )

        col_chart, col_table = st.columns([3, 2])
        with col_chart:
            fig = px.imshow(
                pivot,
                color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
                range_color=[0, 100],
                aspect="auto",
                labels=dict(color="Rate (%)"),
                title=f"Submission Rate by {label} × Holiday",
                height=max(300, len(pivot) * 30 + 80),
            )
            fig.update_xaxes(tickangle=-30, tickfont=dict(size=10))
            fig.update_coloraxes(colorbar=dict(len=0.6))
            st.plotly_chart(fig, use_container_width=True)
        with col_table:
            st.markdown(f"**{label}** — rate (%) per holiday")
            st.dataframe(pivot.add_suffix("%"), use_container_width=True, height=max(200, len(pivot) * 35 + 40))

    st.subheader("Submission Rate by Management Type")
    make_pivot("management_type", "Management Type")

    st.subheader("Submission Rate by Risk Tier")
    make_pivot("updated_risk_tier", "Risk Tier")

    st.subheader("Submission Rate by Account Owner")
    make_pivot("account_owner", "Account Owner")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — By Account Owner
# ─────────────────────────────────────────────────────────────────────────────
with tab_ao:
    st.subheader("Compliance by Account Owner")

    # AO × Holiday matrix
    ao_holiday = (
        df.groupby(["account_owner", "holiday"])
        .agg(
            total=("store_id", "nunique"),
            submitted=("submitted", "sum"),
        )
        .reset_index()
    )
    ao_holiday["rate"] = (ao_holiday["submitted"] / ao_holiday["total"] * 100).round(1)

    # Overall AO compliance
    ao_overall = (
        df.groupby("account_owner")
        .agg(
            total_pairs=("store_id", "count"),
            submitted_pairs=("submitted", "sum"),
            unique_stores=("store_id", "nunique"),
        )
        .reset_index()
    )
    ao_overall["overall_rate"] = (ao_overall["submitted_pairs"] / ao_overall["total_pairs"] * 100).round(1)
    ao_overall["not_submitted"] = ao_overall["total_pairs"] - ao_overall["submitted_pairs"]
    ao_overall = ao_overall.sort_values("overall_rate")

    # Horizontal bar chart — worst first
    fig_ao = px.bar(
        ao_overall,
        x="overall_rate",
        y="account_owner",
        orientation="h",
        color="overall_rate",
        color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
        range_color=[0, 100],
        labels={"overall_rate": "Submission Rate (%)", "account_owner": "Account Owner"},
        title="Overall Submission Rate by AO (all holidays combined)",
        height=max(400, len(ao_overall) * 28),
    )
    fig_ao.update_coloraxes(showscale=False)
    fig_ao.update_layout(yaxis=dict(tickfont=dict(size=11)))
    st.plotly_chart(fig_ao, use_container_width=True)

    # Pivot: AO × Holiday rates
    if len(all_holidays) > 1:
        st.subheader("Rate Heatmap (AO × Holiday)")
        pivot = ao_holiday.pivot(index="account_owner", columns="holiday", values="rate").fillna(0)
        pivot = pivot.loc[pivot.mean(axis=1).sort_values().index]  # worst AOs on top

        fig_heat = px.imshow(
            pivot,
            color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
            range_color=[0, 100],
            aspect="auto",
            labels=dict(color="Rate (%)"),
            height=max(400, len(pivot) * 22),
        )
        fig_heat.update_xaxes(tickangle=-30, tickfont=dict(size=10))
        st.plotly_chart(fig_heat, use_container_width=True)

    # Table
    st.subheader("AO Summary Table")
    st.dataframe(
        ao_overall.rename(columns={
            "account_owner": "Account Owner",
            "unique_stores": "Unique Stores",
            "submitted_pairs": "Submitted (store×holiday)",
            "not_submitted": "Not Submitted",
            "overall_rate": "Overall Rate (%)",
        })[["Account Owner", "Unique Stores", "Submitted (store×holiday)", "Not Submitted", "Overall Rate (%)"]],
        use_container_width=True,
        hide_index=True,
    )

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — By Business
# ─────────────────────────────────────────────────────────────────────────────
with tab_business:
    st.subheader("Compliance by Business")

    biz_agg = (
        df.groupby(["business_id", "business_name", "account_owner"])
        .agg(
            total_pairs=("store_id", "count"),
            submitted_pairs=("submitted", "sum"),
            unique_stores=("store_id", "nunique"),
            l30d_volume=("l30d_volume", "sum") if "l30d_volume" in df.columns else ("store_id", "count"),
        )
        .reset_index()
    )
    biz_agg["rate"] = (biz_agg["submitted_pairs"] / biz_agg["total_pairs"] * 100).round(1)
    biz_agg["not_submitted"] = biz_agg["total_pairs"] - biz_agg["submitted_pairs"]

    col_search, col_sort = st.columns([3, 1])
    with col_search:
        search = st.text_input("Search business name", "")
    with col_sort:
        sort_col = st.selectbox("Sort by", ["rate", "unique_stores", "not_submitted", "l30d_volume"], index=0)

    view = biz_agg.copy()
    if search:
        view = view[view["business_name"].str.contains(search, case=False, na=False)]
    view = view.sort_values(sort_col, ascending=(sort_col == "rate"))

    st.dataframe(
        view.rename(columns={
            "business_name": "Business",
            "business_id": "Biz ID",
            "account_owner": "AO",
            "unique_stores": "Stores",
            "submitted_pairs": "Submitted (×holiday)",
            "not_submitted": "Not Submitted",
            "rate": "Rate (%)",
            "l30d_volume": "L30D Orders",
        })[["Business", "Biz ID", "AO", "Stores", "Submitted (×holiday)", "Not Submitted", "Rate (%)", "L30D Orders"]],
        use_container_width=True,
        hide_index=True,
        height=500,
    )

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — By Risk Tier
# ─────────────────────────────────────────────────────────────────────────────
with tab_cohort:
    st.subheader("Compliance by Risk Tier")

    if "updated_risk_tier" not in df.columns:
        st.info("updated_risk_tier column not found in data. Check that NEILRATONEL.RISK_TIERS_VICTORIA_DAY_2026 joined correctly.")
    else:
        tier_holiday = (
            df.groupby(["updated_risk_tier", "holiday"])
            .agg(
                total=("store_id", "nunique"),
                submitted=("submitted", "sum"),
            )
            .reset_index()
        )
        tier_holiday["rate"] = (tier_holiday["submitted"] / tier_holiday["total"] * 100).round(1)

        tier_overall = (
            df.groupby("updated_risk_tier")
            .agg(
                total_pairs=("store_id", "count"),
                submitted_pairs=("submitted", "sum"),
                unique_stores=("store_id", "nunique"),
            )
            .reset_index()
        )
        tier_overall["rate"] = (tier_overall["submitted_pairs"] / tier_overall["total_pairs"] * 100).round(1)
        tier_overall = tier_overall.sort_values("updated_risk_tier")

        # KPI per tier
        cols = st.columns(max(1, len(tier_overall)))
        for i, (_, row) in enumerate(tier_overall.iterrows()):
            cols[i].metric(
                row["updated_risk_tier"],
                f"{row['rate']:.1f}%",
                f"{int(row['unique_stores']):,} stores",
            )

        st.divider()

        # Grouped bar chart by tier × holiday
        fig_tier = px.bar(
            tier_holiday,
            x="holiday",
            y="rate",
            color="updated_risk_tier",
            barmode="group",
            labels={"rate": "Submission Rate (%)", "holiday": "", "updated_risk_tier": "Risk Tier"},
            title="Submission Rate by Risk Tier and Holiday",
            height=450,
        )
        st.plotly_chart(fig_tier, use_container_width=True)

        # Pivot table
        pivot_tier = tier_holiday.pivot(
            index="updated_risk_tier", columns="holiday", values="rate"
        ).fillna(0).round(1)
        st.dataframe(pivot_tier.add_suffix(" (%)"), use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 — Store Detail
# ─────────────────────────────────────────────────────────────────────────────
with tab_stores:
    st.subheader("Store-Level Detail")

    show_only_missing = st.checkbox("Show only stores NOT submitted", value=False)

    detail = df.copy()
    if show_only_missing:
        detail = detail[detail["submitted"] == False]

    display_detail_cols = [
        c for c in [
            "business_name", "business_id", "store_id", "account_owner",
            "updated_risk_tier", "management_type", "holiday", "date",
            "has_special_hours_text", "provider_type",
            "integrated_special_hours_via_special_hours",
            "integrated_special_hours_via_regular_hours",
            "l30d_volume", "l30d_gov",
        ]
        if c in detail.columns
    ]
    rename_detail = {
        "business_name": "Business",
        "business_id": "Biz ID",
        "store_id": "Store ID",
        "account_owner": "AO",
        "updated_risk_tier": "Updated Risk Tier",
        "management_type": "Mgmt Type",
        "holiday": "Holiday",
        "date": "Date",
        "has_special_hours_text": "Status",
        "provider_type": "POS",
        "integrated_special_hours_via_special_hours": "POS SH",
        "integrated_special_hours_via_regular_hours": "POS RH",
        "l30d_volume": "L30D Orders",
        "l30d_gov": "L30D GOV",
    }
    st.caption(f"{len(detail):,} rows")
    st.dataframe(
        detail[display_detail_cols].rename(columns=rename_detail),
        use_container_width=True,
        hide_index=True,
        height=500,
    )

    # Download
    csv = detail[display_detail_cols].rename(columns=rename_detail).to_csv(index=False)
    st.download_button(
        "⬇️ Download CSV",
        csv,
        file_name=f"holiday_compliance_{datetime.date.today()}.csv",
        mime="text/csv",
    )
