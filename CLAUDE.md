# CLAUDE.md

## Git workflow

After making changes to this project, always commit and push to GitHub:
1. Stage the changed files (prefer naming specific files over `git add -A`)
2. Commit with a clear message describing the changes
3. Push to `origin main`

Do not leave local changes uncommitted. The project should stay in sync with GitHub.

Note: the local Windows scheduled task (daily Dropbox taste ingestion) commits to the same branch. If you encounter merge conflicts on rebase, they're almost always timestamp-only diffs in `learned_preferences.json`/`.md` — resolve by keeping `HEAD` (the newer remote version).

## Newsletter sources

When adding or troubleshooting a source in `sources.py`:
- The sender address in the dict key **must** match the actual `From:` header in Gmail, not a guess
- Substack newsletters send from `<slug>@substack.com`, not `noreply@<slug>.substack.com`
- Many platforms use subdomains like `@go.fiercepharma.com`, `@email.mckinsey.com`, `@interactive.wsj.com`
- Use `python validate_source.py "keyword"` to discover the real sender address before adding
- Use `python validate_source.py --audit` to check whether existing sources are actually producing emails
- The `.githooks/pre-commit` hook auto-validates addresses on commit if `GMAIL_OAUTH_JSON_PATH` is set (enabled per-clone via `git config core.hooksPath .githooks`)
- Sources can carry an optional `subject_allow` regex list to filter marketing emails from paid newsletters whose real-content subjects follow a known shape (see VII entry for an example)

## Local OAuth setup

`GMAIL_OAUTH_JSON_PATH` in `~/.bashrc` points to a token file outside the repo. The helper script at `C:/Users/jroyp/Dropbox/API Keys/get_gmail_token.py` regenerates it; redirect stdout with `>` (not `2>&1` — that mixes the auth prompt into the JSON).

## Gmail scan window

`fetch_newsletters(hours_back=168)` — a 7-day rolling window. Every daily run re-ingests the full week; duplicates are removed by `build_structured_candidates` via `candidate_id` dedupe. The weekly report also dedupes by `candidate_id` across the week so per-source counts stay accurate. Don't narrow this without understanding the Scuttleblurb-style miss pattern that motivated it (see `memory/project_resilience.md`).

## URL handling

`url_resolver.py` is shape-based, not per-host. Any subdomain matching `^(link|links|email|mail|trk|click|go|m|r|cl|e)\d*\.` triggers resolution + dead-end detection. Generic dead-end rule: any resolved URL landing on path `/` is dropped (homepage = article reference lost). See `memory/project_url_redirectors.md` for the full map.

Substack `substack.com/redirect/2/<token>` URLs get unwrapped to canonical publication URLs at extraction time via `_unwrap_substack_redirect` in `gmail_reader.py`. Single-use tokens otherwise fail on desktop after Gmail's link scanner consumes them.

## Slack channels

The daily digest posts to a dedicated `#daily-reads` channel via `SLACK_WEBHOOK_URL_DAILY_READS`. The end-of-run `health/v1` heartbeat plus operator-style alerts (weekly report, source audit, criteria proposals, TickTick-expired warnings, taste synthesis, digest delivery failure) all post to `#status-reports` via `SLACK_WEBHOOK_STATUS_REPORTS`. If `SLACK_WEBHOOK_URL_DAILY_READS` is unset, the digest falls back to `SLACK_WEBHOOK_STATUS_REPORTS` so a missing secret doesn't drop the digest entirely.

## Health reporting

Per `HEALTH_REPORTING.md` at the Claude Folder root. Cadence: **daily at 12:00 UTC** (7am ET) via `.github/workflows/daily.yml`. Every run posts a `health/v1` Block Kit heartbeat to `#status-reports` at end of `main.py` — `ok` on clean completion, `partial` if Slack digest delivery failed or TickTick token expired, `error` on uncaught exception or no-articles-after-2-attempts. URL liveness drops surface as informational warnings. The heartbeat helper is `health_report.py`; it writes `.health/last_run.json` on Slack POST failure and a `.health/posted` sentinel on success. The workflow has a final `if: always()` step that posts a generic error heartbeat when the sentinel is missing (main.py died before reaching its own heartbeat post).
