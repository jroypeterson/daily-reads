# #207 — am I subscribed to the market commentary I should be?

**Audited 2026-08-06 (autonomous session B).** Inventory from `sources.py` (the registry
that actually drives ingestion), not from memory of what was signed up for.

## What arrives today: 22 sources, and one whole category is empty

| category | n | sources |
|---|---:|---|
| finance_macro | 10 | A Letter a Day\*, Bloomberg, Bloomberg (subscription notices), Consilient Observer\*, MBI\*, Morning Brew, Scuttleblurb\*, The Transcript\*, Value Investors Insight\*, WSJ Newsletters |
| healthcare_daily | 4 | BioSpace, Fierce Biotech, Fierce Pharma, STAT News |
| consulting | 2 | BCG, McKinsey |
| journals | 2 | NEJM, NEJM Weekend Briefing |
| finance_weekly | 1 | Stratechery |
| healthcare_policy | 1 | KFF Health News |
| healthcare_weekly | 1 | Biotech Primer\* |
| broad_curious | 1 | The Atlantic |

`*` = always-read. **7 of 22 are always-read**, and the coverage is genuinely good on two
axes JP already cares about: value-investing letters (Scuttleblurb, MBI, VII, Consilient
Observer, A Letter a Day) and healthcare trade press.

**The gap is a category, not a source.** There is **zero institutional market commentary** —
no sell-side research summary, no asset-manager letter, no bank economics. Every macro read
currently arrives via general press (Bloomberg, WSJ, Morning Brew) or a value-investing
newsletter. For a healthcare-focused SMID investor, the missing layer is the one that frames
rates, credit, positioning and flows — the context in which SMID healthcare de-rates or
re-rates regardless of company news.

## Recommended additions

Split by how confident I am, because the difference matters when the next step is "go sign up".

### Verified this session — free, with a real signup path

| source | why it fits | signup |
|---|---|---|
| **Apollo — The Daily Spark** (Torsten Sløk) | daily, chart-led, US economy + inflation + capital markets; the single most-quoted free macro note on the buy side. Sløk spent 15 years sell-side, top-ranked by Institutional Investor for a decade | `apolloacademy.com/daily-spark/subscription/` — confirmed free |
| **Oaktree — Howard Marks memos** | the reference text on cycles and risk posture; irregular, low volume, high signal. Free archive since 1990 | `oaktreecapital.com` memo archive; **also a podcast** ("The Memo by Howard Marks") |

### Named but NOT verified this session

I did not confirm signup mechanics or whether they remain free, so treat these as candidates
to check rather than facts:

- **GMO** quarterly letters — long-horizon asset-class forecasts; the counterweight to
  momentum-driven positioning.
- **Verdad** (Dan Rasmussen) weekly research — small/micro-cap, leverage and value factor
  work; the closest thing to academic evidence on the SMID cohort JP invests in.
- **Klement on Investing** — daily, behavioural/market-structure, unusually short.
- **Research Affiliates** — factor and valuation research.
- **Healthcare-specific sell-side** (Leerink, TD Cowen, Jefferies, Piper) — the obvious gap
  for HC SMID specifically, but these are **paid and relationship-gated**; realistically this
  is "get on a distribution list", not "subscribe".

## Deliberately NOT recommended — the fleet already covers these

Worth stating, because an audit that ignores the rest of the fleet re-proposes solved work:

| candidate | already covered by |
|---|---|
| Damodaran valuation data/posts | the `Damodaran` project (`project_damodaran_data`) |
| Yardeni charts | `macro_monitor`, board rows #105 / #109 |
| FactSet Earnings Insight | board rows #284 and #57 — already filed, not yet built |
| StreetAccount | `sa-monitor` (halts → `#street-account`) |
| Fed speeches / FOMC | `hc_macro_policy` fed-speeches lane |
| GAO / CBO / Federal Register | `gov_reports`, `fr-feed` |
| Podcast-form commentary | `podcast_triage` — and note the Howard Marks memo is *also* a podcast, so it could land there instead of here |

## The one structural note

`sources.py` carries only `category` and `frequency`, not **provenance class** — there is no
field distinguishing "primary research" from "aggregated press". That is why the gap above
was invisible until someone counted: 10 sources in `finance_macro` reads like strong macro
coverage, and it is actually one newspaper, one newsletter aggregator and eight
value-investing letters. If more commentary is added, a `kind` field
(`press` / `letter` / `research` / `trade`) would make the next audit mechanical instead of
manual.

## ⚑ For JP

Two decisions, both cheap:

1. **Apollo Daily Spark and Oaktree memos** — say yes and I add them to `sources.py`; the
   signup is yours (email confirmation), the wiring is one line each plus a sender-address
   verification via `validate_source.py`.
2. **Is this even the right shape?** The alternative reading of "am I subscribed to what I
   should be" is *sell-side distribution lists*, which are relationship-gated and not a
   newsletter problem at all. If that is what you meant, this audit answers the wrong
   question and the real one belongs with the IR-signup work in `earnings_agent`.
