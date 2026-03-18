#!/usr/bin/env python3
"""
Enriches teams.json with advanced statistical fields for bracket simulation.
Derives new fields from existing adj_o, adj_d, adj_em, tempo, kenpom_rank, conference.
Uses deterministic randomness seeded by team name for reproducibility.
"""

import json
import hashlib
import random
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEAMS_PATH = os.path.join(SCRIPT_DIR, "data", "teams.json")

POWER_CONFERENCES = {"ACC", "Big Ten", "Big 12", "SEC", "Big East"}

SEED_WIN_RATES = {
    1: 0.993, 2: 0.944, 3: 0.857, 4: 0.793,
    5: 0.643, 6: 0.629, 7: 0.607, 8: 0.500,
    9: 0.500, 10: 0.393, 11: 0.371, 12: 0.357,
    13: 0.207, 14: 0.143, 15: 0.056, 16: 0.007,
}


def team_rng(team_name: str) -> random.Random:
    """Create a deterministic RNG seeded by team name."""
    seed = int(hashlib.md5(team_name.encode()).hexdigest(), 16) % (2**32)
    return random.Random(seed)


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


def normalize(val, src_lo, src_hi, dst_lo, dst_hi):
    """Linear map from [src_lo, src_hi] to [dst_lo, dst_hi]."""
    t = (val - src_lo) / (src_hi - src_lo) if src_hi != src_lo else 0.5
    t = max(0.0, min(1.0, t))
    return dst_lo + t * (dst_hi - dst_lo)


def enrich_team(team: dict) -> dict:
    rng = team_rng(team["name"])
    adj_o = team["adj_o"]
    adj_d = team["adj_d"]
    adj_em = team["adj_em"]
    tempo = team["tempo"]
    kenpom_rank = team["kenpom_rank"]
    conference = team["conference"]
    seed = team["seed"]
    is_power = conference in POWER_CONFERENCES

    # Helper: add gaussian noise clamped to range
    def noisy(base, noise_std, lo, hi):
        return clamp(base + rng.gauss(0, noise_std), lo, hi)

    # --- Four Factors (Offense) ---
    # adj_o range in data: ~101-126. Map to efg_pct ~46-56%
    efg_base = normalize(adj_o, 101, 126, 46.0, 56.0)
    efg_pct = round(noisy(efg_base, 1.0, 46.0, 56.0), 1)

    # Turnover rate (offense, lower = better). Better teams slightly lower.
    to_base = normalize(kenpom_rank, 1, 210, 14.5, 21.0)
    to_rate = round(noisy(to_base, 1.5, 14.0, 22.0), 1)

    # Offensive rebounding rate. Slight correlation with interior play / adj_o
    orb_base = normalize(adj_o, 101, 126, 26.0, 34.0) + rng.gauss(0, 2.0)
    orb_rate = round(clamp(orb_base, 24.0, 36.0), 1)

    # FT rate offense. Mild correlation with adj_o
    ft_base = normalize(adj_o, 101, 126, 27.0, 38.0)
    ft_rate = round(noisy(ft_base, 3.0, 25.0, 42.0), 1)

    # --- Four Factors (Defense) ---
    # adj_d range: ~84-106. Lower adj_d = better defense = lower efg_pct_d
    efg_d_base = normalize(adj_d, 84, 106, 44.0, 54.0)
    efg_pct_d = round(noisy(efg_d_base, 1.0, 44.0, 54.0), 1)

    # Forced turnover rate (defense, higher = better). Better defenders force more.
    to_d_base = normalize(adj_d, 84, 106, 21.0, 15.0)  # reversed: low adj_d -> high forced TO
    to_rate_d = round(noisy(to_d_base, 1.5, 14.0, 22.0), 1)

    # Defensive rebounding rate. Better defenders rebound better.
    drb_base = normalize(adj_d, 84, 106, 77.0, 67.0)  # reversed
    drb_rate = round(noisy(drb_base, 2.0, 66.0, 78.0), 1)

    # Opponent FT rate (lower = better defense)
    ft_d_base = normalize(adj_d, 84, 106, 26.0, 38.0)
    ft_rate_d = round(noisy(ft_d_base, 3.0, 25.0, 42.0), 1)

    # --- Shooting Profile ---
    # Three-point rate: style variance, slight correlation with tempo
    three_rate_base = normalize(tempo, 60, 75, 33.0, 42.0) + rng.gauss(0, 4.0)
    three_rate = round(clamp(three_rate_base, 30.0, 48.0), 1)

    # Three-point percentage: correlated with efg_pct
    three_pct_base = normalize(efg_pct, 46, 56, 31.0, 38.0)
    three_pct = round(noisy(three_pct_base, 1.5, 30.0, 40.0), 1)

    # Two-point percentage: correlated with adj_o
    two_pct_base = normalize(adj_o, 101, 126, 47.0, 56.0)
    two_pct = round(noisy(two_pct_base, 1.5, 46.0, 58.0), 1)

    # Block rate: correlated with defensive quality
    blk_base = normalize(adj_d, 84, 106, 14.0, 8.0)  # reversed
    blk_rate = round(noisy(blk_base, 1.5, 7.0, 15.0), 1)

    # --- Schedule & Form ---
    # SOS: power conference teams higher
    if is_power:
        sos_base = rng.gauss(6.0, 3.0)
    else:
        sos_base = rng.gauss(-1.0, 3.0)
    sos = round(clamp(sos_base, -5.0, 12.0), 1)

    # SOS rank: derive from sos value (higher sos = lower/better rank)
    sos_rank = int(clamp(normalize(sos, 12.0, -5.0, 1, 364), 1, 364))
    # Add some noise to rank
    sos_rank = int(clamp(sos_rank + rng.randint(-20, 20), 1, 364))

    # Last 10 games wins
    last_10_base = normalize(kenpom_rank, 1, 210, 9.0, 6.0)
    last_10 = int(clamp(round(last_10_base + rng.gauss(0, 1.0)), 5, 10))

    # Recent form: correlated with adj_em but noisy
    recent_form = round(adj_em + rng.gauss(0, 4.0), 1)

    # --- Consistency ---
    # Higher seeds tend to be more consistent (lower std dev) but with variance
    consistency_base = normalize(seed, 1, 16, 9.0, 13.0)
    # Some good teams are volatile (add chance of high variance for any team)
    if rng.random() < 0.15:  # 15% chance of being a high-variance team
        consistency_base += rng.uniform(2.0, 4.0)
    consistency = round(noisy(consistency_base, 1.5, 8.0, 16.0), 1)

    # --- Style Classification ---
    # Score each archetype and pick the strongest signal
    off_contribution = adj_o - 110  # above avg offense
    def_contribution = 96 - adj_d   # above avg defense (lower adj_d = more)

    scores = {}

    # Perimeter: high 3-rate, good 3pt%
    scores["perimeter"] = (
        (three_rate - 35.0) * 0.3 +       # 3-rate above 35 adds signal
        (three_pct - 34.0) * 0.2 +         # good 3pt shooting
        (-1.0 if two_pct > 54.0 else 0.0)  # penalize if also elite inside
    )

    # Interior: low 3-rate, high 2pt%, good rebounding
    scores["interior"] = (
        (35.0 - three_rate) * 0.25 +       # low 3-rate
        (two_pct - 50.0) * 0.3 +           # strong 2pt%
        (orb_rate - 29.0) * 0.15 +         # offensive boards
        (blk_rate - 10.0) * 0.1            # shot blocking
    )

    # Transition: high tempo, fast pace
    scores["transition"] = (
        (tempo - 67.0) * 0.5 +             # tempo above average
        (to_rate_d - 17.0) * 0.15 +        # forces TOs -> fast breaks
        (-1.0 if tempo < 66.0 else 0.0)    # hard penalty for slow teams
    )

    # Defense first: elite defense, defense > offense contribution
    scores["defense_first"] = (
        (96.0 - adj_d) * 0.3 +             # defensive efficiency
        (def_contribution - off_contribution) * 0.2 +  # defense-driven EM
        (efg_pct_d < 48.0) * 1.0 +         # elite opponent eFG%
        (blk_rate - 10.0) * 0.1 +          # shot blocking
        (-2.0 if adj_d > 97.0 else 0.0)    # hard penalty for bad defense
    )

    # Balanced is the default — only wins if no strong signal
    scores["balanced"] = 1.0  # baseline threshold

    style = max(scores, key=scores.get)

    # If no archetype scores above the balanced baseline, stay balanced
    if style != "balanced" and scores[style] < scores["balanced"]:
        style = "balanced"

    # --- Seed Historical Win Rate ---
    seed_historical_win_rate = SEED_WIN_RATES.get(seed, 0.5)

    # Merge new fields into team dict
    team.update({
        "efg_pct": efg_pct,
        "efg_pct_d": efg_pct_d,
        "to_rate": to_rate,
        "to_rate_d": to_rate_d,
        "orb_rate": orb_rate,
        "drb_rate": drb_rate,
        "ft_rate": ft_rate,
        "ft_rate_d": ft_rate_d,
        "three_rate": three_rate,
        "three_pct": three_pct,
        "two_pct": two_pct,
        "blk_rate": blk_rate,
        "sos": sos,
        "sos_rank": sos_rank,
        "last_10": last_10,
        "recent_form": recent_form,
        "consistency": consistency,
        "style": style,
        "seed_historical_win_rate": seed_historical_win_rate,
    })
    return team


