"""
Game-by-game data scraper for NCAA tournament teams.

Scrapes from Sports-Reference game logs — full box score stats per game
including shooting splits, rebounds, turnovers, blocks, and opponent stats.

Uses the LeakyBucket rate limiter to stay well under rate limits.
Sports-Reference allows ~20 req/min; we default to 1 req/sec with burst 2.

Usage:
    python game_scraper.py                  # scrape all 64 teams
    python game_scraper.py --team Duke      # scrape one team
    python game_scraper.py --dry-run        # show URL mappings only
"""

import asyncio
import json
import logging
import math
import re
import statistics
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from rate_limiter import ScrapePipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
TEAMS_PATH = DATA_DIR / "teams.json"
GAMES_PATH = DATA_DIR / "games.json"

YEAR = 2025  # Sports-Reference uses the spring year of the season

# ── Sports-Reference school ID mapping ───────────────────
# Maps bracket team names -> Sports-Reference school slugs
# URL: sports-reference.com/cbb/schools/{slug}/{YEAR}-gamelogs.html
SREF_SLUGS = {
    # 1 seeds
    "Duke": "duke",
    "Arizona": "arizona",
    "Michigan": "michigan",
    "Florida": "florida",
    # 2 seeds
    "UConn": "connecticut",
    "Purdue": "purdue",
    "Iowa State": "iowa-state",
    "Houston": "houston",
    # 3 seeds
    "Michigan State": "michigan-state",
    "Gonzaga": "gonzaga",
    "Virginia": "virginia",
    "Illinois": "illinois",
    # 4 seeds
    "Kansas": "kansas",
    "Arkansas": "arkansas",
    "Alabama": "alabama",
    "Nebraska": "nebraska",
    # 5 seeds
    "St. John's": "st-johns-ny",
    "Wisconsin": "wisconsin",
    "Texas Tech": "texas-tech",
    "Vanderbilt": "vanderbilt",
    # 6 seeds
    "Louisville": "louisville",
    "BYU": "brigham-young",
    "Tennessee": "tennessee",
    "North Carolina": "north-carolina",
    # 7 seeds
    "UCLA": "ucla",
    "Miami FL": "miami-fl",
    "Kentucky": "kentucky",
    "Saint Mary's": "saint-marys-ca",
    # 8 seeds
    "Ohio State": "ohio-state",
    "Villanova": "villanova",
    "Georgia": "georgia",
    "Clemson": "clemson",
    # 9 seeds
    "TCU": "texas-christian",
    "Utah State": "utah-state",
    "Saint Louis": "saint-louis",
    "Iowa": "iowa",
    # 10 seeds
    "UCF": "central-florida",
    "Missouri": "missouri",
    "Santa Clara": "santa-clara",
    "Texas A&M": "texas-am",
    # 11 seeds
    "South Florida": "south-florida",
    "Texas": "texas",
    "SMU": "southern-methodist",
    "VCU": "virginia-commonwealth",
    # 12 seeds
    "Northern Iowa": "northern-iowa",
    "High Point": "high-point",
    "Akron": "akron",
    "McNeese St.": "mcneese-state",
    # 13 seeds
    "Cal Baptist": "california-baptist",
    "Hawaii": "hawaii",
    "Hofstra": "hofstra",
    "Troy": "troy",
    # 14 seeds
    "N. Dakota St.": "north-dakota-state",
    "Kennesaw St.": "kennesaw-state",
    "Wright State": "wright-state",
    "Penn": "pennsylvania",
    # 15 seeds
    "Furman": "furman",
    "Queens": "queens-nc",
    "Tennessee St.": "tennessee-state",
    "Idaho": "idaho",
    # 16 seeds
    "Siena": "siena",
    "Long Island": "long-island-university",
    "UMBC": "maryland-baltimore-county",
    "Lehigh": "lehigh",
}

