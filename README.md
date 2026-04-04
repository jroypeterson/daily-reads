# Daily Reads

AI-curated daily article digest — 4 articles across healthcare/biotech, finance, tech/AI, and wildcard topics.

## Architecture

```
Gmail Newsletters ─┐
                    ├─→ Claude (article selection) ─→ Gmail email
Hacker News ────────┤                                → Slack webhook
Web search ─────────┘                                → GitHub Pages
                                                     → Actions log
                         ↑
                  feedback_log.json ←─ Email replies / GitHub issue feedback
                         ↓
      artifacts/runs/YYYY-MM-DD.json ←─ selected digest snapshot
                         ↓
            external_exemplars.json ←─ Gmail +taste alias / Gmail label / local Dropbox inbox
                         ↓
 learned_preferences.json + learned_preferences.md
                         ↓
        selection_criteria_proposed.md + criteria_update_state.json
                         ↓
                  selection_criteria.md (after review)
```

## How It Works

1. **Gmail Scan**: Fetches newsletters from tracked sources (last 24h)
2. **Tier 2 Scan**: Pulls Hacker News top stories + web search
3. **Feedback Check**: Reviews yesterday's ratings, triggers criteria evolution after 7 days
4. **Article Selection**: Claude selects 4 articles using `selection_criteria.md` + ticker signals
5. **Delivery**: Sends to Gmail, Slack, GitHub Pages, and Actions log
6. **Criteria Review**: When enough feedback accumulates, Claude proposes a criteria update and notifies via Gmail + Slack for accept/reject/modify review
7. **Taste Intake**: Positive exemplars can come from a dedicated Gmail alias/label or a local Dropbox watch folder and feed learned preferences

## GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key |
| `GMAIL_OAUTH_JSON` | Gmail OAuth token JSON (see setup below) |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions |
| `TASTE_EMAIL_ALIAS` | Optional override for exemplar intake alias, defaults to `jroypeterson+taste@gmail.com` |
| `TASTE_GMAIL_LABEL` | Optional Gmail label used as a backup exemplar intake path, defaults to `taste` |

## Gmail OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable Gmail API
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download `credentials.json`
5. Run locally once to generate a token:
   ```bash
   python -c "
   from google_auth_oauthlib.flow import InstalledAppFlow
   flow = InstalledAppFlow.from_client_secrets_file('credentials.json', ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send'])
   creds = flow.run_local_server(port=0)
   print(creds.to_json())
   "
   ```
6. Copy the output JSON → set as `GMAIL_OAUTH_JSON` secret in GitHub

## Run Locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
export GMAIL_OAUTH_JSON='{"token": "...", ...}'
export SLACK_WEBHOOK_URL=https://hooks.slack.com/...
python main.py
```

To inspect accumulated history and artifacts:

```bash
python analyze_history.py
```

The report includes retrospective views such as source selection frequency, average scores by slot/source, recurring miss notes, and overall selection rate.

To ingest local Dropbox exemplars:

```bash
python process_dropbox_exemplars.py
python process_exemplar_content.py
```

By default this scans:

```text
C:\Users\jroyp\Dropbox\Claude Folder\daily-reads-taste-samples
```

Processed files are moved into:

```text
C:\Users\jroyp\Dropbox\Claude Folder\daily-reads-taste-samples\Incorporated into taste preferences
```

To register a once-daily local Windows task for Dropbox ingestion and preference refresh:

```powershell
powershell -ExecutionPolicy Bypass -File .\register_daily_dropbox_taste_task.ps1
```

That helper now registers:

- a daily time-based trigger at `06:00`
- `StartWhenAvailable`, so Windows should catch up after a missed scheduled start
- `WakeToRun`, so Windows is allowed to wake the machine if supported/configured
- an additional at-logon trigger as a fallback when the laptop was asleep at the scheduled time
- local content extraction for archived Dropbox files before learned preferences are refreshed

## Feedback Loop

- Rate daily articles by replying to the digest email with lines like `1 3` or `3 1 too generic`
- Slack rating links open prefilled email drafts so email stays the single scoring pipeline
- GitHub Pages provides read access plus email scoring links
- Ratings are stored in `feedback_log.json`
- Positive exemplar submissions from Gmail alias/label and local Dropbox are stored in `external_exemplars.json`
- Local Dropbox exemplar ingestion defaults to `C:\Users\jroyp\Dropbox\Claude Folder\daily-reads-taste-samples`
- After Dropbox files are processed, they are archived under `Incorporated into taste preferences` to avoid repeat scans
- Archived local PDFs/text files are then processed by `process_exemplar_content.py`, which stores extracted text previews back into `external_exemplars.json`
- Each digest run is saved to `artifacts/runs/YYYY-MM-DD.json`
- Each candidate set is saved to `artifacts/candidates/YYYY-MM-DD.json`
- Each run also saves a ranked backlog to `artifacts/triage/YYYY-MM-DD.json`
- Machine-readable learned preference state is stored in `learned_preferences.json`
- Human-readable learned preference summary is stored in `learned_preferences.md`
- Learned preferences now count both GitHub taste issues and external exemplars from Gmail/Dropbox
- The selector prompt now includes recent positive exemplar notes from the learned-preference state
- Gmail candidate extraction strips common tracking params and filters obvious non-article links before selection
- The selector now reasons over structured candidate records with derived signals, not raw newsletter dumps
- After 7+ days of feedback, Claude proposes a criteria update in `selection_criteria_proposed.md`
- Proposal status is tracked in `criteria_update_state.json`
- Accept/reject/modify decisions are sent via GitHub issues and applied on the next run

## Schedule

Runs daily at 7am ET (noon UTC) via GitHub Actions. Manual trigger available via `workflow_dispatch`.
