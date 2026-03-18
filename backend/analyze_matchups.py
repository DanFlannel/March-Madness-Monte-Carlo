#!/usr/bin/env python3
"""
Analyze style matchup performance from real game data.

Computes how each play style performs against every other style,
relative to expected margin (based on adj_em difference). Outputs
an empirical matchup matrix for the simulator.

Usage:
    python analyze_matchups.py              # full analysis
    python analyze_matchups.py --export     # print matrix ready to paste into simulator.py
    python analyze_matchups.py --style perimeter  # deep dive on one style
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def load_data():
    teams = json.loads((DATA_DIR / "teams.json").read_text())
    games = json.loads((DATA_DIR / "games.json").read_text())
    td = {t["name"]: t for t in teams}
    return teams, games, td


def build_matchup_data(teams, games, td):
    """
    For every game between two bracket teams, compute margin vs expected.
    margin_vs_expected = actual_margin - (team_em - opp_em)
    Positive = attacker overperformed their EM edge.
    """
    style_lookup = {t["name"]: t.get("style", "balanced") for t in teams}
    matchup_data = defaultdict(list)
    game_details = defaultdict(list)

    for team_name, game_list in games.items():
        if team_name not in td:
            continue
        team_style = style_lookup[team_name]

        for g in game_list:
            opp = g.get("opp_name_abbr", "")
            if opp not in td:
                continue

            opp_style = style_lookup[opp]
            em_diff = td[team_name]["adj_em"] - td[opp]["adj_em"]
            margin = g.get("margin", 0)
            vs_expected = margin - em_diff

            key = (team_style, opp_style)
            matchup_data[key].append(vs_expected)
            game_details[key].append({
                "team": team_name,
                "opp": opp,
                "margin": margin,
                "em_diff": round(em_diff, 1),
                "vs_expected": round(vs_expected, 1),
                "win": g.get("win", False),
            })

    return matchup_data, game_details


def print_full_matrix(matchup_data):
    styles = ["perimeter", "interior", "transition", "defense_first", "balanced"]

    print()
    print("=" * 90)
    print(f"{'EMPIRICAL STYLE MATCHUP MATRIX':^90}")
    print(f"{'Margin vs Expected (positive = attacker overperforms)':^90}")
    print("=" * 90)
    print()

    # Header
    print(f"{'ATTACKER →':<20}", end="")
    for s in styles:
        print(f"{s:>14}", end="")
    print()
    print("-" * 90)

    for defender in styles:
        print(f"{'vs ' + defender:<20}", end="")
        for attacker in styles:
            vals = matchup_data.get((attacker, defender), [])
            n = len(vals)
            if n >= 3:
                avg = statistics.mean(vals)
                print(f"{avg:>+8.1f} ({n:>2})", end="")
            elif n > 0:
                avg = statistics.mean(vals)
                print(f"{avg:>+8.1f} ({n:>2})", end="")
            else:
                print(f"{'—':>8} ({n:>2})", end="")
        print()

    print()


def print_reliable_matchups(matchup_data, min_games=10):
    print()
    print("=" * 80)
    print(f"{'RELIABLE MATCHUPS (n >= ' + str(min_games) + ')':^80}")
    print("=" * 80)
    print()
    print(f"{'Matchup':<35} {'N':>4} {'Avg':>7} {'StdDev':>7}  {'Verdict'}")
    print("-" * 75)

    rows = []
    for (att, defe), vals in matchup_data.items():
        if att == defe or len(vals) < min_games:
            continue
        avg = statistics.mean(vals)
        std = statistics.stdev(vals) if len(vals) > 1 else 0
        rows.append((att, defe, len(vals), avg, std))

    rows.sort(key=lambda x: -abs(x[3]))

    for att, defe, n, avg, std in rows:
        if avg > 2:
            verdict = f"{att} BEATS {defe}"
        elif avg < -2:
            verdict = f"{att} LOSES TO {defe}"
        else:
            verdict = "neutral"
        print(f"{att + ' vs ' + defe:<35} {n:>4} {avg:>+7.1f} {std:>7.1f}  {verdict}")

    print()


def print_style_summary(matchup_data, teams):
    """Overall win rate and performance by style."""
    styles = ["perimeter", "interior", "transition", "defense_first", "balanced"]
    style_lookup = {t["name"]: t.get("style", "balanced") for t in teams}

    print()
    print("=" * 60)
    print(f"{'STYLE OVERVIEW':^60}")
    print("=" * 60)
    print()

    # Count teams per style
    from collections import Counter
    style_counts = Counter(t.get("style", "balanced") for t in teams)

    print(f"{'Style':<18} {'Teams':>6} {'Avg EM':>8} {'Avg Recent':>11}")
    print("-" * 45)
    for s in styles:
        s_teams = [t for t in teams if t.get("style") == s]
        avg_em = statistics.mean([t["adj_em"] for t in s_teams]) if s_teams else 0
        avg_recent = statistics.mean([t.get("recent_form", 0) for t in s_teams]) if s_teams else 0
        print(f"{s:<18} {len(s_teams):>6} {avg_em:>8.1f} {avg_recent:>11.1f}")

    # Overall performance vs expected by style (as attacker)
    print()
    print(f"{'Style':<18} {'Games':>6} {'Avg vs Expected':>16} {'Description'}")
    print("-" * 65)
    for s in styles:
        all_vals = []
        for (att, _), vals in matchup_data.items():
            if att == s:
                all_vals.extend(vals)
        if all_vals:
            avg = statistics.mean(all_vals)
            if avg > 1:
                desc = "overperforms EM"
            elif avg < -1:
                desc = "underperforms EM"
            else:
                desc = "performs to EM"
            print(f"{s:<18} {len(all_vals):>6} {avg:>+16.1f} {desc}")

    print()


def print_export(matchup_data, scale=0.15, cap=1.5, min_games=10, min_effect=0.3):
    """Print a matrix ready to paste into simulator.py."""
    print()
    print("=" * 80)
    print("SIMULATOR MATRIX (paste into simulator.py)")
    print(f"Scale factor: {scale}, cap: ±{cap}, min games: {min_games}, min effect: {min_effect}")
    print("=" * 80)
    print()
    print("STYLE_MATCHUP_MATRIX = {")

    entries = []
    for (att, defe), vals in sorted(matchup_data.items()):
        if att == defe or len(vals) < min_games:
            continue
        avg = statistics.mean(vals)
        capped = max(-cap, min(cap, avg * scale))
        if abs(capped) < min_effect:
            continue
        n = len(vals)
        entries.append((att, defe, capped, avg, n))

    for att, defe, capped, raw, n in entries:
        print(f'    ("{att}", "{defe}"): {capped:.1f},  '
              f"# n={n}, raw={raw:+.1f}")

    print("}")
    print()


def deep_dive_style(matchup_data, game_details, style):
    """Show detailed game-by-game for one style."""
    styles_against = ["perimeter", "interior", "transition", "defense_first", "balanced"]

    print()
    print("=" * 80)
    print(f"DEEP DIVE: {style.upper()}")
    print("=" * 80)

    for opp_style in styles_against:
        games = game_details.get((style, opp_style), [])
        if not games:
            continue

        margins = [g["vs_expected"] for g in games]
        avg = statistics.mean(margins)
        wins = sum(1 for g in games if g["win"])

        print(f"\n  vs {opp_style} ({len(games)} games, {wins}W-{len(games)-wins}L, "
              f"avg vs expected: {avg:+.1f})")
        print(f"  {'Team':<20} {'Opp':<20} {'Margin':>7} {'Expected':>9} {'vs Exp':>7}")
        print(f"  {'-'*65}")
        for g in sorted(games, key=lambda x: -x["vs_expected"]):
            print(f"  {g['team']:<20} {g['opp']:<20} {g['margin']:>+7d} "
                  f"{g['em_diff']:>+9.1f} {g['vs_expected']:>+7.1f}")


def main():
    parser = argparse.ArgumentParser(description="Analyze style matchup performance")
    parser.add_argument("--export", action="store_true", help="Print simulator-ready matrix")
    parser.add_argument("--style", help="Deep dive on one style")
    parser.add_argument("--min-games", type=int, default=10, help="Min games for reliable matchup")
    args = parser.parse_args()

    teams, games, td = load_data()
    matchup_data, game_details = build_matchup_data(teams, games, td)

    total_matched = sum(len(v) for v in matchup_data.values())
    print(f"Analyzed {total_matched} games between bracket teams")

    if args.style:
        deep_dive_style(matchup_data, game_details, args.style)
        return

    print_style_summary(matchup_data, teams)
    print_full_matrix(matchup_data)
    print_reliable_matchups(matchup_data, min_games=args.min_games)

    if args.export:
        print_export(matchup_data, min_games=args.min_games)


if __name__ == "__main__":
    main()
