# Project Context

This file records design decisions and engineering rationale that are not obvious from the code alone. It is intended to help future maintainers and AI coding tools understand why the system is shaped the way it is.

Maintenance note:
- When you make a change that affects architecture, feedback flow, product behavior, operating assumptions, or important tradeoffs, update this file in the same change.
- This applies to both human maintainers and AI coding agents.

## Product Goal

Daily Reads is a personal, investor-oriented article curation system. It is not a generic news summarizer.

Core product intent:
- prioritize signal over breadth
- bias toward healthcare/biotech with secondary finance and tech/AI coverage
- deliver in surfaces already used daily
- learn reader preferences over time without hiding important behavior changes

## Canonical Feedback Paths

Feedback is split into two categories:

1. Daily scoring
- canonical path: email reply
- supported formats: `1 3`, `2 1 too generic`, `slot 3: okay`
- reason: email is private, low-friction, and already part of the reading workflow

2. Broader taste training
- canonical paths:
  - emails sent to `jroypeterson+taste@gmail.com`
  - messages tagged with Gmail label `taste`
  - local files dropped into a configured Dropbox watch folder
- fallback path: GitHub issue labeled `taste`
- reason: exemplars are richer than daily article ratings and should remain a separate signal, but they should enter through low-friction capture tools already used in normal reading workflows

Taste evidence and learned preferences follow a three-layer architecture:

1. `taste_evidence.json`: canonical evidence store. Every taste signal — positive exemplars, daily score-3 articles, daily score-1 misses — is one normalized record regardless of source (Dropbox, Gmail, GitHub Issue, daily scoring).

2. `learned_preferences.json` (v2): structured preference model with per-topic, per-source, per-style preference entries, each with discrete strength levels (strong/moderate/weak), direction (positive/negative), and evidence IDs linking back to `taste_evidence.json`.

3. `learned_preferences.md` and `taste_profile.md`: generated read-only views. Never source of truth.

The preference engine has two refinement cadences:
- Fast: lightweight recomputation from evidence counts and keyword matching. No API call. Runs on every update when no new exemplars are present.
- Slow (synthesis): Claude analyzes all evidence to discover/update structured topic, source, style, and avoid preferences. Triggered when a new exemplar arrives or 5+ new daily ratings accumulate.

The selector consumes `learned_preferences.json` v2 directly, rendering structured preference sections (STRONG/MODERATE/AVOID) plus recent exemplar/miss headlines into the prompt.

Legacy files `external_exemplars.json` and `taste_submissions.json` are superseded by `taste_evidence.json`. A one-time migration in `project_data.py` converts existing data.

Each run should also persist:
- `artifacts/candidates/YYYY-MM-DD.json`: normalized candidate ledger for everything the system saw
- `artifacts/runs/YYYY-MM-DD.json`: selected digest snapshot
- `artifacts/triage/YYYY-MM-DD.json`: ranked backlog of additional candidates not chosen for the digest

There is also a lightweight analysis entry point:
- `analyze_history.py`: summarizes runs, candidates, triage backlog, feedback, learned preferences, and pending criteria review state from JSON artifacts
- it should increasingly serve as the main retrospective surface for understanding what the system selects, what gets scored well or poorly, and where learning signals are weak

Candidate normalization currently includes:
- basic URL canonicalization
- common tracking-parameter stripping
- rejection of obvious account/share/unsubscribe/non-article paths
- derived signals: source type, category, priority, HN score, ticker mentions, company name matching, and subsector tagging

Candidate sources are:
- Gmail newsletters (tier 1, ~21 sources defined in `sources.py`)
- Hacker News top stories (tier 2)
- RSS feeds (tier 2, ~38 feeds defined in `rss_feeds.py` covering healthcare, finance, tech/AI, and curiosity)

Ticker matching uses `tickers.json`, which is generated from the Coverage Manager coverage universe CSV via `sync_tickers.py`. It contains:
- ~1,080 tickers across healthcare (biopharma, medtech, healthcare services), tech, and other
- ~2,000 company name → ticker mappings for headline matching (e.g., "Centene" → CNC)
- ~70 subsector groupings (e.g., Mgd Care, Post-Acute, HIT, CRO, Hospitals)
- when the coverage universe changes, run `python sync_tickers.py` to regenerate

Selection should prefer structured candidate records over raw source text where possible.

Exemplar ingestion currently has two different operating modes:
- `process_email_exemplars.py`: safe for GitHub Actions because Gmail is already part of the hosted workflow
- `process_dropbox_exemplars.py`: intentionally local-only because GitHub Actions cannot see the user's Dropbox filesystem

