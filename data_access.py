"""Snowflake data loading for Holiday Special Hours Compliance Dashboard."""

from __future__ import annotations

from typing import Any

import pandas as pd
import snowflake.connector
import streamlit as st
from snowflake.connector import SnowflakeConnection

from config import get_snowflake_config, load_sql


@st.cache_resource
def _connect() -> SnowflakeConnection:
    cfg = get_snowflake_config()
    kwargs: dict[str, Any] = {
        "account": cfg.account,
        "user": cfg.user,
        "warehouse": cfg.warehouse,
        "database": cfg.database,
        "schema": cfg.schema,
        "session_parameters": {"QUERY_TAG": "holiday_compliance_dashboard"},
    }
    if cfg.role:
        kwargs["role"] = cfg.role
    if cfg.password:
        kwargs["password"] = cfg.password
    else:
        raise ValueError("Set SNOWFLAKE_PASSWORD or SNOWFLAKE_PAT in .env")
    return snowflake.connector.connect(**kwargs)


def run_query(sql: str) -> pd.DataFrame:
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(sql)
        cols = [c[0].lower() for c in cur.description]
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame(rows, columns=cols)
    finally:
        cur.close()


def connect_and_run(sql: str) -> pd.DataFrame:
    """Non-Streamlit version (for scheduler/push_to_slack script)."""
    cfg = get_snowflake_config()
    kwargs: dict[str, Any] = {
        "account": cfg.account,
        "user": cfg.user,
        "warehouse": cfg.warehouse,
        "database": cfg.database,
        "schema": cfg.schema,
        "session_parameters": {"QUERY_TAG": "holiday_compliance_dashboard"},
    }
    if cfg.role:
        kwargs["role"] = cfg.role
    if cfg.password:
        kwargs["password"] = cfg.password
    else:
        raise ValueError("Set SNOWFLAKE_PASSWORD or SNOWFLAKE_PAT in .env")

    conn = snowflake.connector.connect(**kwargs)
    cur = conn.cursor()
    try:
        cur.execute(sql)
        cols = [c[0].lower() for c in cur.description]
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame(rows, columns=cols)
    finally:
        cur.close()
        conn.close()


@st.cache_data(ttl=3600, show_spinner="Running holiday compliance query…")
def fetch_compliance_data() -> pd.DataFrame:
    sql = load_sql()
    df = run_query(sql)
    return _post_process(df)


def fetch_compliance_data_no_cache() -> pd.DataFrame:
    """For scheduler — no Streamlit caching."""
    sql = load_sql()
    df = connect_and_run(sql)
    return _post_process(df)


def _post_process(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    # Normalize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Handle column name variations from SQL (quoted column names)
    rename = {
        "missing_&_incorrect": "missing_incorrect_cpd",
        "missing_&_incorrect_": "missing_incorrect_cpd",
        "poor_food_quality": "poor_food_quality_cpd",
        "lateness": "lateness_cpd",
        "never_delivered": "never_delivered_cpd",
    }
    df.rename(columns=rename, inplace=True)

    # Ensure types
    for col in ["has_special_hours", "l30d_volume", "l30d_gov", "num_stores", "num_stores_under_ao"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    for col in ["integrated_special_hours_via_special_hours", "integrated_special_hours_via_regular_hours"]:
        if col in df.columns:
            df[col] = df[col].astype(bool)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

    # Submission flag as bool
    df["submitted"] = df["has_special_hours"].astype(int) == 1

    return df
