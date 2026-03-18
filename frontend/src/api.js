const BASE = '/api';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export const api = {
  getTeams: () => request('/teams'),
  refreshTeams: () => request('/teams/refresh'),
  getBracket: () => request('/bracket'),
  simulate: (n = 10000, lockedPicks = {}, scalingFactor = 11.0) =>
    request('/simulate', {
      method: 'POST',
      body: JSON.stringify({ n, locked_picks: lockedPicks, scaling_factor: scalingFactor }),
    }),
  matchup: (teamA, teamB, roundName = 'r64', scaling = 11.0) =>
    request(`/matchup/${encodeURIComponent(teamA)}/${encodeURIComponent(teamB)}?round_name=${roundName}&scaling=${scaling}`),
  getAdjustments: () => request('/adjustments'),
  updateAdjustment: (team, factor, note, adjType = 'injury') =>
    request(`/adjustments/${encodeURIComponent(team)}`, {
      method: 'PUT',
      body: JSON.stringify({ factor, note, adj_type: adjType }),
    }),
  removeAdjustment: (team) =>
    request(`/adjustments/${encodeURIComponent(team)}`, { method: 'DELETE' }),
  getTeamGames: (team) =>
    request(`/teams/games/${encodeURIComponent(team)}`),
};
