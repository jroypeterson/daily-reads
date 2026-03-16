"""Daily Reads — Main orchestration script."""

import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode

import anthropic
import requests

from gmail_reader import fetch_newsletters
from sources import SOURCES

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: str, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else []


def save_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def feedback_url(date: str, slot: int, score: int, headline: str) -> str:
    """Generate a pre-filled GitHub Issue URL for one-tap feedback."""
    truncated = headline[:80]
    title = f"Feedback: {date} slot{slot} score{score}"
    body = f"Article: {truncated}\n\nOptional note: "
    params = urlencode({"labels": "feedback", "title": title, "body": body})
    return f"https://github.com/jroypeterson/daily-reads/issues/new?{params}"


# ---------------------------------------------------------------------------
# [GMAIL SCAN]
# ---------------------------------------------------------------------------

def gmail_scan() -> list[dict]:
    section("GMAIL SCAN")
    try:
        items = fetch_newsletters(hours_back=26)
        print(f"Found {len(items)} newsletter emails")
        sources_found = set(i["source_name"] for i in items)
        for s in sorted(sources_found):
            count = sum(1 for i in items if i["source_name"] == s)
            print(f"  - {s}: {count} email(s)")
        return items
    except Exception as e:
        print(f"Gmail scan failed: {e}")
        print("Continuing with Tier 2 sources only...")
        return []


# ---------------------------------------------------------------------------
# [TIER2 SCAN]
# ---------------------------------------------------------------------------

def tier2_scan() -> list[dict]:
    section("TIER2 SCAN")
    items = []

    # Hacker News top stories
    print("Fetching Hacker News top stories...")
    try:
        resp = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
        )
        top_ids = resp.json()[:30]
        for story_id in top_ids:
            story = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                timeout=5,
            ).json()
            if story and story.get("url"):
                items.append({
                    "source_name": "Hacker News",
                    "subject": story.get("title", ""),
                    "snippet": story.get("title", ""),
                    "urls": [story["url"]],
                    "tier": 2,
                    "category": "tech_ai",
                    "priority": "normal",
                    "score": story.get("score", 0),
                })
        print(f"  Got {len(items)} HN stories")
    except Exception as e:
        print(f"  HN fetch failed: {e}")

    return items


# ---------------------------------------------------------------------------
# [FEEDBACK CHECK]
# ---------------------------------------------------------------------------

def feedback_check() -> dict:
    section("FEEDBACK CHECK")
    feedback = load_json("feedback_log.json", [])
    result = {"low_scores": [], "should_rewrite": False}

    if not feedback:
        print("No feedback yet.")
        return result

    # Check yesterday's ratings
    today = datetime.now(timezone.utc).date()
    yesterday_entries = [
        f for f in feedback
        if f.get("date", "")[:10] == str(today.replace(day=today.day - 1))
    ]
    low = [f for f in yesterday_entries if f.get("score", 5) <= 3]
    if low:
        result["low_scores"] = low
        print(f"Found {len(low)} low-rated articles from yesterday")

    # Check if 7+ days of feedback → trigger rewrite
    unique_dates = set(f.get("date", "")[:10] for f in feedback)
    if len(unique_dates) >= 7:
        result["should_rewrite"] = True
        print("7+ days of feedback accumulated — will trigger criteria rewrite")
    else:
        print(f"{len(unique_dates)} day(s) of feedback so far (need 7 for rewrite)")

    return result


# ---------------------------------------------------------------------------
# [ARTICLE SELECTION]
# ---------------------------------------------------------------------------

