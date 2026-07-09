# Project Brief — read this first (for reviewers, human or AI)

This file exists so a reviewer can (1) judge how close the project is to its
intended goal and (2) understand the key design decisions **before** giving
feedback. For mechanics (architecture, run steps, secrets, sources) see
`README.md`; for the operating manual / gotchas see `CLAUDE.md`. This brief does
not re-describe how the pipeline works — it carries the intent and self-assessment
the repo can't.

> When reviewing, weigh findings against the **success criteria** (§2) and the
> **non-goals / accepted tradeoffs** (§4) below — several "obvious improvements"
> (pull from Reader, narrower Gmail window, per-host URL rules, auto-applying
> criteria changes) were considered and deliberately declined. Say so if you
> think a declined option is actually worth it, but engage with the stated
> rationale rather than re-proposing it cold.

---

## 1. Intended goal (the "why")

Give the owner — a solo, part-time, healthcare-focused investor automating
"signal from noise" — a **single daily digest of ~4 genuinely worth-reading
articles** (healthcare/biotech, finance, tech/AI, wildcard), pulled from the
newsletters/feeds he already subscribes to plus Hacker News and web search, so
he stops manually triaging a cluttered inbox. The differentiator over a plain
newsletter aggregator is **taste**: the digest should learn what *this* reader
finds substantive (value/quality investing, credit, healthcare, the
serial-acquirer playbook, SF&F as wildcard) and get better over time from his
feedback, not just match keywords. Success = he opens the digest, trusts the 4
picks, and reads them — and the few he rates teach the selector.

## 2. Success criteria — and current status

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Ship ~4 curated articles daily, unattended | ✅ Done | `main.py` on GH Actions daily 12:00 UTC (7am ET) + `workflow_dispatch`; status `live` |
| 2 | Multi-source ingest (newsletters + HN + web) | ✅ Done | `gmail_reader.py` (7-day window), Hacker News, web search; `rss_feeds.py` |
| 3 | Picks are *real articles with substance*, not headlines/paywalls | ✅ Done | Per-candidate fetch (trafilatura→Jina→Tavily) + Claude verification; skipped picks replaced; paywall falls back to newsletter summary |
| 4 | No dead links shipped | ✅ Done | `validate_delivery_urls` pre-flight; `url_resolver.py` shape-based tracker-unwrap + homepage dead-end drop; Substack redirect decode |
| 5 | Taste learning from feedback | 🟡 Partial | Email-reply + GitHub-issue ratings → `feedback_log.json`; `preference_learning.py` / `learned_preferences.*`. Working, but the rich signal is the seeded `taste_profile.md`, not yet much earned feedback |
| 6 | Earn-not-guess taste model | 🟡 Seeded | `taste_profile.md` seeded 2026-06-04 from ~3,860 Readwise highlights; `process_taste.py::rebuild_profile()` only fires at **3+** GitHub taste-issue exemplars — currently 0 earned, so refinement loop is unexercised |
| 7 | Criteria evolve with human sign-off | ✅ Done | After 7+ feedback days Claude proposes to `selection_criteria_proposed.md`; accept/reject/modify via GitHub issue; applied next run (not auto-applied) |
| 8 | Feed top picks into the reading workflow | ✅ Done | `deliver_reader` pushes top picks + always-read to Readwise Reader (`later`), idempotent, token-gated; TickTick + GitHub Pages archive |
| 9 | No silent failures; operator visibility | ✅ Done | 8-layer resilience model (canary, daily source audit, pre-commit hook, section auto-splitter, operator alert, `health/v1` heartbeat to `#status-reports`); see README "Resilience model" |
| 10 | Weekly self-report on health/quality | ✅ Done | `weekly_report.py` Fridays — source health roster, selection quality, feedback trends, URL stats |
| 11 | Outbound email digest | ⬜ Paused | `deliver_gmail` gated off in scheduled run since 2026-05-18 (`DELIVER_GMAIL_ENABLED:"false"`); Slack/TickTick/Pages carry delivery. Deliberate, reversible |

**Overall verdict: v1 goal is met and the pipeline is live and well-hardened.**
The honest soft spot is the *learning* half (§5–6): the taste model is strong but
**seeded, not yet earned** — the feedback→criteria→profile loop is built and
tested but barely exercised because the owner has submitted few ratings/exemplars.
Delivery, resilience, and curation are solid; "gets better from *my* feedback over
time" is unproven in production.

## 3. Key design decisions (and why)

1. **7-day rolling Gmail window, re-ingested daily, deduped by `candidate_id`.**
   Counterintuitive (re-reads the whole week every run) but deliberate: a single
   missed run or a late-arriving newsletter (the "Scuttleblurb miss" pattern)
   would otherwise drop articles forever. Dedupe makes re-ingestion harmless.
   Don't narrow this without reading `memory/project_resilience.md`.