# Columns we extract from Sports-Reference game log rows
GAME_FIELDS = {
    "date": str,
    "game_location": str,         # "" = home, "@" = away, "N" = neutral
    "opp_name_abbr": str,
    "game_type": str,             # REG, CTOURN, NCAA, etc.
    "team_game_result": str,      # W or L
    "team_game_score": int,
    "opp_team_game_score": int,
    # Team offense
    "fg": int, "fga": int, "fg_pct": float,
    "fg3": int, "fg3a": int, "fg3_pct": float,
    "fg2": int, "fg2a": int, "fg2_pct": float,
    "efg_pct": float,
    "ft": int, "fta": int, "ft_pct": float,
    "orb": int, "drb": int, "trb": int,
    "ast": int, "stl": int, "blk": int, "tov": int, "pf": int,
    # Opponent defense
    "opp_fg": int, "opp_fga": int, "opp_fg_pct": float,
    "opp_fg3": int, "opp_fg3a": int, "opp_fg3_pct": float,
    "opp_fg2": int, "opp_fg2a": int, "opp_fg2_pct": float,
    "opp_efg_pct": float,
    "opp_ft": int, "opp_fta": int, "opp_ft_pct": float,
    "opp_orb": int, "opp_drb": int, "opp_trb": int,
    "opp_ast": int, "opp_stl": int, "opp_blk": int, "opp_tov": int, "opp_pf": int,
}


# ── Parsing ──────────────────────────────────────────────

