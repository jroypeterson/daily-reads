# Article Selection Criteria

## Slot Definitions

Each daily digest contains **4 articles** (or 3 if the AI slot is skipped):

### Slot 1: Healthcare / Biopharma (required)
- FDA decisions, clinical trial data readouts, M&A, pipeline news
- Priority: coverage universe tickers (see tickers.json healthcare bucket)
- Bonus: catalysts with near-term investment implications
- Domains: endpoints.com, statnews.com, fiercepharma.com, fiercebiotech.com

### Slot 2: Finance / Markets (required)
- Macro moves, earnings, sector rotation, policy impact on markets
- Priority: healthcare-adjacent finance (drug pricing, reimbursement, payer dynamics)
- Domains: wsj.com, bloomberg.com, morningbrew.com

### Slot 3: Tech / AI (required)
- AI breakthroughs, infrastructure, enterprise adoption
- Priority: AI applied to healthcare/biotech, or foundational model advances
- Domains: stratechery.com, thesequence.substack.com, importai.net

### Slot 4: Wildcard / Curiosity (optional — drop if no strong candidate)
- Consulting insights, cross-domain thinking, surprising science
- Must pass the "would I forward this?" test
- Domains: mckinsey.com, bcg.com, nautil.us, theatlantic.com

## Signal Weighting

1. **Ticker match** (+3): Article mentions a ticker in tickers.json
2. **High-priority source** (+2): Source marked priority=high (weekly/periodic newsletters, consulting)
3. **Catalyst proximity** (+2): FDA date within 30 days, earnings within 7 days, conference presentation
4. **Novelty** (+1): Not a rehash of yesterday's story
5. **Actionability** (+1): Reader can act on this (trade idea, portfolio review, strategic insight)

## Selection Rules

- Never pick 2 articles from the same source
- Prefer depth over breadth — one deep analysis > two thin summaries
- If a weekly/periodic newsletter arrives, it gets priority consideration
- Weekend digests can be lighter (3 articles fine)

## Output Format

For each selected article, provide:
- **headline**: Article title
- **source**: Publication name
- **url**: Direct link
- **slot**: Which slot (1-4)
- **summary**: 2-3 sentence summary
- **why_it_matters**: 1 sentence on investment/strategic relevance
- **signal_tags**: List of matched signals (e.g., ["ticker_match:MRNA", "catalyst_proximity"])

## Feedback Integration

This document evolves based on user feedback. After 7+ days of ratings:
- Articles rated 4-5: reinforce those signal patterns
- Articles rated 1-2: reduce weight for those patterns
- Rewrite this document with updated weights and preferences
