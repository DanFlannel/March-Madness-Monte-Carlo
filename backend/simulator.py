"""
Monte Carlo bracket simulation engine — 538-style model.

Uses adjusted efficiency margins with a logistic win probability model,
enhanced with real game-by-game data from Sports-Reference.

Model factors (ordered by impact):
  1. Recency-weighted EM     — 60% season EM + 30% last-10 form + 10% road/neutral
  2. Four Factors matchup    — eFG%, TO rate, ORB%, FT rate interactions
  3. Style matchup           — archetype advantages (perimeter vs interior, etc.)
  4. Tempo-adjusted variance — more possessions = more variance = more upsets
  5. Consistency/volatility  — high-variance underdogs are dangerous
  6. Clutch factor           — close-game record as tournament pressure proxy
  7. Momentum                — win streaks and recent shooting trends
  8. Seed history prior      — Bayesian blend with historical upset rates (R64 only)
"""

import json
import math
import random
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).parent / "data"

ROUND_NAMES = ["r64", "r32", "s16", "e8", "f4", "finals", "champion"]

# Final Four pairing: South vs East, West vs Midwest
FF_PAIRS = [("South", "East"), ("West", "Midwest")]


# ---------------------------------------------------------------------------
# Style matchup matrix
# ---------------------------------------------------------------------------
STYLE_MATCHUP_MATRIX = {
    # Empirically derived from 547 games between bracket teams.
    # (attacker_style, defender_style): EM adjustment for attacker.
    # Scaled from raw margin-vs-expected (×0.15) and capped at ±1.5.
    #
    # Key finding: perimeter teams are the style kings — they beat
    # everyone except transition. Defense-first teams underperform
    # their EM against perimeter and balanced styles.
    ("perimeter", "interior"): 1.3,        # Perimeter dominates interior (n=16, +8.7 raw)
    ("perimeter", "defense_first"): 0.8,   # Shooters beat elite D (n=32, +5.6 raw)
    ("perimeter", "balanced"): 0.3,        # Slight edge (n=44, +1.8 raw)
    ("perimeter", "transition"): -0.7,     # Transition disrupts shooters (n=37, -4.3 raw)
    ("transition", "perimeter"): 0.6,      # Pace kills perimeter D (n=39, +3.8 raw)
    ("transition", "balanced"): 0.7,       # Tempo advantage (n=16, +4.4 raw)
    ("balanced", "defense_first"): 0.6,    # Balanced attacks exploit rigidity (n=24, +4.0 raw)
    ("balanced", "perimeter"): -0.3,       # Perimeter has edge (n=48, -2.2 raw)
    ("balanced", "transition"): -0.6,      # Transition is tough (n=16, -4.2 raw)
    ("defense_first", "balanced"): -0.8,   # D-first underperforms vs balanced (n=23, -5.5 raw)
    ("defense_first", "perimeter"): -0.7,  # D-first struggles vs shooters (n=35, -4.8 raw)
    ("interior", "perimeter"): -0.6,       # Interior loses to perimeter (n=19, -4.1 raw)
}


# ---------------------------------------------------------------------------
# Factor 1: Recency-weighted efficiency margin
# ---------------------------------------------------------------------------

def recency_weighted_em(team: dict) -> float:
    """
    Blend season EM with recent performance and neutral-site margins.

    538's key insight: teams peak and fade. A team's last 10 games
    are more predictive of tournament performance than their November results.
    Tournament games are neutral site — road/neutral margin is more relevant
    than overall margin which includes home games.

    Weights:
        70% season adj_em (overall quality floor — KenPom is already excellent)
        20% recent_form (last 10 games avg margin — captures peaking/fading)
        10% road_neutral_margin (tournament-relevant, strips home advantage)

    Recent form and road/neutral are blended conservatively because small
    sample sizes (10 games, ~15 road games) are noisy. Season EM from
    KenPom already regression-adjusts for opponent quality.
    """
    base_em = team.get('adj_em', 0)
    recent = team.get('recent_form', base_em)
    road_neutral = team.get('road_neutral_margin', base_em * 0.6)

    return base_em * 0.7 + recent * 0.2 + road_neutral * 0.1


