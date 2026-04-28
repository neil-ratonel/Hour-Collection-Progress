"""Fetch holiday compliance data from Mode Analytics API."""

from __future__ import annotations

import os
import time
import requests
import pandas as pd


MODE_BASE = "https://app.mode.com/api"
WORKSPACE  = "doordash"
REPORT_TOKEN = "6e815b1b6a3c"
QUERY_TOKEN  = "679745cfccbb"

POLL_INTERVAL = 5   # seconds between status checks
MAX_WAIT      = 300 # seconds before giving up


def _auth() -> tuple[str, str]:
    token  = os.environ["MODE_API_TOKEN"]
    secret = os.environ["MODE_API_SECRET"]
    return token, secret


def _run_report() -> str:
    """Trigger a report run and return the run token."""
    url = f"{MODE_BASE}/{WORKSPACE}/reports/{REPORT_TOKEN}/runs"
    resp = requests.post(url, json={}, auth=_auth(), timeout=30)
    resp.raise_for_status()
    return resp.json()["token"]


def _wait_for_run(run_token: str) -> None:
    """Poll until the run succeeds or raises on failure/timeout."""
    url = f"{MODE_BASE}/{WORKSPACE}/reports/{REPORT_TOKEN}/runs/{run_token}"
    deadline = time.time() + MAX_WAIT
    while time.time() < deadline:
        resp = requests.get(url, auth=_auth(), timeout=30)
        resp.raise_for_status()
        state = resp.json().get("state")
        if state == "succeeded":
            return
        if state in ("failed", "cancelled"):
            raise RuntimeError(f"Mode run {run_token} ended with state: {state}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Mode run {run_token} did not complete within {MAX_WAIT}s")


def _get_query_run_token(run_token: str) -> str:
    """Return the query run token for our query within this report run."""
    url = f"{MODE_BASE}/{WORKSPACE}/reports/{REPORT_TOKEN}/runs/{run_token}/query_runs"
    resp = requests.get(url, auth=_auth(), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    query_runs = data.get("query_runs") or data.get("_embedded", {}).get("query_runs", [])
    for qr in query_runs:
        if qr.get("query_token") == QUERY_TOKEN:
            return qr["token"]
    # fall back to first query run if token doesn't match
    if query_runs:
        return query_runs[0]["token"]
    raise ValueError("No query runs found in Mode report run")


def _download_results(run_token: str, query_run_token: str) -> pd.DataFrame:
    """Download query results as CSV and return a DataFrame."""
    url = (
        f"{MODE_BASE}/{WORKSPACE}/reports/{REPORT_TOKEN}"
        f"/runs/{run_token}/query_runs/{query_run_token}/results/content.csv"
    )
    resp = requests.get(url, auth=_auth(), timeout=60)
    resp.raise_for_status()
    from io import StringIO
    return pd.read_csv(StringIO(resp.text))


def fetch_compliance_data_from_mode() -> pd.DataFrame:
    """Run the Mode report and return results as a DataFrame."""
    print("Triggering Mode report run…")
    run_token = _run_report()
    print(f"Run token: {run_token} — waiting for completion…")
    _wait_for_run(run_token)
    print("Run succeeded. Fetching results…")
    query_run_token = _get_query_run_token(run_token)
    df = _download_results(run_token, query_run_token)
    print(f"Downloaded {len(df)} rows from Mode.")
    return _post_process(df)


def _post_process(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    for col in ["has_special_hours", "l30d_volume", "l30d_gov", "num_stores", "num_stores_under_ao"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    for col in ["integrated_special_hours_via_special_hours", "integrated_special_hours_via_regular_hours"]:
        if col in df.columns:
            df[col] = df[col].astype(bool)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["submitted"] = df["has_special_hours"].astype(int) == 1
    return df