def parse_game_log(html: str, team_name: str) -> list[dict] | None:
    """
    Parse Sports-Reference team game log page.

    Returns list of game dicts with full box score stats.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "team_game_log"})

    if not table:
        logger.warning(f"[{team_name}] No game_log table found")
        return None

    games = []
    rows = table.find_all("tr")

    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        # Build cell map by data-stat attribute
        cell_map = {}
        for cell in cells:
            stat = cell.get("data-stat", "")
            if stat:
                cell_map[stat] = cell.get_text(strip=True)

        # Skip rows without a score (header rows, separators)
        if "team_game_score" not in cell_map or not cell_map["team_game_score"]:
            continue

        # Skip totals/summary rows (no date = season totals)
        if not cell_map.get("date"):
            continue

        game = {}
        for field, dtype in GAME_FIELDS.items():
            raw = cell_map.get(field, "")
            if not raw:
                game[field] = None
                continue
            try:
                if dtype == int:
                    game[field] = int(raw)
                elif dtype == float:
                    game[field] = float(raw.lstrip(".") if raw.startswith("..") else raw)
                else:
                    game[field] = raw
            except (ValueError, TypeError):
                game[field] = None

        # Computed fields
        ts = game.get("team_game_score")
        os = game.get("opp_team_game_score")
        if ts is not None and os is not None:
            game["margin"] = ts - os
            game["win"] = game.get("team_game_result", "").startswith("W")
            game["total_points"] = ts + os
        else:
            continue  # Skip games without scores

        games.append(game)

    if games:
        logger.debug(f"[{team_name}] Parsed {len(games)} games")
    else:
        logger.warning(f"[{team_name}] No games parsed from table")

    return games if games else None


def safe_mean(values):
    """Mean of non-None values, or None if empty."""
    clean = [v for v in values if v is not None]
    return round(statistics.mean(clean), 3) if clean else None


def safe_stdev(values):
    """Stdev of non-None values, or None if < 2 values."""
    clean = [v for v in values if v is not None]
    return round(statistics.stdev(clean), 1) if len(clean) >= 2 else None


def compute_derived_stats(games: list[dict]) -> dict:
    """
    Compute derived statistics from game-by-game results.

    Produces real Four Factors, shooting splits, consistency metrics,
    recent form, close-game record, and road/neutral performance.
    """
    if not games:
        return {}

    margins = [g["margin"] for g in games]
    n = len(games)

    stats = {}

    # ── Scoring & Margin ──
    stats["avg_margin"] = round(statistics.mean(margins), 1)
    stats["consistency"] = safe_stdev(margins) or 10.0
    stats["max_margin"] = max(margins)
    stats["worst_loss"] = min(margins)
    stats["scoring_variance"] = safe_stdev(
        [g["team_game_score"] for g in games]
    ) or 8.0

    # ── Four Factors (Offense) ──
    # eFG% = (FG + 0.5 * 3FG) / FGA — compute from totals for accuracy
    total_fg = sum(g.get("fg", 0) or 0 for g in games)
    total_fga = sum(g.get("fga", 0) or 0 for g in games)
    total_fg3 = sum(g.get("fg3", 0) or 0 for g in games)
    total_ft = sum(g.get("ft", 0) or 0 for g in games)
    total_fta = sum(g.get("fta", 0) or 0 for g in games)
    total_fg3a = sum(g.get("fg3a", 0) or 0 for g in games)
    total_fg2 = sum(g.get("fg2", 0) or 0 for g in games)
    total_fg2a = sum(g.get("fg2a", 0) or 0 for g in games)
    total_orb = sum(g.get("orb", 0) or 0 for g in games)
    total_drb = sum(g.get("drb", 0) or 0 for g in games)
    total_tov = sum(g.get("tov", 0) or 0 for g in games)
    total_blk = sum(g.get("blk", 0) or 0 for g in games)

    if total_fga > 0:
        stats["efg_pct"] = round((total_fg + 0.5 * total_fg3) / total_fga * 100, 1)
        stats["three_rate"] = round(total_fg3a / total_fga * 100, 1)
        stats["ft_rate"] = round(total_fta / total_fga * 100, 1)
    if total_fg3a > 0:
        stats["three_pct"] = round(total_fg3 / total_fg3a * 100, 1)
    if total_fg2a > 0:
        stats["two_pct"] = round(total_fg2 / total_fg2a * 100, 1)

    # Turnover rate: TOV / (FGA + 0.44 * FTA + TOV)
    possessions_approx = total_fga + 0.44 * total_fta + total_tov
    if possessions_approx > 0:
        stats["to_rate"] = round(total_tov / possessions_approx * 100, 1)

    # Offensive rebounding rate: ORB / (ORB + Opp DRB)
    total_opp_drb = sum(g.get("opp_drb", 0) or 0 for g in games)
    if total_orb + total_opp_drb > 0:
        stats["orb_rate"] = round(total_orb / (total_orb + total_opp_drb) * 100, 1)

    # Block rate
    if total_fga > 0:
        stats["blk_rate"] = round(total_blk / total_fga * 100, 1)

    # ── Four Factors (Defense) ──
    opp_fg = sum(g.get("opp_fg", 0) or 0 for g in games)
    opp_fga = sum(g.get("opp_fga", 0) or 0 for g in games)
    opp_fg3 = sum(g.get("opp_fg3", 0) or 0 for g in games)
    opp_fg2 = sum(g.get("opp_fg2", 0) or 0 for g in games)
    opp_fg2a = sum(g.get("opp_fg2a", 0) or 0 for g in games)
    opp_fta = sum(g.get("opp_fta", 0) or 0 for g in games)
    opp_tov = sum(g.get("opp_tov", 0) or 0 for g in games)
    opp_orb = sum(g.get("opp_orb", 0) or 0 for g in games)

    if opp_fga > 0:
        stats["efg_pct_d"] = round((opp_fg + 0.5 * opp_fg3) / opp_fga * 100, 1)
        stats["ft_rate_d"] = round(opp_fta / opp_fga * 100, 1)

    # Forced turnover rate
    opp_poss = opp_fga + 0.44 * opp_fta + opp_tov
    if opp_poss > 0:
        stats["to_rate_d"] = round(opp_tov / opp_poss * 100, 1)

    # Defensive rebounding rate: DRB / (DRB + Opp ORB)
    if total_drb + opp_orb > 0:
        stats["drb_rate"] = round(total_drb / (total_drb + opp_orb) * 100, 1)

    # ── Recent Form ──
    last_10 = games[-10:]
    last_10_margins = [g["margin"] for g in last_10]
    stats["recent_form"] = round(statistics.mean(last_10_margins), 1)
    stats["last_10"] = sum(1 for g in last_10 if g.get("win", False))

    # Last 10 eFG% (to see if shooting is trending)
    l10_fg = sum(g.get("fg", 0) or 0 for g in last_10)
    l10_fga = sum(g.get("fga", 0) or 0 for g in last_10)
    l10_fg3 = sum(g.get("fg3", 0) or 0 for g in last_10)
    if l10_fga > 0:
        stats["recent_efg"] = round((l10_fg + 0.5 * l10_fg3) / l10_fga * 100, 1)

    # ── Close Games ──
    close = [g for g in games if abs(g["margin"]) <= 6]
    close_wins = sum(1 for g in close if g.get("win", False))
    close_losses = len(close) - close_wins
    stats["close_game_record"] = [close_wins, close_losses]
    stats["close_game_pct"] = round(close_wins / len(close), 3) if close else 0.5

    # ── Road/Neutral Performance ──
    rn = [g for g in games if g.get("game_location") in ("@", "N")]
    rn_margins = [g["margin"] for g in rn]
    stats["road_neutral_margin"] = round(statistics.mean(rn_margins), 1) if rn_margins else stats["avg_margin"]

    # ── Streaks ──
    streak = 0
    for g in reversed(games):
        if g.get("win"):
            streak += 1
        else:
            break
    stats["win_streak"] = streak

    # ── SOS proxy (average opponent score allowed to us vs scored against us) ──
    opp_scores = [g.get("opp_team_game_score", 0) for g in games if g.get("opp_team_game_score")]
    stats["avg_opp_score"] = round(statistics.mean(opp_scores), 1) if opp_scores else 0

    return stats


def classify_style(team: dict) -> str:
    """
    Classify team play style from real stats.
    Uses a scoring system — highest score wins.
    """
    three_rate = team.get("three_rate", 35)
    three_pct = team.get("three_pct", 34)
    two_pct = team.get("two_pct", 50)
    orb_rate = team.get("orb_rate", 30)
    blk_rate = team.get("blk_rate", 10)
    tempo = team.get("tempo", 68)
    adj_d = team.get("adj_d", 96)
    adj_o = team.get("adj_o", 110)
    to_rate_d = team.get("to_rate_d", 18)

    off_contribution = adj_o - 110
    def_contribution = 96 - adj_d

    scores = {}

    scores["perimeter"] = (
        (three_rate - 35.0) * 0.3 +
        (three_pct - 34.0) * 0.2 +
        (-1.0 if two_pct > 54.0 else 0.0)
    )

    scores["interior"] = (
        (35.0 - three_rate) * 0.25 +
        (two_pct - 50.0) * 0.3 +
        (orb_rate - 29.0) * 0.15 +
        (blk_rate - 10.0) * 0.1
    )

    scores["transition"] = (
        (tempo - 67.0) * 0.5 +
        (to_rate_d - 17.0) * 0.15 +
        (-1.0 if tempo < 66.0 else 0.0)
    )

    scores["defense_first"] = (
        (96.0 - adj_d) * 0.3 +
        (def_contribution - off_contribution) * 0.2 +
        (1.0 if team.get("efg_pct_d", 50) < 48.0 else 0.0) +
        (blk_rate - 10.0) * 0.1 +
        (-2.0 if adj_d > 97.0 else 0.0)
    )

    scores["balanced"] = 1.0

    style = max(scores, key=scores.get)
    if style != "balanced" and scores[style] < scores["balanced"]:
        style = "balanced"

    return style


# ── Scraper worker ───────────────────────────────────────

async def scrape_team_games(task_id: str, task_data: dict) -> dict:
    """Worker: scrape game log from Sports-Reference."""
    team_name = task_data["name"]
    slug = SREF_SLUGS.get(team_name)
    if not slug:
        raise ValueError(f"No Sports-Reference slug for {team_name}")

    url = f"https://www.sports-reference.com/cbb/schools/{slug}/{YEAR}-gamelogs.html"

    async with httpx.AsyncClient(
        timeout=20.0,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
        },
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)

        # If rate limited, wait and retry once with a long cooldown
        if resp.status_code == 429:
            wait = 60  # Wait 60 seconds on 429
            logger.warning(f"[{team_name}] Rate limited (429), waiting {wait}s...")
            await asyncio.sleep(wait)
            resp = await client.get(url)

        resp.raise_for_status()

    games = parse_game_log(resp.text, team_name)
    derived = compute_derived_stats(games or [])

    return {
        "team": team_name,
        "url": url,
        "games": games,
        "derived": derived,
        "game_count": len(games) if games else 0,
    }


# ── Main pipeline ────────────────────────────────────────

def load_cached_games() -> dict:
    """Load previously scraped game data if it exists."""
    if GAMES_PATH.exists():
        try:
            return json.loads(GAMES_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_games_incremental(games_cache: dict):
    """Write current game cache to disk."""
    GAMES_PATH.write_text(json.dumps(games_cache, indent=2))


async def scrape_all_teams(
    teams: list[dict],
    concurrency: int = 1,
    rate: float = 1.0,
    force: bool = False,
) -> dict:
    """
    Scrape game logs for all teams sequentially with incremental saves.

    Saves to games.json after EVERY successful team scrape so progress
    is never lost. Skips teams already cached (unless force=True).

    Args:
        teams: List of team dicts
        concurrency: Ignored (always sequential for incremental saves)
        rate: Requests per second
        force: If True, re-scrape even if cached data exists
    """
    games_cache = {} if force else load_cached_games()
    all_data = {}

    teams_to_scrape = []
    for t in teams:
        name = t["name"]
        if name not in SREF_SLUGS:
            logger.warning(f"No Sports-Reference slug for {name}, skipping")
            continue
        if not force and name in games_cache and len(games_cache[name]) > 10:
            logger.info(f"  Cache hit: {name} ({len(games_cache[name])} games)")
            derived = compute_derived_stats(games_cache[name])
            all_data[name] = {
                "team": name,
                "games": games_cache[name],
                "derived": derived,
                "game_count": len(games_cache[name]),
                "from_cache": True,
            }
        else:
            teams_to_scrape.append(t)

    cached_count = len(all_data)
    if cached_count:
        logger.info(f"Using cached data for {cached_count} teams")

    if not teams_to_scrape:
        logger.info("All teams cached, nothing to scrape")
        return all_data

    total = len(teams_to_scrape)
    delay = 1.0 / rate
    logger.info(
        f"Scraping {total} teams @ 1 req per {delay:.0f}s "
        f"(~{total * delay / 60:.1f} minutes)"
    )

    succeeded = 0
    failed = 0

    for i, t in enumerate(teams_to_scrape):
        name = t["name"]

        # Rate limit: wait between requests (skip wait on first)
        if i > 0:
            await asyncio.sleep(delay)

        try:
            result = await scrape_team_games(name, t)
            games = result.get("games")

            if games and len(games) > 0:
                # Save to cache immediately
                games_cache[name] = games
                _save_games_incremental(games_cache)

                all_data[name] = result
                succeeded += 1
                logger.info(
                    f"  [{i + 1:>2}/{total}] {name} — "
                    f"{len(games)} games — SAVED"
                )
            else:
                failed += 1
                logger.warning(f"  [{i + 1:>2}/{total}] {name} — no games parsed")

        except Exception as e:
            failed += 1
            logger.error(f"  [{i + 1:>2}/{total}] {name} — FAILED: {e}")

            # On 429, wait extra long before next request
            if "429" in str(e):
                logger.warning(f"  Rate limited! Waiting 120s before continuing...")
                await asyncio.sleep(120)

    logger.info(
        f"Done: {succeeded}/{total} succeeded, {failed} failed, "
        f"{cached_count} from cache"
    )
    return all_data


def merge_scraped_into_teams(teams: list[dict], scraped: dict) -> list[dict]:
    """
    Merge scraped game data into teams.json.
    Replaces generated fields with real computed stats.
    Reclassifies play style from real data.
    """
    for team in teams:
        name = team["name"]
        data = scraped.get(name, {})
        derived = data.get("derived", {})

        if not derived:
            continue

        # Replace stats with real computed values
        for key in [
            # Four Factors offense
            "efg_pct", "to_rate", "orb_rate", "ft_rate",
            # Four Factors defense
            "efg_pct_d", "to_rate_d", "drb_rate", "ft_rate_d",
            # Shooting
            "three_rate", "three_pct", "two_pct", "blk_rate",
            # Consistency & form
            "consistency", "recent_form", "last_10",
            "close_game_record", "close_game_pct",
            "road_neutral_margin", "win_streak",
            "avg_margin", "max_margin", "worst_loss",
            "scoring_variance", "recent_efg", "avg_opp_score",
        ]:
            if key in derived:
                team[key] = derived[key]

        team["games_scraped"] = data.get("game_count", 0)
        team["data_source"] = "sports-reference"

        # Reclassify style with real data
        team["style"] = classify_style(team)

    return teams


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Scrape game data for bracket teams")
    parser.add_argument("--team", help="Scrape a single team by name")
    parser.add_argument("--rate", type=float, default=1.0,
                        help="Requests per second (default: 1.0)")
    parser.add_argument("--concurrency", type=int, default=2,
                        help="Max concurrent requests (default: 2)")
    parser.add_argument("--force", action="store_true",
                        help="Re-scrape even if cached data exists")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show URL mappings without scraping")
    args = parser.parse_args()

    # Load teams
    teams = json.loads(TEAMS_PATH.read_text())
    logger.info(f"Loaded {len(teams)} teams")

    if args.team:
        teams = [t for t in teams if t["name"] == args.team]
        if not teams:
            logger.error(f"Team not found: {args.team}")
            sys.exit(1)

    if args.dry_run:
        print(f"\n{'Team':<22} {'Slug':<30} {'URL'}")
        print("-" * 110)
        for t in teams:
            slug = SREF_SLUGS.get(t["name"], "MISSING")
            url = f"sports-reference.com/cbb/schools/{slug}/{YEAR}-gamelogs.html"
            status = "" if slug != "MISSING" else " *** NO MAPPING ***"
            print(f"{t['name']:<22} {slug:<30} {url}{status}")
        return

    # Run scraping pipeline
    scraped = await scrape_all_teams(
        teams, concurrency=args.concurrency, rate=args.rate, force=args.force
    )

    # Save raw game data
    games_output = {}
    for team_name, data in scraped.items():
        games_output[team_name] = data.get("games") or []
    GAMES_PATH.write_text(json.dumps(games_output, indent=2))
    logger.info(f"Saved game data to {GAMES_PATH}")

    # Merge into teams.json
    all_teams = json.loads(TEAMS_PATH.read_text())
    updated = merge_scraped_into_teams(all_teams, scraped)
    TEAMS_PATH.write_text(json.dumps(updated, indent=2))
    logger.info(f"Updated {TEAMS_PATH}")

    # Summary
    total_games = sum(len(g) for g in games_output.values())
    teams_with_games = sum(1 for g in games_output.values() if g)
    print(f"\n{'='*60}")
    print(f"  SCRAPE COMPLETE")
    print(f"  Teams with data: {teams_with_games}/{len(teams)}")
    print(f"  Total games scraped: {total_games}")
    print(f"  Avg games/team: {total_games / max(teams_with_games, 1):.0f}")
    print(f"{'='*60}\n")

    # Show samples
    for t in (teams[:3] if len(teams) > 3 else teams):
        data = scraped.get(t["name"], {})
        derived = data.get("derived", {})
        if not derived:
            print(f"  {t['name']}: NO DATA")
            continue
        print(f"  {t['name']} ({data.get('game_count', 0)} games):")
        print(f"    eFG%: {derived.get('efg_pct')}  |  Opp eFG%: {derived.get('efg_pct_d')}")
        print(f"    3P%: {derived.get('three_pct')}  |  3PA rate: {derived.get('three_rate')}")
        print(f"    TO rate: {derived.get('to_rate')}  |  Forced TO: {derived.get('to_rate_d')}")
        print(f"    ORB%: {derived.get('orb_rate')}  |  DRB%: {derived.get('drb_rate')}")
        print(f"    Consistency (stddev): {derived.get('consistency')}")
        print(f"    Recent form (L10 margin): {derived.get('recent_form')}")
        print(f"    Close games: {derived.get('close_game_record')}")
        print(f"    Road/neutral margin: {derived.get('road_neutral_margin')}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