# ---------------------------------------------------------------------------
# Factor 2: Four Factors matchup edge
# ---------------------------------------------------------------------------

def four_factors_edge(team_a: dict, team_b: dict) -> float:
    """
    Matchup-specific EM adjustment from Dean Oliver's Four Factors.

    How team A's offensive profile attacks team B's defensive profile.
    Uses real scraped data — eFG%, TO rate, ORB%, FT rate.

    Weights reflect research on factor importance.
    Total edge is capped at ±2.0 EM points — Four Factors are a modifier
    on top of EM, not a replacement. Raw EM already captures most of this.
    """
    # Shooting: A's eFG% vs B's eFG% defense — centered around D1 averages
    efg_edge = (team_a.get('efg_pct', 50) - 50) - (team_b.get('efg_pct_d', 50) - 50)
    edge = efg_edge * 0.15

    # Turnovers: A's ball security vs B's ability to force turnovers
    # Lower TO rate = better for A. Higher TO_rate_d = B forces more.
    a_to = team_a.get('to_rate', 17)
    b_forced_to = team_b.get('to_rate_d', 17)
    to_edge = (17 - a_to) - (b_forced_to - 17)
    edge += to_edge * 0.10

    # Rebounding: A's offensive boards vs B's defensive boards
    a_orb = team_a.get('orb_rate', 28)
    b_drb = team_b.get('drb_rate', 72)
    orb_edge = (a_orb - 28) - (b_drb - 72)
    edge += orb_edge * 0.08

    # Free throws: A's ability to get to the line vs B's foul discipline
    a_ft_rate = team_a.get('ft_rate', 33)
    b_ft_rate_d = team_b.get('ft_rate_d', 33)
    ft_edge = (a_ft_rate - 33) - (b_ft_rate_d - 33)
    edge += ft_edge * 0.05

    # Cap total edge to prevent blowout probabilities from matchup factors alone
    return max(-2.0, min(2.0, edge))


# ---------------------------------------------------------------------------
# Factor 3: Style matchup
# ---------------------------------------------------------------------------

def style_matchup_adjustment(style_a: str, style_b: str) -> float:
    """Get EM adjustment for team A based on style matchup."""
    return STYLE_MATCHUP_MATRIX.get((style_a, style_b), 0.0)


# ---------------------------------------------------------------------------
# Factor 4: Tempo-adjusted variance
# ---------------------------------------------------------------------------

def tempo_adjusted_scaling(tempo_a: float, tempo_b: float, base_scaling: float) -> float:
    """
    More possessions = more variance = more upset potential.

    When two teams with very different tempos meet, the game becomes
    less predictable — the slower team controls pace (benefits underdog).
    """
    avg_tempo = (tempo_a + tempo_b) / 2
    tempo_diff = abs(tempo_a - tempo_b)
    # Baseline D1 tempo ~68
    tempo_factor = 1.0 + (avg_tempo - 68) * 0.005 + tempo_diff * 0.008
    return base_scaling * tempo_factor


# ---------------------------------------------------------------------------
# Factor 5: Consistency / volatility
# ---------------------------------------------------------------------------

def consistency_modifier(prob: float, team_a: dict, team_b: dict) -> float:
    """
    Volatile matchups pull probability toward 0.5.

    When both teams are volatile, the game is less predictable —
    the favorite's edge shrinks. When both are consistent, the
    favorite's edge holds.

    Returns adjusted probability (not a delta).
    """
    cons_a = team_a.get('consistency', 14)
    cons_b = team_b.get('consistency', 14)

    # Average volatility of the matchup. D1 avg ~14.
    avg_volatility = (cons_a + cons_b) / 2
    # Scale: at avg=14 no effect, at avg=20 pull ~3% toward 0.5
    pull_factor = max(0, (avg_volatility - 14)) * 0.005

    # Pull probability toward 0.5
    return prob + (0.5 - prob) * pull_factor


# ---------------------------------------------------------------------------
# Factor 6: Clutch / close-game factor
# ---------------------------------------------------------------------------