def select_articles(
    gmail_items: list[dict],
    tier2_items: list[dict],
    feedback_info: dict,
) -> list[dict]:
    section("ARTICLE SELECTION")

    # Load selection criteria and tickers
    with open("selection_criteria.md", "r") as f:
        criteria = f.read()
    tickers = load_json("tickers.json", {})

    # Build content for Claude
    newsletter_text = ""
    for i, item in enumerate(gmail_items, 1):
        newsletter_text += f"\n--- Newsletter {i} ---\n"
        newsletter_text += f"Source: {item['source_name']} ({item['category']})\n"
        newsletter_text += f"Priority: {item['priority']}\n"
        newsletter_text += f"Subject: {item['subject']}\n"
        newsletter_text += f"Snippet: {item['snippet']}\n"
        newsletter_text += f"URLs: {', '.join(item['urls'][:5])}\n"

    tier2_text = ""
    for i, item in enumerate(tier2_items, 1):
        tier2_text += f"\n--- Tier2 {i} ---\n"
        tier2_text += f"Source: {item['source_name']}\n"
        tier2_text += f"Title: {item['subject']}\n"
        tier2_text += f"URL: {item['urls'][0] if item['urls'] else 'N/A'}\n"
        if item.get("score"):
            tier2_text += f"HN Score: {item['score']}\n"

    feedback_context = ""
    if feedback_info.get("low_scores"):
        feedback_context = "\n\nFEEDBACK NOTE: Yesterday had low-rated articles. Patterns to avoid:\n"
        for f in feedback_info["low_scores"]:
            feedback_context += f"- Slot {f.get('slot')}: score {f.get('score')}, note: {f.get('note', 'N/A')}\n"

    system_prompt = f"""You are a daily article curator for an investor focused on healthcare/biotech,
with secondary interest in tech/AI and macro markets.

SELECTION CRITERIA:
{criteria}

TICKER UNIVERSE (abbreviated — {len(tickers.get('healthcare', []))} healthcare,
{len(tickers.get('tech', []))} tech, {len(tickers.get('other', []))} other):
Healthcare sample: {', '.join(tickers.get('healthcare', [])[:50])}
Tech sample: {', '.join(tickers.get('tech', [])[:30])}
{feedback_context}

Select exactly 4 articles (or 3 if no good wildcard candidate).
Use the web_search tool if you need to verify or supplement any article.

Return ONLY valid JSON — an array of objects with these keys:
headline, source, url, slot (1-4), summary, why_it_matters, signal_tags
"""

    user_content = f"""Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

=== GMAIL NEWSLETTERS ===
{newsletter_text if newsletter_text else "(No Gmail newsletters found today)"}

=== TIER 2 SOURCES ===
{tier2_text if tier2_text else "(No Tier 2 items found)"}

Select the best 4 (or 3) articles for today's digest. Return JSON only."""

    print("Calling Claude for article selection...")
    client = anthropic.Anthropic()

    # Use tool for web search capability
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        messages=[{"role": "user", "content": user_content}],
    )

    # Extract JSON from response
    articles = []
    for block in response.content:
        if block.type == "text":
            text = block.text.strip()
            # Try to parse JSON from the response
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if json_match:
                try:
                    articles = json.loads(json_match.group())
                    break
                except json.JSONDecodeError:
                    pass

    if not articles:
        print("WARNING: Could not parse article selection from Claude response")
        print("Raw response blocks:")
        for block in response.content:
            if block.type == "text":
                print(block.text[:500])
        return []

    print(f"Selected {len(articles)} articles:")
    for a in articles:
        print(f"  Slot {a.get('slot')}: {a.get('headline', '?')[:60]}")
        print(f"    Source: {a.get('source')} | Signals: {a.get('signal_tags', [])}")

    return articles


# ---------------------------------------------------------------------------
# [DELIVERY: GMAIL]
# ---------------------------------------------------------------------------

