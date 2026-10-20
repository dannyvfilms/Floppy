#!/usr/bin/env python3
"""Refresh the README Sponsors goal SVG from GitHub's public GraphQL data."""

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/brand/sponsors-goal.svg"
QUERY = """
query {
  user(login: "dannyvfilms") {
    sponsorsListing {
      activeGoal {
        kind
        targetValue
        percentComplete
      }
    }
  }
}
"""


def fetch_goal() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit(
            "GITHUB_TOKEN is required. In Actions, add the SPONSORS_GOAL_TOKEN (or SPONSORS_TOKEN) repository "
            "secret: a personal access token from dannyvfilms (the built-in token cannot "
            "read GitHub Sponsors data)."
        )
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Floppy-sponsors-goal-updater",
        },
    )
    with urlopen(request, timeout=20) as response:
        result = json.load(response)
    if result.get("errors"):
        raise SystemExit(f"GitHub GraphQL error: {result['errors']}")
    goal = (result.get("data", {}).get("user", {}).get("sponsorsListing") or {}).get("activeGoal")
    if not goal or goal.get("kind") != "MONTHLY_SPONSORSHIP_AMOUNT":
        raise SystemExit("No active monthly amount goal was returned for dannyvfilms")
    return goal


def render(goal: dict) -> str:
    target = int(goal["targetValue"])
    percent = max(0, min(100, int(goal["percentComplete"])))
    goal_label = f"{percent}% of ${target:,} per month"
    # The SVG dimensions match its half-width column in the README table.
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="500" height="340" viewBox="0 0 500 340" role="img" aria-labelledby="title desc">
  <title id="title">Help Floppy reach its GitHub Sponsors goal</title>
  <desc id="desc">{goal_label}. Sponsorships help cover the AI development tools used to build Floppy.</desc>
  <rect x="1" y="1" width="498" height="338" rx="14" fill="#0d1117" stroke="#30363d" stroke-width="2"/>
  <text x="25" y="48" fill="#f0f6fc" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="23" font-weight="700">Help Floppy grow</text>
  <text x="25" y="92" fill="#f0f6fc" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="17" font-weight="600">{goal_label}</text>
  <rect x="25" y="108" width="450" height="12" rx="6" fill="#3d444d"/>
  <rect x="25" y="108" width="{450 * percent / 100:.1f}" height="12" rx="6" fill="#db61a2"/>
  <rect x="20" y="144" width="460" height="160" rx="10" fill="#161b22"/>
  <text x="40" y="184" fill="#f0f6fc" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="17" font-weight="700">Build more of what the</text>
  <text x="40" y="208" fill="#f0f6fc" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="17" font-weight="700">community needs.</text>
  <text x="40" y="244" fill="#c9d1d9" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="14">Sponsorships help cover the AI tools</text>
  <text x="40" y="266" fill="#c9d1d9" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="14">I use to develop Floppy and respond</text>
  <text x="40" y="288" fill="#c9d1d9" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="14">to issues and community needs.</text>
</svg>
'''


if __name__ == "__main__":
    OUTPUT.write_text(render(fetch_goal()), encoding="utf-8")