def clutch_factor(team: dict) -> float:
    """
    Teams that win close games (margin <= 6) may have an edge
    in tournament pressure situations.

    Returns a small EM adjustment (-0.5 to +0.5).
    """
    close_pct = team.get('close_game_pct', 0.5)
    # Center around 0.5 (expected). Very small effect — close game
    # record is noisy with small samples (most teams play ~6-10 close games).
    return (close_pct - 0.5) * 0.5


# ---------------------------------------------------------------------------
# Factor 7: Momentum
# ---------------------------------------------------------------------------

def momentum_adjustment(team: dict) -> float:
    """
    Recent shooting trend as a momentum proxy.

    Win streaks are unreliable — a team that lost a close championship
    game isn't cold, and a team that beat 3 cupcakes isn't hot.
    Instead we look at whether the team is shooting better or worse
    than their season average recently.

    Returns a small EM adjustment (~-0.3 to +0.3).
    """
    recent_efg = team.get('recent_efg', team.get('efg_pct', 50))
    season_efg = team.get('efg_pct', 50)

    # Shooting trend: if last-10 eFG% is above season average, team is hot
    efg_trend = (recent_efg - season_efg) * 0.1
    return max(-0.3, min(0.3, efg_trend))


# ---------------------------------------------------------------------------
# Factor 8: Seed history prior (Bayesian blend)
# ---------------------------------------------------------------------------

def blend_with_seed_history(
    model_prob: float,
    team_a_data: dict,
    team_b_data: dict,
    round_name: str = "r64",
) -> float:
    """
    Blend model probability with historical seed win rates.
    Only applied in R64 where seed-line data is most predictive.

    538 did this too — their model was calibrated against actual
    tournament results, not just regular season efficiency.

    80% model / 20% historical prior.
    """
    if round_name != "r64":
        return model_prob

    hist_a = team_a_data.get('seed_historical_win_rate', 0.5)
    hist_b = team_b_data.get('seed_historical_win_rate', 0.5)
    hist_total = hist_a + hist_b
    hist_prob = hist_a / hist_total if hist_total > 0 else 0.5

    return model_prob * 0.8 + hist_prob * 0.2


# ---------------------------------------------------------------------------
# Combined model
# ---------------------------------------------------------------------------

def enhanced_win_probability(
    team_a_data: dict,
    team_b_data: dict,
    base_scaling: float = 11.0,
    round_name: str = "r64",
) -> float:
    """
    538-style win probability combining all factors.

    Returns win probability for team A (0.01 to 0.99).
    """
    # Factor 1: Recency-weighted EM
    em_a = recency_weighted_em(team_a_data)
    em_b = recency_weighted_em(team_b_data)

    # Factor 2: Four Factors matchup (applied symmetrically)
    em_a += four_factors_edge(team_a_data, team_b_data)
    em_b += four_factors_edge(team_b_data, team_a_data)

    # Factor 3: Style matchup
    style_a = team_a_data.get('style', 'balanced')
    style_b = team_b_data.get('style', 'balanced')
    em_a += style_matchup_adjustment(style_a, style_b)
    em_b += style_matchup_adjustment(style_b, style_a)

    # Factor 6: Clutch factor
    em_a += clutch_factor(team_a_data)
    em_b += clutch_factor(team_b_data)

    # Factor 7: Momentum
    em_a += momentum_adjustment(team_a_data)
    em_b += momentum_adjustment(team_b_data)

    # Factor 4: Tempo-adjusted scaling (affects variance, not EM)
    tempo_a = team_a_data.get('tempo', 68)
    tempo_b = team_b_data.get('tempo', 68)
    scaling = tempo_adjusted_scaling(tempo_a, tempo_b, base_scaling)

    # Logistic model
    diff = em_a - em_b
    prob = 1.0 / (1.0 + math.pow(10, -diff / scaling))

    # Factor 5: Consistency modifier (pulls prob toward 0.5 for volatile matchups)
    prob = consistency_modifier(prob, team_a_data, team_b_data)
    prob = max(0.01, min(0.99, prob))

    # Factor 8: Seed history prior (R64 only)
    prob = blend_with_seed_history(prob, team_a_data, team_b_data, round_name)

    return prob