Current Dropbox operating assumption:
- default watch folder: `C:\Users\jroyp\Dropbox\Claude Folder\daily-reads-taste-samples`
- after ingestion, processed files are moved to the subfolder `Incorporated into taste preferences`
- intended cadence: once daily via a local scheduled task, not via GitHub Actions
- the task helper runs native Windows Python (not WSL), registers a daily time trigger plus an at-logon fallback, with catch-up-after-missed-run behavior enabled
- the task does `git fetch` + `git pull --rebase --autostash -X ours origin main` BEFORE running any ingestion scripts. This is critical: both the local task and the GitHub Actions workflow touch `learned_preferences.json`/`learned_preferences.md`, and without an upfront rebase the two histories diverge daily and the local Dropbox copy stops seeing remote daily-reads commits
- after ingestion, the task commits and pushes `taste_evidence.json` so the next GitHub Actions run can see new evidence
- after ingestion, `process_exemplar_content.py` extracts text previews from local archived files so preference learning can use more than filenames and free-text notes

## Why Email Is The Source Of Truth For Scoring

Multiple delivery surfaces exist, but scoring should converge into one ingestion path.

Reasoning:
- email replies are easy to parse
- email avoids adding backend infrastructure
- Slack interactivity would require a Slack app and a public endpoint
- GitHub Pages cannot securely write feedback directly without an awkward token flow

Implication:
- Slack rating links open prefilled email drafts
- GitHub Pages rating links open prefilled email drafts
- `process_email_feedback.py` is the canonical scorer ingestion path
- feedback records should be enriched with article identity whenever a run artifact is available

## Why GitHub Pages Is Static

GitHub Pages is used as a read surface, not an authenticated write surface.

Reasoning:
- direct writes from Pages required a GitHub token in the URL
- that path was fragile and not realistic for daily use
- localStorage-based fallback looked like feedback was saved when it was not part of the real learning loop

Current intent:
- Pages shows the digest
- Pages offers email scoring links
- Pages links to taste submission issues
- All delivery surfaces (email, Slack, Pages) include an "Also considered" section with up to 10 triage candidates (numbered #5-#14) that can be optionally rated using the same feedback format

## Selection Validation Philosophy

Prompt instructions alone are not trusted to preserve product quality.

The system validates selected articles before delivery to enforce:
- required slots 1, 2, and 3
- optional slot 4
- unique slots
- unique sources
- valid URLs
- required summary fields

Reasoning:
- the LLM is advisory for selection, not authoritative for system invariants
- core editorial constraints should be enforced in code

## Feedback Scale Decision

Daily scoring currently uses a 1-3 scale:
- `3 = Strong pick`
- `2 = Fine`
- `1 = Miss`

Reasoning:
- the project has sparse feedback volume
- a 1-5 scale implies precision that the data does not yet support
- 1-3 is easier to apply consistently across email and Slack launch links

Slots 1-4 are digest articles; slots 5-14 are triage ("Also considered") articles. Triage rating is optional but flows through the same feedback pipeline and taste evidence bridge.

## Criteria Update Strategy

The system is allowed to learn from feedback, but criteria updates are staged rather than silently activated.

Current flow:
- after enough feedback days, the system generates `selection_criteria_proposed.md`
- metadata is stored in `criteria_update_state.json`
- a notification is sent via Gmail and Slack, including model-written summary bullets and concrete diff highlights against the active criteria file
- user can `Accept`, `Reject`, or `Request modifications`
- decisions are processed by `process_criteria_feedback.py`

Reasoning:
- direct self-rewrites can drift silently
- criteria files encode product intent, not just tuning
- staged proposals preserve visibility while keeping adaptation automatic

## Why Accept/Reject Uses GitHub Issues

Decision actions are routed through GitHub issues rather than a custom backend.

Reasoning:
- the repo already has issue-processing infrastructure
- issue links work from both email and Slack
- it keeps approvals auditable
- modification requests can include free-form notes

Tradeoff:
- this is not as seamless as a dedicated UI, but much simpler to operate

## Current Known Limitations

- `docs/index.html` is an artifact and may lag until the next run regenerates it
- older feedback entries may still be slot-centric until enough new enriched entries accumulate
- newsletter URL extraction is improved but still heuristic and should keep getting better
- candidate normalization is intentionally lightweight and should get smarter over time
- email exemplar ingestion records attachment metadata but does not yet fetch attachment bytes or parse attachment content
- Dropbox scheduling is only configured if the local user installs the provided Windows scheduled task helper (now runs via native Windows Python, no longer requires WSL)
- Pages is intentionally simple and not a full management UI

## Recommended Next Steps

When improving the system further, prioritize:

1. accumulate feedback and taste evidence — the preference engine needs real data before it can be validated
2. add exemplar content extraction for Gmail attachments (bytes fetch + parse)
3. improve novelty signals — detect when an RSS/newsletter candidate is a rehash of yesterday's story
4. consider SQLite once JSON stores become unwieldy (fix the model shape first, then storage)
