#!/usr/bin/env python3
"""
Standalone script for scheduled Slack push of Holiday Compliance summary.

Usage:
    # One-shot push (run via cron):
    python push_to_slack.py

    # Run with APScheduler (long-running process):
    python push_to_slack.py --schedule

Cron example (every Monday 9AM ET):
    0 9 * * 1 cd /path/to/HolidayDashboard && .venv/bin/python push_to_slack.py >> logs/push.log 2>&1
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def run_push() -> None:
    from config import get_slack_config, SCHEDULE_CRON, TIMEZONE
    from slack_notifier import build_slack_message, post_to_slack

    use_mode = bool(os.getenv("MODE_API_TOKEN"))
    if use_mode:
        from mode_data_access import fetch_compliance_data_from_mode as fetch_fn
    else:
        from data_access import fetch_compliance_data_no_cache as fetch_fn

    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M ET")
    log.info("Fetching holiday compliance data…")

    try:
        df = fetch_fn()
    except Exception as exc:
        log.error("Snowflake query failed: %s", exc)
        sys.exit(1)

    if df.empty:
        log.warning("Query returned 0 rows — skipping Slack push.")
        return

    log.info("Query returned %d rows. Filtering to next upcoming holiday…", len(df))

    # Filter to next upcoming holiday only
    import datetime as dt
    import pandas as pd
    today = dt.date.today()
    future = df[pd.to_datetime(df["date"]).dt.date >= today] if "date" in df.columns else df
    if future.empty:
        log.warning("No upcoming holidays found in data — using full dataset.")
    else:
        next_date = pd.to_datetime(future["date"]).dt.date.min()
        df = df[pd.to_datetime(df["date"]).dt.date == next_date]
        log.info("Next holiday date: %s (%d rows)", next_date, len(df))

    message = build_slack_message(df, run_ts=run_ts)

    slack_cfg = get_slack_config()
    if not slack_cfg.webhook_url and not (slack_cfg.bot_token and slack_cfg.channel_id):
        log.error("Set SLACK_WEBHOOK_URL (or SLACK_BOT_TOKEN + SLACK_CHANNEL_ID) in .env.")
        sys.exit(1)

    for label, url in [("webhook 1", slack_cfg.webhook_url), ("webhook 2", slack_cfg.webhook_url_2)]:
        if not url:
            continue
        log.info("Posting to Slack via %s…", label)
        result = post_to_slack(message, webhook_url=url)
        if result.get("ok"):
            log.info("%s posted successfully.", label)
        else:
            log.error("%s post failed: %s", label, result.get("error"))


def run_scheduler() -> None:
    """Long-running scheduled push using APScheduler."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from config import SCHEDULE_CRON, TIMEZONE

    scheduler = BlockingScheduler(timezone=TIMEZONE)

    # Parse cron string (5-field standard cron)
    fields = SCHEDULE_CRON.split()
    if len(fields) != 5:
        log.error("SCHEDULE_CRON must be a 5-field cron expression, got: %r", SCHEDULE_CRON)
        sys.exit(1)

    minute, hour, day, month, day_of_week = fields
    trigger = CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=TIMEZONE,
    )

    scheduler.add_job(run_push, trigger=trigger, id="holiday_push", max_instances=1)
    log.info(
        "Scheduler started. Will push on cron=%r (tz=%s). Ctrl-C to stop.",
        SCHEDULE_CRON,
        TIMEZONE,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Holiday Compliance Slack Push")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run as a long-lived scheduled process (uses SCHEDULE_CRON from .env)",
    )
    args = parser.parse_args()

    if args.schedule:
        run_scheduler()
    else:
        run_push()