# ---------------------------------------------------------------------------
# Legacy function (backwards compat for simple EM-only calculations)
# ---------------------------------------------------------------------------

def win_probability(em_a: float, em_b: float, scaling: float = 11.0) -> float:
    """Simple logistic win probability from raw efficiency margins."""
    diff = em_a - em_b
    return 1.0 / (1.0 + math.pow(10, -diff / scaling))


def predict_score(team_a: dict, team_b: dict) -> tuple[int, int]:
    """
    Predict the score of a matchup based on efficiency and tempo.

    Uses the formula:
        team_score = (team_adj_o * opp_adj_d / avg_efficiency) * (avg_tempo / 100)
    """
    avg_eff = 106.0  # D1 average efficiency
    avg_tempo = (team_a.get("tempo", 68) + team_b.get("tempo", 68)) / 2

    a_score = (team_a.get("adj_o", 106) * team_b.get("adj_d", 106) / avg_eff) * (avg_tempo / 100)
    b_score = (team_b.get("adj_o", 106) * team_a.get("adj_d", 106) / avg_eff) * (avg_tempo / 100)

    return round(a_score), round(b_score)


def apply_adjustments(teams: dict[str, dict], adjustments: dict) -> dict[str, dict]:
    """
    Apply injury/form/momentum adjustments to team efficiency margins.
    A factor of 0.92 means the team plays at 92% of their normal margin.
    """
    adjusted = {}
    for name, team in teams.items():
        t = team.copy()
        if name in adjustments:
            adj = adjustments[name]
            factor = adj.get("factor", 1.0) if isinstance(adj, dict) else adj
            raw_em = t["adj_em"]
            t["adj_em"] = raw_em * factor
            t["adjusted"] = True
            t["adj_factor"] = factor
        else:
            t["adjusted"] = False
            t["adj_factor"] = 1.0
        adjusted[name] = t
    return adjusted


def simulate_single(
    bracket: dict,
    teams: dict[str, dict],
    scaling: float = 11.0,
    locked_picks: dict[str, str] | None = None,
) -> dict:
    """
    Simulate one full tournament. Returns per-team highest round reached.
    """
    locked = locked_picks or {}
    results = {}
    region_winners = {}

    def _get_team(name):
        return teams.get(name, {})

    for region_name, matchups in bracket.items():
        # R64: 8 games -> 8 winners
        round_teams = []
        for i, (a, b) in enumerate(matchups):
            lock_key = f"R64-{region_name}-{i}"
            if lock_key in locked:
                winner = locked[lock_key]
            else:
                p = enhanced_win_probability(
                    _get_team(a), _get_team(b), scaling, "r64"
                )
                winner = a if random.random() < p else b
            round_teams.append(winner)
            results.setdefault(winner, "r64")

        # R32: 4 games
        s16_teams = []
        for i in range(0, len(round_teams), 2):
            a, b = round_teams[i], round_teams[i + 1]
            lock_key = f"R32-{region_name}-{i // 2}"
            if lock_key in locked:
                winner = locked[lock_key]
            else:
                p = enhanced_win_probability(
                    _get_team(a), _get_team(b), scaling, "r32"
                )
                winner = a if random.random() < p else b
            s16_teams.append(winner)
            results[winner] = "r32"

        # S16: 2 games
        e8_teams = []
        for i in range(0, len(s16_teams), 2):
            a, b = s16_teams[i], s16_teams[i + 1]
            lock_key = f"S16-{region_name}-{i // 2}"
            if lock_key in locked:
                winner = locked[lock_key]
            else:
                p = enhanced_win_probability(
                    _get_team(a), _get_team(b), scaling, "s16"
                )
                winner = a if random.random() < p else b
            e8_teams.append(winner)
            results[winner] = "s16"

        # E8: 1 game -> regional champion
        a, b = e8_teams[0], e8_teams[1]
        lock_key = f"E8-{region_name}-0"
        if lock_key in locked:
            winner = locked[lock_key]
        else:
            p = enhanced_win_probability(
                _get_team(a), _get_team(b), scaling, "e8"
            )
            winner = a if random.random() < p else b
        region_winners[region_name] = winner
        results[winner] = "e8"

    # Final Four
    for rw in region_winners.values():
        if rw:
            results[rw] = "f4"

    finalists = []
    for r1, r2 in FF_PAIRS:
        a = region_winners.get(r1, "")
        b = region_winners.get(r2, "")
        lock_key = f"F4-{r1}_{r2}-0"
        if lock_key in locked:
            winner = locked[lock_key]
        elif a and b:
            p = enhanced_win_probability(
                _get_team(a), _get_team(b), scaling, "f4"
            )
            winner = a if random.random() < p else b
        else:
            winner = a or b
        finalists.append(winner)

    for f in finalists:
        results[f] = "finals"

    # Championship
    if len(finalists) == 2:
        a, b = finalists
        lock_key = "FINAL-0"
        if lock_key in locked:
            winner = locked[lock_key]
        else:
            p = enhanced_win_probability(
                _get_team(a), _get_team(b), scaling, "finals"
            )
            winner = a if random.random() < p else b
        results[winner] = "champion"

    return results


