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
                  feedback_log.json ←─ GitHub Pages UI
                         ↓
                  selection_criteria.md (evolves over time)
```

## How It Works

1. **Gmail Scan**: Fetches newsletters from tracked sources (last 24h)
2. **Tier 2 Scan**: Pulls Hacker News top stories + web search
3. **Feedback Check**: Reviews yesterday's ratings, triggers criteria evolution after 7 days
4. **Article Selection**: Claude selects 4 articles using `selection_criteria.md` + ticker signals
5. **Delivery**: Sends to Gmail, Slack, GitHub Pages, and Actions log

## GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key |
| `GMAIL_OAUTH_JSON` | Gmail OAuth token JSON (see setup below) |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions |

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

## Feedback Loop

- Rate articles on [GitHub Pages](https://jroypeterson.github.io/daily-reads)
- Ratings stored in `feedback_log.json`
- After 7 days of feedback, Claude rewrites `selection_criteria.md` with learned preferences

## Schedule

Runs daily at 7am ET (noon UTC) via GitHub Actions. Manual trigger available via `workflow_dispatch`.