def deliver_gmail(articles: list[dict]):
    section("DELIVERY: GMAIL")
    try:
        import base64
        from email.mime.text import MIMEText
        from gmail_reader import get_gmail_service

        service = get_gmail_service()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slot_emojis = {1: "🧬", 2: "📊", 3: "🤖", 4: "🌀"}

        html = f"""<html><body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; background: #1a1a2e; color: #eee; padding: 20px;">
<h1 style="color: #e94560;">📰 Daily Reads — {today}</h1>
"""
        for a in articles:
            slot = a.get("slot", 0)
            emoji = slot_emojis.get(slot, "📌")
            html += f"""
<div style="background: #16213e; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 4px solid #e94560;">
  <h2 style="margin: 0 0 8px 0;">{emoji} {a.get('headline', 'Untitled')}</h2>
  <p style="color: #a8a8b3; margin: 4px 0; font-size: 13px;">{a.get('source', '')} · Slot {slot}</p>
  <p style="margin: 8px 0;">{a.get('summary', '')}</p>
  <p style="color: #e94560; font-style: italic; margin: 8px 0;">💡 {a.get('why_it_matters', '')}</p>
  <p style="margin: 8px 0;"><a href="{a.get('url', '#')}" style="color: #0fbcf9;">Read article →</a></p>
  <p style="margin: 8px 0;">
    <a href="{feedback_url(today, slot, 5, a.get('headline', ''))}" style="text-decoration: none; background: #1a1a40; border: 1px solid #333; border-radius: 4px; padding: 4px 10px; color: #eee; font-size: 13px; margin-right: 6px;">👍 Good pick</a>
    <a href="{feedback_url(today, slot, 1, a.get('headline', ''))}" style="text-decoration: none; background: #1a1a40; border: 1px solid #333; border-radius: 4px; padding: 4px 10px; color: #eee; font-size: 13px;">👎 Not useful</a>
  </p>
  <p style="color: #666; font-size: 11px;">Signals: {', '.join(a.get('signal_tags', []))}</p>
</div>
"""
        html += """
<hr style="border-color: #333; margin: 24px 0;">
<p style="color: #666; font-size: 12px;">Or rate at
<a href="https://jroypeterson.github.io/daily-reads" style="color: #0fbcf9;">jroypeterson.github.io/daily-reads</a></p>
</body></html>"""

        msg = MIMEText(html, "html")
        msg["to"] = "jroypeterson@gmail.com"
        msg["subject"] = f"📰 Daily Reads — {today}"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        print("Email sent to jasonrpeterson@gmail.com")
    except Exception as e:
        print(f"Gmail delivery failed: {e}")


# ---------------------------------------------------------------------------
# [DELIVERY: SLACK]
# ---------------------------------------------------------------------------

def deliver_slack(articles: list[dict]):
    section("DELIVERY: SLACK")
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("No SLACK_WEBHOOK_URL set — skipping Slack delivery")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slot_emojis = {1: ":dna:", 2: ":chart_with_upwards_trend:", 3: ":robot_face:", 4: ":cyclone:"}

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📰 Daily Reads — {today}"}},
        {"type": "divider"},
    ]

    for a in articles:
        slot = a.get("slot", 0)
        emoji = slot_emojis.get(slot, ":pushpin:")
        up_url = feedback_url(today, slot, 5, a.get("headline", ""))
        down_url = feedback_url(today, slot, 1, a.get("headline", ""))
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{emoji} *<{a.get('url', '#')}|{a.get('headline', 'Untitled')}>*\n"
                    f"_{a.get('source', '')} · Slot {slot}_\n\n"
                    f"{a.get('summary', '')}\n\n"
                    f"💡 _{a.get('why_it_matters', '')}_\n\n"
                    f"<{up_url}|:thumbsup: Good pick>  <{down_url}|:thumbsdown: Not useful>"
                ),
            },
        })
        blocks.append({"type": "divider"})

    try:
        resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
        resp.raise_for_status()
        print("Slack message sent")
    except Exception as e:
        print(f"Slack delivery failed (non-blocking): {e}")


# ---------------------------------------------------------------------------
# [DELIVERY: PAGES]
# ---------------------------------------------------------------------------

