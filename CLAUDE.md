# CLAUDE.md

## Git workflow

After making changes to this project, always commit and push to GitHub:
1. Stage the changed files (prefer naming specific files over `git add -A`)
2. Commit with a clear message describing the changes
3. Push to `origin main`

Do not leave local changes uncommitted. The project should stay in sync with GitHub.

Note: the local Windows scheduled task (daily Dropbox taste ingestion) commits to the same branch, so **two writers share `learned_preferences.json`/`.md`**.

**Timestamp-churn conflicts were fixed at the source on 2026-07-25** — `preference_learning.apply_evidence()` now stamps `updated_at`/`last_updated` only when a strength or evidence-id set actually changes, so a no-op learning run produces a no-op diff and the two writers stop colliding over nothing. Before that fix the file was rewritten with a fresh clock every run; six local commits had accumulated that were byte-identical to the remote once timestamps were stripped (all 18 topics), and the standing advice here was to resolve by keeping `HEAD`. If you *do* still hit a conflict in these files, it now means a **real** preference divergence — look at the strengths and evidence ids, don't just take one side. Invariant guarded by `test_unchanged_preferences_do_not_restamp_timestamps`.

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

## Readwise Reader push

`deliver_reader` in `main.py` pushes the day's **top picks** (`articles`) + **always-read** items into Readwise Reader so they're queued to read in the app. Uses the Readwise REST API (`POST https://readwise.io/api/v3/save/`), NOT the interactive MCP — the cron can't reach interactive MCP servers. Auth is the static personal token in `READWISE_TOKEN` (header `Authorization: Token <token>`), set as a GH Actions secret and kept locally in `daily-reads/.env` (gitignored). Mint/rotate at https://readwise.io/access_token.

- **What's pushed:** top picks (tagged `daily-reads` + `top-pick`) and always-read items (tagged `daily-reads` + `always-read`). The pull direction (ingesting Reader docs as digest candidates) was intentionally not built.
- **Where:** location `later` by default; override with `READWISE_READER_LOCATION` (e.g. `shortlist`).
- **NOT idempotent — Reader does not dedupe by URL.** This entry claimed it did, and that was wrong. Measured 2026-09-06 with a controlled probe: two saves of one URL return two different document ids, for a real https URL and a synthetic one alike; the 200-vs-201 reading was a misinterpretation.
- **The hazard is latent, not realised.** A full sweep of all 7,853 articles the same day found **0 duplicate source_urls** across the 316 `daily-reads` documents — the 14-day rolling window has been enough so far. (An earlier count of "three items with seven copies" was wrong: `source_url` came back null under a filtered field request, so the grouping fell back to *title*, and recurring formats like "Catalyst Watch" and "Value Investor Insight New Issue" are 11 and 4 genuinely different articles sharing one headline. Group these by URL, never by title.)
- **What actually prevents duplicates:** `reader_pushed` in `delivered_state.json`, a permanent URL→date map written by `deliver_reader` and checked before every save. It is deliberately **never pruned**. The rolling delivered-id window cannot do this job: an always-read source keeps listing the same URL (a quarterly letter sits on a fund's page for months), so it ages out of the window and is pushed again — the window fails precisely on the long-lived items. Guarded by `test_deliver_reader_skips_urls_already_in_reader` and `test_deliver_reader_records_what_it_pushed`, both mutation-checked.
- **`load_delivered_state` returns a NEW dict**, so any key it does not explicitly carry across is destroyed on the next save. If you add state, add it there too — `test_load_delivered_state_preserves_reader_pushed` exists because `reader_pushed` would otherwise have been silently dropped.
- **Failure handling:** a 401/403 (bad token) posts a `#status-reports` alarm and marks the run `partial`; other per-item failures are counted and added as a partial reason. A single 429 retry honors `Retry-After`.
- If `READWISE_TOKEN` is unset the push is skipped cleanly (no error) — so local `python main.py` without the token just no-ops this step.

## Taste profile

`taste_profile.md` is a **general-purpose** content preference model (no daily-reads/source references — reusable for podcasts/videos/articles too). It feeds `preference_learning.py` and the digest's scoring prior.

- **Seeded 2026-06-04 from a full Readwise-library analysis** (~3,860 of 4,255 highlights via the readwise MCP), NOT from submitted article exemplars — so the file is richly populated even though `taste_evidence.json` has 0 `positive_exemplar` rows. Don't be confused by that mismatch; the provenance is in an HTML comment at the top of the file. Full narrative persona lives at `../READING_PERSONA.md`.
- `process_taste.py` → `rebuild_profile()` only fires once **3+** GitHub-issue exemplars accumulate (`Taste: <headline>` issues). When it does, it passes the current file to Claude as the `CURRENT PROFILE` prior to preserve/refine — so the Readwise seed is the standing prior, not throwaway. Treat it that way; don't blank it.

## Readwise highlight → taste exemplar ingest

`process_readwise_exemplars.py` (daily workflow step, before "Update learned preferences") pulls recent Readwise highlights via the reusable fetch-only client `readwise_client.py` (v2 `/api/v2/export/`, same `READWISE_TOKEN` as the Reader push; 429/Retry-After backoff built in). Each highlighted **article** becomes one `kind="positive_exemplar"` record in `taste_evidence.json` (`source_channel="readwise"`, highlight texts as `metadata.extracted_text_preview`, highlight notes as `note`) — identical shape to the email/Dropbox/issue intake, so `preference_learning.py` synthesis and the ranker's `load_learned_preferences_summary()` pick them up with no changes.

- **Books/tweets/podcasts are excluded** — the article-taste loop models article taste; the standing `taste_profile.md` prior was already seeded from the full book+article library.
- **State:** `readwise_state.json` holds the incremental `updatedAfter` cursor (10-min overlap for clock skew; id-dedupe absorbs it). Committed by the workflow. First run = 30-day lookback.
- **Cap:** max 25 new exemplars per run; on overflow the cursor is held back so the remainder drains on later runs (nothing lost).
- **Failure mode:** missing/rejected token or API failure prints a loud warning + posts a Block Kit alert to `#status-reports`, then exits 0 — digest proceeds without fresh exemplars.
- **Reuse:** `readwise_client.fetch_export()` is deliberately taste-agnostic — the planned Anki pipeline should reuse it rather than re-implementing the pull.

## Outbound email digest — paused

As of 2026-05-18 the HTML email digest (`deliver_gmail` in `main.py`) is paused in the scheduled GH Actions run via `DELIVER_GMAIL_ENABLED: "false"` in `.github/workflows/daily.yml`. The function is gated on that env var (default `"true"` so local `python main.py` still sends if the user wants to test). To resume: delete the env line in `daily.yml` or flip it to `"true"`. Slack/TickTick/Pages/health-heartbeat were never paused.

## Health reporting

Per `HEALTH_REPORTING.md` at the Claude Folder root. Cadence: **daily at 12:00 UTC** (7am ET) via `.github/workflows/daily.yml`. Every run posts a `health/v1` Block Kit heartbeat to `#status-reports` at end of `main.py` — `ok` on clean completion, `partial` if Slack digest delivery failed or TickTick token expired, `error` on uncaught exception or no-articles-after-2-attempts. URL liveness drops surface as informational warnings. The heartbeat helper is `health_report.py`; it writes `.health/last_run.json` on Slack POST failure and a `.health/posted` sentinel on success. The workflow has a final `if: always()` step that posts a generic error heartbeat when the sentinel is missing (main.py died before reaching its own heartbeat post).