# Map round names to numeric values for comparison
ROUND_ORDER = {
    "r64": 1, "r32": 2, "s16": 3, "e8": 4,
    "f4": 5, "finals": 6, "champion": 7,
}


def simulate(
    bracket: dict,
    teams: dict[str, dict],
    n: int = 10000,
    scaling: float = 11.0,
    locked_picks: dict[str, str] | None = None,
    adjustments: dict | None = None,
) -> dict:
    """
    Run N tournament simulations and aggregate results.
    """
    if adjustments:
        adj_teams = apply_adjustments(teams, adjustments)
    else:
        adj_teams = teams

    all_teams = set()
    for matchups in bracket.values():
        for a, b in matchups:
            all_teams.add(a)
            all_teams.add(b)

    counts = {
        team: {r: 0 for r in ROUND_NAMES}
        for team in all_teams
    }

    for _ in range(n):
        result = simulate_single(bracket, adj_teams, scaling, locked_picks)
        for team, highest_round in result.items():
            team_order = ROUND_ORDER.get(highest_round, 0)
            for round_name, order in ROUND_ORDER.items():
                if team_order >= order:
                    counts[team][round_name] += 1

    results = []
    for team in all_teams:
        t = teams.get(team, {})
        results.append({
            "team": team,
            "seed": t.get("seed", 0),
            "region": t.get("region", ""),
            "kenpom_rank": t.get("kenpom_rank", 999),
            "adj_em": adj_teams.get(team, {}).get("adj_em", 0),
            "raw_em": t.get("adj_em", 0),
            "adjusted": adj_teams.get(team, {}).get("adjusted", False),
            "adj_factor": adj_teams.get(team, {}).get("adj_factor", 1.0),
            **{
                round_name: round(counts[team][round_name] / n * 100, 2)
                for round_name in ROUND_NAMES
            },
        })

    results.sort(key=lambda x: x["champion"], reverse=True)

    matchup_probs = {}
    for region_name, matchups in bracket.items():
        region_matchups = []
        for a, b in matchups:
            em_a = adj_teams.get(a, {}).get("adj_em", 0)
            em_b = adj_teams.get(b, {}).get("adj_em", 0)
            prob_a = win_probability(em_a, em_b, scaling)
            score_a, score_b = predict_score(
                adj_teams.get(a, {}), adj_teams.get(b, {})
            )
            region_matchups.append({
                "team_a": a,
                "team_b": b,
                "seed_a": teams.get(a, {}).get("seed", 0),
                "seed_b": teams.get(b, {}).get("seed", 0),
                "prob_a": round(prob_a * 100, 1),
                "prob_b": round((1 - prob_a) * 100, 1),
                "score_a": score_a,
                "score_b": score_b,
                "em_a": round(em_a, 1),
                "em_b": round(em_b, 1),
            })
        matchup_probs[region_name] = region_matchups

    return {
        "n_sims": n,
        "scaling_factor": scaling,
        "results": results,
        "matchups": matchup_probs,
    }