def deliver_pages(articles: list[dict]):
    section("DELIVERY: PAGES")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slot_emojis = {1: "🧬", 2: "📊", 3: "🤖", 4: "🌀"}

    cards_html = ""
    for a in articles:
        slot = a.get("slot", 0)
        emoji = slot_emojis.get(slot, "📌")
        tags = ", ".join(a.get("signal_tags", []))
        cards_html += f"""
      <div class="card" data-slot="{slot}" data-date="{today}">
        <div class="card-header">
          <span class="slot-emoji">{emoji}</span>
          <span class="slot-label">Slot {slot}</span>
        </div>
        <h2><a href="{a.get('url', '#')}" target="_blank">{a.get('headline', 'Untitled')}</a></h2>
        <p class="meta">{a.get('source', '')} · {today}</p>
        <p class="summary">{a.get('summary', '')}</p>
        <p class="why">💡 {a.get('why_it_matters', '')}</p>
        <p class="tags">{tags}</p>
        <div class="feedback">
          <button class="fb-btn" onclick="rate(this, {slot}, 5)">👍</button>
          <button class="fb-btn" onclick="rate(this, {slot}, 1)">👎</button>
          <input type="text" class="fb-note" placeholder="Optional note..." id="note-{slot}">
          <button class="fb-submit" onclick="submitFeedback({slot})">Send</button>
        </div>
      </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Daily Reads — {today}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #0f0f23; color: #e0e0e0; padding: 24px;
      max-width: 800px; margin: 0 auto;
    }}
    h1 {{ color: #e94560; margin-bottom: 8px; font-size: 28px; }}
    .updated {{ color: #666; font-size: 13px; margin-bottom: 24px; }}
    .card {{
      background: #16213e; border-radius: 12px; padding: 20px;
      margin-bottom: 20px; border-left: 4px solid #e94560;
      transition: transform 0.2s;
    }}
    .card:hover {{ transform: translateY(-2px); }}
    .card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }}
    .slot-emoji {{ font-size: 24px; }}
    .slot-label {{ color: #a8a8b3; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }}
    .card h2 {{ font-size: 18px; margin-bottom: 8px; }}
    .card h2 a {{ color: #0fbcf9; text-decoration: none; }}
    .card h2 a:hover {{ text-decoration: underline; }}
    .meta {{ color: #a8a8b3; font-size: 13px; margin-bottom: 12px; }}
    .summary {{ line-height: 1.6; margin-bottom: 10px; }}
    .why {{ color: #e94560; font-style: italic; margin-bottom: 10px; }}
    .tags {{ color: #666; font-size: 12px; margin-bottom: 12px; }}
    .feedback {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .fb-btn {{
      background: #1a1a40; border: 1px solid #333; border-radius: 6px;
      padding: 6px 12px; cursor: pointer; font-size: 18px;
      transition: background 0.2s;
    }}
    .fb-btn:hover {{ background: #2a2a50; }}
    .fb-btn.selected {{ background: #e94560; border-color: #e94560; }}
    .fb-note {{
      background: #1a1a40; border: 1px solid #333; border-radius: 6px;
      padding: 6px 10px; color: #eee; flex: 1; min-width: 120px;
    }}
    .fb-submit {{
      background: #e94560; color: white; border: none; border-radius: 6px;
      padding: 6px 14px; cursor: pointer; font-size: 13px;
    }}
    .fb-submit:hover {{ background: #c7385a; }}
    .fb-status {{ color: #4caf50; font-size: 12px; margin-left: 8px; }}
    .empty {{ text-align: center; padding: 60px 20px; color: #666; }}
  </style>
</head>
<body>
  <h1>📰 Daily Reads</h1>
  <p class="updated">Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>

  <div id="cards">
{cards_html if cards_html else '    <div class="empty"><p>No articles selected today. Check back tomorrow!</p></div>'}
  </div>

  <script>
    const REPO = 'jroypeterson/daily-reads';
    const today = '{today}';
    let ratings = {{}};

    function rate(btn, slot, score) {{
      // Toggle selection
      const card = btn.closest('.card');
      card.querySelectorAll('.fb-btn').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      ratings[slot] = score;
    }}

    async function submitFeedback(slot) {{
      const note = document.getElementById('note-' + slot)?.value || '';
      const score = ratings[slot];
      if (!score) {{ alert('Click 👍 or 👎 first'); return; }}

      const entry = {{
        date: today,
        slot: slot,
        score: score,
        note: note,
        source: 'github_pages'
      }};

      // Try to update feedback_log.json via GitHub API
      const token = new URLSearchParams(window.location.search).get('token');
      if (!token) {{
        // Fallback: show the JSON for manual submission
        const card = document.querySelector(`[data-slot="${{slot}}"]`);
        let status = card.querySelector('.fb-status');
        if (!status) {{
          status = document.createElement('span');
          status.className = 'fb-status';
          card.querySelector('.feedback').appendChild(status);
        }}
        status.textContent = '✓ Feedback recorded locally';
        console.log('Feedback:', JSON.stringify(entry));

        // Store in localStorage as backup
        let stored = JSON.parse(localStorage.getItem('daily-reads-feedback') || '[]');
        stored.push(entry);
        localStorage.setItem('daily-reads-feedback', JSON.stringify(stored));
        return;
      }}

      try {{
        // Fetch current file
        const fileResp = await fetch(
          `https://api.github.com/repos/${{REPO}}/contents/feedback_log.json`,
          {{ headers: {{ 'Authorization': `token ${{token}}` }} }}
        );
        const fileData = await fileResp.json();
        const content = JSON.parse(atob(fileData.content));
        content.push(entry);

        // Update file
        await fetch(
          `https://api.github.com/repos/${{REPO}}/contents/feedback_log.json`,
          {{
            method: 'PUT',
            headers: {{
              'Authorization': `token ${{token}}`,
              'Content-Type': 'application/json'
            }},
            body: JSON.stringify({{
              message: `Feedback: slot ${{slot}} rated ${{score}}`,
              content: btoa(JSON.stringify(content, null, 2)),
              sha: fileData.sha
            }})
          }}
        );

        const card = document.querySelector(`[data-slot="${{slot}}"]`);
        let status = card.querySelector('.fb-status');
        if (!status) {{
          status = document.createElement('span');
          status.className = 'fb-status';
          card.querySelector('.feedback').appendChild(status);
        }}
        status.textContent = '✓ Saved!';
      }} catch (e) {{
        console.error('Feedback submit failed:', e);
        alert('Failed to save feedback. Check console.');
      }}
    }}
  </script>
</body>
</html>"""

    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Updated docs/index.html with {len(articles)} articles")


