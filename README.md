# Bracket Simulator — 538-Style NCAA Tournament Model

Monte Carlo bracket simulator for the 2026 NCAA Men's Basketball Tournament. Uses adjusted efficiency margins (KenPom-style) with a logistic win probability model, injury/form adjustments, and configurable chaos factor.

## Quick Start

```bash
# One-time setup
make setup

# Run (two terminals)
make backend    # FastAPI on :8000
make frontend   # Vite on :3000 (proxied to backend)

# Open http://localhost:3000
```

## CLI Simulation (no server needed)

```bash
make sim
```

Runs 10K simulations and prints championship odds to terminal.

## Architecture

```
backend/
  main.py          FastAPI server with CORS
  simulator.py     Monte Carlo engine (NumPy)
  scraper.py       Bart Torvik data scraper (+ JSON fallback)
  models.py        Pydantic schemas
  data/
    teams.json     Team ratings (cached/fallback)
    bracket.json   R64 pairings by region
    adjustments.json  Injury/form overrides

frontend/
  src/App.jsx      React UI (Vite)
  src/api.js       Backend API client
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/teams` | All teams with ratings + adjustments |
| GET | `/teams/refresh` | Re-scrape Bart Torvik |
| GET | `/bracket` | Bracket structure |
| POST | `/simulate` | Run N simulations |
| GET | `/matchup/{a}/{b}` | Head-to-head probability |
| GET | `/adjustments` | Current overrides |
| PUT | `/adjustments/{team}` | Add/update override |
| DELETE | `/adjustments/{team}` | Remove override |

Full docs at `http://localhost:8000/docs` (Swagger UI).

## Simulation Parameters

**POST /simulate**

```json
{
  "n": 10000,
  "scaling_factor": 11.0,
  "locked_picks": {
    "R64-East-0": "Duke",
    "R32-East-0": "Duke"
  }
}
```

- **n**: Number of simulations (100–100,000)
- **scaling_factor**: Logistic scaling for win probability
  - `9.0–10.0`: Very chalky (favors higher seeds)
  - `11.0`: Standard (matches historical accuracy)
  - `12.0–14.0`: Chaos mode (more upsets)
- **locked_picks**: Lock specific winners, sim respects downstream
  - Key format: `{ROUND}-{REGION}-{INDEX}`
  - Rounds: R64, R32, S16, E8, F4, FINAL

## Adjustments

Multiply a team's efficiency margin before simulation:

```bash
# Duke at 92% strength (Foster injury)
curl -X PUT http://localhost:8000/adjustments/Duke \
  -H "Content-Type: application/json" \
  -d '{"factor": 0.92, "note": "Foster out, 7-man rotation", "adj_type": "injury"}'
```

Pre-configured adjustments for Duke, Texas Tech, Kentucky, UNC, BYU, UCLA, UConn, and Clemson based on known injuries/form issues.

## The Model

Win probability uses a logistic function on adjusted efficiency margin:

```
P(A wins) = 1 / (1 + 10^(-(EM_A - EM_B) / scaling))
```

Where EM = AdjO - AdjD (adjusted offensive efficiency minus adjusted defensive efficiency), and scaling controls variance. This matches the approach used by KenPom, 538, and most public bracket models.

**What it captures:** Overall team quality, offensive/defensive efficiency, tempo.

**What it doesn't:** Matchup-specific styles, injuries (use adjustments), coaching tendencies, travel/venue effects, momentum. That's what your brain is for.

## Refreshing Data

```bash
# Scrape latest from Bart Torvik
make refresh

# Or via API
curl http://localhost:8000/teams/refresh
```

Falls back to `data/teams.json` if scraping fails. You can also manually edit the JSON.

## Stack

- **Backend**: Python 3.11+, FastAPI, NumPy, httpx, BeautifulSoup
- **Frontend**: React 18, Vite
- **No database** — JSON files for storage, all state in memory
