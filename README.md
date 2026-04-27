# Holiday Special Hours Compliance Dashboard

Streamlit app tracking Canadian restaurant special hours submissions for DoorDash holidays 2026–2027.

## Setup

```bash
cd HolidayDashboard

# Create venv and install
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure credentials
cp .env.example .env
# Edit .env with your Snowflake creds + Slack bot token
```

### `.env` keys

| Key | Description |
|---|---|
| `SNOWFLAKE_ACCOUNT` | e.g. `abc12345.us-east-1` |
| `SNOWFLAKE_USER` | Your DoorDash email |
| `SNOWFLAKE_PAT` | Snowflake PAT (preferred) or use `SNOWFLAKE_PASSWORD` |
| `SNOWFLAKE_WAREHOUSE` | Your warehouse name |
| `SNOWFLAKE_ROLE` | Optional role override |
| `SLACK_BOT_TOKEN` | `xoxb-...` — bot with `chat:write` scope |
| `SLACK_CHANNEL_ID` | Channel ID (e.g. `C0123456789`) |
| `SCHEDULE_CRON` | 5-field cron, default `0 9 * * 1` (Mon 9AM ET) |

## Run the dashboard

```bash
streamlit run app.py
```

## Manual Slack push

```bash
python push_to_slack.py
```

## Scheduled automatic push

### Option A — cron

```cron
# Every Monday 9:00 AM ET
0 9 * * 1 cd /path/to/HolidayDashboard && .venv/bin/python push_to_slack.py >> logs/push.log 2>&1
```

### Option B — long-running process (APScheduler)

```bash
python push_to_slack.py --schedule
```

Reads `SCHEDULE_CRON` and `TIMEZONE` from `.env` (default: Monday 9AM ET).

## Dashboard tabs

| Tab | Description |
|---|---|
| Holiday Overview | Submission rate per holiday with progress bars + stacked bar chart |
| By Account Owner | Compliance rate per AO with heatmap |
| By Business | Searchable business-level compliance table |
| By Risk Cohort | Cohort 1–4 + Net New breakdown |
| Store Detail | Filterable store-level table with CSV export |

## Slack message format

The push includes:
- Submission rate per holiday (text progress bars)
- Stores with ≥1 holiday submitted by risk cohort
- Bottom 5 AOs for the next upcoming holiday