# ---------------------------------------------------------------------------
# [DELIVERY: LOG]
# ---------------------------------------------------------------------------

def deliver_log(articles: list[dict]):
    section("DELIVERY: LOG")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slot_emojis = {1: "🧬", 2: "📊", 3: "🤖", 4: "🌀"}

    print(f"Daily Reads — {today}")
    print("-" * 40)
    for a in articles:
        slot = a.get("slot", 0)
        emoji = slot_emojis.get(slot, "📌")
        print(f"\n{emoji} Slot {slot}: {a.get('headline', 'Untitled')}")
        print(f"   Source: {a.get('source', '')}")
        print(f"   URL: {a.get('url', '')}")
        print(f"   {a.get('summary', '')}")
        print(f"   💡 {a.get('why_it_matters', '')}")
        print(f"   Signals: {', '.join(a.get('signal_tags', []))}")


# ---------------------------------------------------------------------------
# [CRITERIA REWRITE]
# ---------------------------------------------------------------------------

def rewrite_criteria(feedback: list[dict]):
    """Use Claude to rewrite selection_criteria.md based on accumulated feedback."""
    section("CRITERIA REWRITE")
    print("Rewriting selection criteria based on 7+ days of feedback...")

    with open("selection_criteria.md", "r") as f:
        current = f.read()

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""You are refining article selection criteria for a daily newsletter digest.

Current criteria:
{current}

Accumulated feedback (each entry has date, slot, score 1-5, and optional note):
{json.dumps(feedback, indent=2)}

Analyze the feedback patterns:
- High scores (4-5): What patterns should be reinforced?
- Low scores (1-3): What patterns should be reduced?

Rewrite the selection criteria document with updated weights and preferences.
Keep the same markdown structure. Output ONLY the new document content."""
        }],
    )

    new_criteria = response.content[0].text
    with open("selection_criteria.md", "w") as f:
        f.write(new_criteria)
    print("selection_criteria.md updated with learned preferences")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  📰 DAILY READS AGENT")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # Step 1: Gmail scan
    gmail_items = gmail_scan()

    # Step 2: Tier 2 sources
    tier2_items = tier2_scan()

    # Step 3: Feedback check
    feedback_info = feedback_check()

    # Step 3b: Criteria rewrite if enough feedback
    if feedback_info["should_rewrite"]:
        all_feedback = load_json("feedback_log.json", [])
        rewrite_criteria(all_feedback)

    # Step 4: Article selection
    if not gmail_items and not tier2_items:
        print("\nNo items from any source. Exiting.")
        sys.exit(0)

    articles = select_articles(gmail_items, tier2_items, feedback_info)
    if not articles:
        print("\nNo articles selected. Exiting.")
        sys.exit(1)

    # Step 5: Deliver to all channels
    deliver_gmail(articles)
    deliver_slack(articles)
    deliver_pages(articles)
    deliver_log(articles)

    print(f"\n{'='*60}")
    print(f"  ✅ Daily Reads complete — {len(articles)} articles delivered")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
