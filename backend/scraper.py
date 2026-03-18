"""
Scraper for Bart Torvik (barttorvik.com) team ratings.
Falls back to cached JSON data if scraping fails.
"""

import json
import logging
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
TEAMS_CACHE = DATA_DIR / "teams.json"
TORVIK_URL = "https://barttorvik.com/trank.php"

# Mapping from Torvik names to our bracket names (handle discrepancies)
NAME_MAP = {
    "Connecticut": "UConn",
    "St. John's": "St. John's",
    "North Carolina St.": "NC State",
    "N.C. State": "NC State",
    "Miami FL": "Miami FL",
    "Miami OH": "Miami OH",
    "Central Florida": "UCF",
    "North Dakota St.": "N. Dakota St.",
    "Tennessee St.": "Tennessee St.",
    "McNeese": "McNeese St.",
    "McNeese St.": "McNeese St.",
    "Kennesaw St.": "Kennesaw St.",
    "Cal Baptist": "Cal Baptist",
    "LIU": "Long Island",
    "Long Island University": "Long Island",
    "Saint Mary's (CA)": "Saint Mary's",
    "Saint Mary's": "Saint Mary's",
    "Prairie View A&M": "PV A&M",
    "Prairie View": "PV A&M",
    "UMBC": "UMBC",
    "Northern Iowa": "Northern Iowa",
    "South Florida": "South Florida",
    "Wright State": "Wright State",
    "High Point": "High Point",
    "Kennesaw State": "Kennesaw St.",
    "North Dakota State": "N. Dakota St.",
    "Tennessee State": "Tennessee St.",
}


def normalize_name(name: str) -> str:
    """Normalize a team name to match our bracket naming convention."""
    name = name.strip()
    return NAME_MAP.get(name, name)


async def scrape_torvik() -> list[dict] | None:
    """
    Scrape current season team ratings from Bart Torvik.
    Returns list of team dicts or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {"year": 2026, "sort": 1, "conlimit": "All"}
            resp = await client.get(TORVIK_URL, params=params)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"id": "trank-table"})
        if not table:
            # Try finding any data table
            table = soup.find("table")
        if not table:
            logger.warning("Could not find ratings table on Torvik")
            return None

        teams = []
        rows = table.find_all("tr")[1:]  # skip header
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 8:
                continue
            try:
                name = normalize_name(cells[1].get_text(strip=True))
                conf = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                record = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                adj_o = float(cells[4].get_text(strip=True))
                adj_d = float(cells[5].get_text(strip=True))
                tempo = float(cells[7].get_text(strip=True)) if len(cells) > 7 else 68.0

                teams.append({
                    "name": name,
                    "adj_o": adj_o,
                    "adj_d": adj_d,
                    "adj_em": round(adj_o - adj_d, 1),
                    "tempo": tempo,
                    "record": record,
                    "conference": conf,
                })
            except (ValueError, IndexError) as e:
                continue

        if len(teams) > 50:
            logger.info(f"Scraped {len(teams)} teams from Torvik")
            return teams

        logger.warning(f"Only scraped {len(teams)} teams, falling back to cache")
        return None

    except Exception as e:
        logger.warning(f"Torvik scrape failed: {e}")
        return None


def load_cached_teams() -> list[dict]:
    """Load team data from cached JSON file."""
    with open(TEAMS_CACHE) as f:
        return json.load(f)


def save_teams_cache(teams: list[dict]):
    """Save scraped team data to cache."""
    with open(TEAMS_CACHE, "w") as f:
        json.dump(teams, f, indent=2)


async def get_teams(force_refresh: bool = False) -> list[dict]:
    """
    Get team data, attempting scrape first, falling back to cache.
    """
    if force_refresh:
        scraped = await scrape_torvik()
        if scraped:
            save_teams_cache(scraped)
            return scraped

    # Try scraping
    scraped = await scrape_torvik()
    if scraped:
        save_teams_cache(scraped)
        return scraped

    # Fall back to cache
    logger.info("Using cached team data")
    return load_cached_teams()
