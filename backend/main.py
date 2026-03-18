"""
Bracket Simulator API — FastAPI server.

Run: uvicorn main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scraper import get_teams, load_cached_teams
from simulator import simulate, win_probability, enhanced_win_probability, predict_score, apply_adjustments

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"

app = FastAPI(
    title="Bracket Simulator",
    description="538-style NCAA Tournament Monte Carlo simulator",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── State ──────────────────────────────────────────────

_teams: dict[str, dict] = {}
_bracket: dict = {}
_adjustments: dict = {}


def _load_bracket():
    with open(DATA_DIR / "bracket.json") as f:
        return json.load(f)


def _load_adjustments():
    adj_path = DATA_DIR / "adjustments.json"
    if adj_path.exists():
        with open(adj_path) as f:
            return json.load(f)
    return {}


def _save_adjustments(adj: dict):
    with open(DATA_DIR / "adjustments.json", "w") as f:
        json.dump(adj, f, indent=2)


@app.on_event("startup")
async def startup():
    global _teams, _bracket, _adjustments
    # Load bracket structure
    _bracket = _load_bracket()
    # Load adjustments
    _adjustments = _load_adjustments()
    # Load team data (try scraping, fall back to cache)
    raw_teams = load_cached_teams()
    _teams = {t["name"]: t for t in raw_teams}
    logger.info(f"Loaded {len(_teams)} teams, {len(_adjustments)} adjustments")


# ── Endpoints ──────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": "Bracket Simulator API",
        "version": "1.0.0",
        "teams_loaded": len(_teams),
        "adjustments_active": len(_adjustments),
        "endpoints": ["/docs", "/teams", "/bracket", "/simulate", "/matchup", "/adjustments"],
    }


@app.get("/teams")
async def get_all_teams():
    """Get all teams with current ratings and any active adjustments."""
    adjusted = apply_adjustments(_teams, _adjustments)
    result = []
    for name, team in adjusted.items():
        t = {**team, "name": name}
        if name in _adjustments:
            t["adjustment"] = _adjustments[name]
        result.append(t)
    result.sort(key=lambda x: x.get("kenpom_rank", 999))
    return {"teams": result, "count": len(result)}


@app.get("/teams/refresh")
async def refresh_teams():
    """Re-scrape team data from Bart Torvik."""
    global _teams
    raw_teams = await get_teams(force_refresh=True)
    _teams = {t["name"]: t for t in raw_teams}
    return {"message": f"Refreshed {len(_teams)} teams", "source": "torvik" if len(raw_teams) > 60 else "cache"}


@app.get("/bracket")
async def get_bracket():
    """Get bracket structure with R64 pairings."""
    return {"bracket": _bracket, "regions": list(_bracket.keys())}


class SimRequest(BaseModel):
    n: int = 10000
    locked_picks: dict[str, str] = {}
    scaling_factor: float = 11.0


@app.post("/simulate")
async def run_simulation(req: SimRequest):
    """
    Run Monte Carlo simulation.

    Body:
        n: Number of simulations (default 10000)
        locked_picks: Dict of locked picks, e.g. {"R64-East-0": "Duke", "R32-East-0": "Duke"}
        scaling_factor: Logistic scaling (10=chalky, 11=normal, 12.5=chaos)

    Lock key format: {ROUND}-{REGION}-{INDEX}
        ROUND: R64, R32, S16, E8, F4, FINAL
        REGION: East, West, Midwest, South (or compound for F4)
        INDEX: 0-based matchup index within the round
    """
    if req.n < 100:
        raise HTTPException(400, "Minimum 100 simulations")
    if req.n > 100000:
        raise HTTPException(400, "Maximum 100,000 simulations")

    result = simulate(
        bracket=_bracket,
        teams=_teams,
        n=req.n,
        scaling=req.scaling_factor,
        locked_picks=req.locked_picks,
        adjustments=_adjustments,
    )
    return result


@app.get("/matchup/{team_a}/{team_b}")
async def head_to_head(team_a: str, team_b: str, round_name: str = "r64", scaling: float = 11.0):
    """Get head-to-head win probability and predicted score."""
    if team_a not in _teams:
        raise HTTPException(404, f"Team not found: {team_a}")
    if team_b not in _teams:
        raise HTTPException(404, f"Team not found: {team_b}")

    adjusted = apply_adjustments(_teams, _adjustments)
    a = adjusted[team_a]
    b = adjusted[team_b]

    prob = enhanced_win_probability(a, b, scaling, round_name)
    score_a, score_b = predict_score(a, b)

    return {
        "team_a": team_a,
        "team_b": team_b,
        "win_prob_a": round(prob * 100, 1),
        "win_prob_b": round((1 - prob) * 100, 1),
        "predicted_score_a": score_a,
        "predicted_score_b": score_b,
        "adj_em_a": round(a["adj_em"], 1),
        "adj_em_b": round(b["adj_em"], 1),
        "seed_a": a.get("seed", 0),
        "seed_b": b.get("seed", 0),
        "style_a": a.get("style", "balanced"),
        "style_b": b.get("style", "balanced"),
    }


@app.get("/adjustments")
async def get_adjustments():
    """Get current injury/form adjustments."""
    return {"adjustments": _adjustments}


class AdjUpdate(BaseModel):
    factor: float = 1.0
    note: str = ""
    adj_type: str = "injury"


@app.put("/adjustments/{team}")
async def update_adjustment(team: str, adj: AdjUpdate):
    """Add or update an adjustment for a team."""
    if team not in _teams:
        raise HTTPException(404, f"Team not found: {team}")
    _adjustments[team] = {
        "team": team,
        "factor": adj.factor,
        "note": adj.note,
        "adj_type": adj.adj_type,
    }
    _save_adjustments(_adjustments)
    return {"message": f"Updated adjustment for {team}", "adjustment": _adjustments[team]}


@app.delete("/adjustments/{team}")
async def remove_adjustment(team: str):
    """Remove adjustment for a team."""
    if team in _adjustments:
        del _adjustments[team]
        _save_adjustments(_adjustments)
        return {"message": f"Removed adjustment for {team}"}
    raise HTTPException(404, f"No adjustment found for {team}")


@app.get("/teams/games/{team_name}")
async def get_team_games(team_name: str):
    """Get game-by-game results and margins for a team, with opponent seeds."""
    if team_name not in _teams:
        raise HTTPException(404, f"Team not found: {team_name}")
    games_path = DATA_DIR / "games.json"
    if not games_path.exists():
        raise HTTPException(404, "Games data not available")
    with open(games_path) as f:
        all_games = json.load(f)
    team_games = all_games.get(team_name, [])

    # Enrich with opponent seed/region if they're in the bracket
    enriched = []
    for g in team_games:
        ge = {**g}
        opp = g.get("opp_name_abbr", "")
        if opp in _teams:
            ge["opp_seed"] = _teams[opp].get("seed")
            ge["opp_region"] = _teams[opp].get("region")
            ge["opp_kenpom"] = _teams[opp].get("kenpom_rank")
            ge["opp_in_bracket"] = True
        else:
            ge["opp_in_bracket"] = False
        enriched.append(ge)

    margins = [g.get("margin", 0) for g in team_games]
    losses = [g for g in enriched if not g.get("win", True)]
    last_10 = enriched[-10:]

    return {
        "team": team_name,
        "games": enriched,
        "margins": margins,
        "losses": losses,
        "last_10": last_10,
        "game_count": len(team_games),
    }


@app.get("/health")
async def health():
    return {"status": "ok", "teams": len(_teams), "adjustments": len(_adjustments)}
