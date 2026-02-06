"""
TrippixnBot - GitHub Service
============================

Fetch GitHub contribution stats using GraphQL API.

Author: حَـــــنَّـــــا
"""

from datetime import datetime
from typing import Optional

from src.core import log
from src.api.config import get_api_config
from src.utils.http import http_session, DEFAULT_TIMEOUT


async def fetch_github_commits() -> Optional[dict]:
    """
    Fetch GitHub contribution stats using GraphQL API.

    Returns:
        Dict with total commits, year_start, fetched_at, and calendar data.
        None if fetch fails.
    """
    config = get_api_config()
    username = config.github_username
    token = config.github_token

    if not username:
        log.warning("GitHub Fetch Skipped", [("Reason", "GITHUB_USERNAME not set")])
        return None

    if not token:
        log.warning("GitHub Fetch Skipped", [("Reason", "GITHUB_TOKEN not set")])
        return None

    query = """
    query($username: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $username) {
            contributionsCollection(from: $from, to: $to) {
                totalCommitContributions
                restrictedContributionsCount
                contributionCalendar {
                    totalContributions
                    weeks {
                        contributionDays {
                            date
                            contributionCount
                            contributionLevel
                        }
                    }
                }
            }
        }
    }
    """

    now = datetime.now()
    year_start = datetime(now.year, 1, 1)

    variables = {
        "username": username,
        "from": year_start.isoformat() + "Z",
        "to": now.isoformat() + "Z",
    }

    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        async with http_session.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        ) as resp:
            if resp.status != 200:
                log.warning("GitHub API Error", [("Status", str(resp.status))])
                return None

            data = await resp.json()

            if "errors" in data:
                log.warning("GitHub GraphQL Error", [("Error", str(data["errors"])[:50])])
                return None

            user_data = data.get("data", {}).get("user", {})
            contributions = user_data.get("contributionsCollection", {})

            # Total = public + private
            public_commits = contributions.get("totalCommitContributions", 0)
            private_commits = contributions.get("restrictedContributionsCount", 0)
            total_commits = public_commits + private_commits

            # Extract calendar
            calendar = contributions.get("contributionCalendar", {})
            weeks = calendar.get("weeks", [])

            contribution_days = []
            for week in weeks:
                for day in week.get("contributionDays", []):
                    contribution_days.append({
                        "date": day.get("date"),
                        "count": day.get("contributionCount", 0),
                        "level": day.get("contributionLevel", "NONE"),
                    })

            return {
                "total": total_commits,
                "year_start": year_start.strftime("%Y-%m-%d"),
                "fetched_at": now.isoformat(),
                "calendar": contribution_days,
            }

    except Exception as e:
        log.warning("GitHub Fetch Failed", [("Error", str(e)[:50])])
        return None


__all__ = ["fetch_github_commits"]
