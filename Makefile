.PHONY: setup backend frontend dev clean

# Full setup — run once
setup: setup-backend setup-frontend

setup-backend:
	cd backend && python3 -m venv .venv && \
	. .venv/bin/activate && \
	pip install -r requirements.txt

setup-frontend:
	cd frontend && npm install

# Run backend (port 8000)
backend:
	cd backend && . .venv/bin/activate && \
	uvicorn main:app --reload --port 8000

# Run frontend (port 3000, proxies /api -> backend)
frontend:
	cd frontend && npm run dev

# Run both (use two terminals, or use this with &)
dev:
	@echo "Run these in two separate terminals:"
	@echo "  make backend"
	@echo "  make frontend"
	@echo ""
	@echo "Then open http://localhost:3000"
	@echo "API docs at http://localhost:8000/docs"

# Scrape fresh data from Bart Torvik
refresh:
	cd backend && . .venv/bin/activate && \
	python3 -c "import asyncio; from scraper import get_teams; print(f'Loaded {len(asyncio.run(get_teams(True)))} teams')"

# Quick simulation from CLI (no server needed)
sim:
	cd backend && . .venv/bin/activate && \
	python3 -c "\
import json; \
from simulator import simulate; \
from pathlib import Path; \
teams_raw = json.loads((Path('data/teams.json')).read_text()); \
teams = {t['name']: t for t in teams_raw}; \
bracket = json.loads((Path('data/bracket.json')).read_text()); \
adj = json.loads((Path('data/adjustments.json')).read_text()); \
r = simulate(bracket, teams, n=10000, adjustments=adj); \
print(f\"\\n{'='*70}\"); \
print(f\"  BRACKET SIMULATOR — {r['n_sims']:,} simulations @ scaling {r['scaling_factor']}\"); \
print(f\"{'='*70}\\n\"); \
print(f\"{'Team':<20} {'Seed':>4} {'Region':<10} {'R64':>6} {'R32':>6} {'S16':>6} {'E8':>6} {'F4':>6} {'W':>6}\"); \
print('-'*70); \
[print(f\"{t['team']:<20} {t['seed']:>4} {t['region']:<10} {t['r64']:>5.1f}% {t['r32']:>5.1f}% {t['s16']:>5.1f}% {t['e8']:>5.1f}% {t['f4']:>5.1f}% {t['champion']:>5.1f}%\") for t in r['results'][:25]]; \
"

# Analyze style matchup performance from real game data
matchups:
	cd backend && . .venv/bin/activate && \
	python3 analyze_matchups.py

# Export matchup matrix for simulator
matchups-export:
	cd backend && . .venv/bin/activate && \
	python3 analyze_matchups.py --export

# Deep dive on one style (e.g., make matchup-style STYLE=perimeter)
matchup-style:
	cd backend && . .venv/bin/activate && \
	python3 analyze_matchups.py --style $(STYLE)

# Scrape game-by-game data for all tournament teams
scrape:
	cd backend && . .venv/bin/activate && \
	python3 game_scraper.py --rate 1.0 --concurrency 3

# Scrape from both sources (slower, Sports-Reference rate limited)
scrape-all:
	cd backend && . .venv/bin/activate && \
	python3 game_scraper.py --source both --rate 0.5 --concurrency 2

# Scrape a single team (for testing)
scrape-team:
	cd backend && . .venv/bin/activate && \
	python3 game_scraper.py --team $(TEAM) --rate 1.0

# Show URL mappings without scraping
scrape-dry:
	cd backend && . .venv/bin/activate && \
	python3 game_scraper.py --dry-run

clean:
	rm -rf backend/.venv backend/__pycache__ frontend/node_modules frontend/dist