2. **Verify the article body, don't trust the headline.** Each shortlisted pick
   is fetched and Claude-checked for real substance before it ships, with a
   trafilatura→Jina→Tavily fallback chain and a newsletter-summary fallback for
   paywalls. Curation quality > coverage.
3. **Shape-based URL resolution, not per-host rules.** `url_resolver.py` unwraps
   any tracker-shaped subdomain and drops anything resolving to a publisher
   homepage, so new newsletter platforms work without per-host maintenance.
4. **Taste model seeded from the Readwise *library*, not from article exemplars.**
   Clipped highlights are a denser, more honest signal of taste than thumbs on a
   handful of digests, so `taste_profile.md` was bootstrapped from ~3,860
   highlights. The earned-exemplar rebuild treats that seed as the standing prior
   (preserve/refine), never blanks it. This is why `taste_evidence.json` shows 0
   exemplars yet the profile is rich — not a bug.
5. **Human-in-the-loop on criteria changes.** Claude *proposes*; the owner
   accepts/rejects/modifies via GitHub issue. The selector never silently rewrites
   its own selection criteria.
6. **Push to Reader, never pull.** Reader gets top picks + always-read; ingesting
   Reader docs back as candidates was intentionally not built (avoids a feedback
   loop and keeps Reader as the read-queue, not a source). REST token, not the
   interactive MCP, because the cron can't reach interactive MCP servers.
7. **Email is the single scoring pipeline.** Even Slack rating links open a
   prefilled email draft, so all ratings funnel through one path into
   `feedback_log.json`.

## 4. Non-goals / accepted tradeoffs

- **Not** a comprehensive reader — it ships ~4 picks, accepting that good
  articles get dropped. Precision over recall, by design.
- **Not** a real-time feed — one batch run a day. Fine for a long-form reading habit.
- **Not** a Reader→digest pull; the integration is push-only (see §3.6).
- **Not** auto-evolving criteria — proposals always wait for human sign-off (§3.5).
- **Outbound HTML email is intentionally paused** (not broken); Slack/TickTick/Pages
  are the live surfaces. One env line resumes it.
- Uses headless Gmail OAuth + Readwise REST token (not interactive connectors)
  because everything must run unattended under GH Actions.

## 5. Known gaps / candidate next steps (feedback welcome here)

- **The learning loop is unexercised.** The biggest gap is product, not code: few
  earned ratings/exemplars exist, so criteria-evolution and `rebuild_profile()`
  have rarely (if ever) fired in anger. Is the friction the email-reply scoring
  UX? Worth lowering the bar to generate signal?
- **Two delivery surfaces depend on tokens that expire** (TickTick especially);
  expiry degrades to `partial` with an alarm, but there's no auto-refresh.
- **Wake-time network race** (fleet-wide): a caught-up scheduled run can fire
  before DNS is up. This is a GH-Actions-hosted job (less exposed than the local
  Windows taste-ingestion task), but the local task could still hit it — a
  retry-with-backoff wrapper would harden it (see workspace `CONVENTIONS.md` §3).
- **Local + CI both write `learned_preferences.*`** and can diverge; mitigated by
  a `git pull --rebase --autostash -X ours` pre-step in the local task, but it's a
  two-writer design worth a second look.
- **Selection-quality measurement is thin** — `analyze_history.py` + the weekly
  report give retrospective stats, but there's no crisp "are the picks actually
  good?" metric beyond the owner's own ratings (which are sparse, per above).

## 6. How to evaluate

- **Mechanics / architecture / secrets:** `README.md` (canonical) and `CLAUDE.md`
  (gotchas). Don't re-derive them.
- **Entry points:** `main.py` (orchestrator + delivery + heartbeat), `gmail_reader.py`
  (ingest + candidate building + Substack unwrap), `url_resolver.py` (link safety),
  `preference_learning.py` / `process_taste.py` (taste-learning core).
- **Core logic worth scrutinizing:** the candidate→shortlist→verify→deliver path in
  `main.py`; the taste model in `taste_profile.md` + how `preference_learning.py`
  feeds it into the selector prompt; and the criteria-evolution gate in
  `process_criteria_feedback.py`.
- **Tests:** `test_daily_reads.py` (~33 tests, single file at repo root — note there
  is no `tests/` dir). Run `python -m pytest test_daily_reads.py -q`.
- **Most useful feedback:** (a) is the *taste-learning* design sound, and what would
  make the feedback loop actually generate signal given a low-effort owner? (b) is
  the 4-pick precision-over-recall bet right, or is too much good material dropped?
  (c) verification/URL-safety edge cases; (d) which §5 gap to close first.