def main():
    with open(TEAMS_PATH, "r") as f:
        teams = json.load(f)

    print(f"Loaded {len(teams)} teams from {TEAMS_PATH}")

    for team in teams:
        enrich_team(team)

    with open(TEAMS_PATH, "w") as f:
        json.dump(teams, f, indent=2)

    print(f"Wrote enhanced data back to {TEAMS_PATH}\n")

    # Print sample teams for verification
    samples = ["Duke", "Virginia", "Alabama", "Houston", "Siena"]
    for name in samples:
        team = next((t for t in teams if t["name"] == name), None)
        if team:
            print(f"=== {team['name']} (#{team['seed']} seed, KenPom #{team['kenpom_rank']}) ===")
            print(f"  Style: {team['style']} | Tempo: {team['tempo']}")
            print(f"  eFG%: {team['efg_pct']} | eFG% D: {team['efg_pct_d']}")
            print(f"  TO Rate: {team['to_rate']} | Forced TO: {team['to_rate_d']}")
            print(f"  ORB%: {team['orb_rate']} | DRB%: {team['drb_rate']}")
            print(f"  FT Rate: {team['ft_rate']} | Opp FT Rate: {team['ft_rate_d']}")
            print(f"  3-Rate: {team['three_rate']} | 3PT%: {team['three_pct']} | 2PT%: {team['two_pct']}")
            print(f"  Blk Rate: {team['blk_rate']} | SOS: {team['sos']} (rank {team['sos_rank']})")
            print(f"  Last 10: {team['last_10']} | Recent Form: {team['recent_form']}")
            print(f"  Consistency: {team['consistency']} | Seed Win Rate: {team['seed_historical_win_rate']}")
            print()


if __name__ == "__main__":
    main()
