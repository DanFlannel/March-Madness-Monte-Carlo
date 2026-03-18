from pydantic import BaseModel
from typing import Optional


class Team(BaseModel):
    name: str
    seed: int
    region: str
    adj_o: float  # Adjusted offensive efficiency (points per 100 possessions)
    adj_d: float  # Adjusted defensive efficiency
    adj_em: float  # Adjusted efficiency margin (adj_o - adj_d)
    tempo: float  # Possessions per game
    record: str
    kenpom_rank: int
    conference: str = ""


class Adjustment(BaseModel):
    team: str
    factor: float  # Multiplier on efficiency margin (e.g. 0.92 = 8% nerf)
    note: str
    adj_type: str  # "injury", "form", "momentum", "matchup"


class AdjustmentsUpdate(BaseModel):
    adjustments: dict[str, Adjustment]


class SimulationRequest(BaseModel):
    n: int = 10000  # Number of simulations
    locked_picks: dict[str, str] = {}  # {"R64-East-0": "Duke", "R32-East-0": "Duke", ...}
    scaling_factor: float = 11.0  # Logistic scaling (higher = more upsets)


class MatchupResult(BaseModel):
    team_a: str
    team_b: str
    win_prob_a: float
    win_prob_b: float
    predicted_score_a: int
    predicted_score_b: int
    seed_a: int
    seed_b: int


class TeamSimResult(BaseModel):
    team: str
    seed: int
    region: str
    r64: float  # % chance to win R64
    r32: float
    s16: float
    e8: float
    f4: float
    finals: float
    champion: float


class SimulationResponse(BaseModel):
    n_sims: int
    results: list[TeamSimResult]
    matchups: dict  # Round-by-round matchup probabilities
