import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from './api';

const COLORS = {
  bg: '#0a0b10',
  surface: '#12131a',
  border: 'rgba(255,255,255,0.06)',
  text: '#e4e4e8',
  muted: 'rgba(255,255,255,0.4)',
  accent: '#4a9eff',
  gold: '#ffd700',
  green: '#4adf6a',
  red: '#ff6b6b',
  regions: {
    East: '#4a9eff',
    West: '#c46ac4',
    Midwest: '#d4a843',
    South: '#4adf6a',
  },
};

const mono = "'JetBrains Mono', monospace";
const display = "'Oswald', sans-serif";
const body = "'DM Sans', sans-serif";

const ROUNDS = ['R64', 'R32', 'S16', 'E8', 'F4', 'FINAL'];
const ROUND_LABELS = { R64: 'Round of 64', R32: 'Round of 32', S16: 'Sweet 16', E8: 'Elite 8', F4: 'Final Four', FINAL: 'Championship' };
const FF_PAIRS = [['South', 'East'], ['West', 'Midwest']];

// ── Styles ───────────────────────────────────────────────
const styles = {
  app: {
    minHeight: '100vh', background: COLORS.bg, color: COLORS.text,
    fontFamily: body, margin: 0, padding: 0,
  },
  header: {
    padding: '20px 24px 16px', borderBottom: `1px solid ${COLORS.border}`,
    background: 'rgba(0,0,0,0.3)',
  },
  title: {
    fontFamily: display, fontSize: 28, fontWeight: 700, letterSpacing: 3, margin: 0,
    background: `linear-gradient(90deg, ${COLORS.accent}, ${COLORS.gold})`,
    WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
  },
  subtitle: { fontFamily: mono, fontSize: 11, opacity: 0.3, letterSpacing: 1, marginTop: 4 },
  nav: { display: 'flex', borderBottom: `1px solid ${COLORS.border}` },
  navBtn: (active) => ({
    flex: 1, padding: '12px 8px', border: 'none', background: 'transparent',
    borderBottom: active ? `2px solid ${COLORS.gold}` : '2px solid transparent',
    color: active ? COLORS.gold : COLORS.muted,
    fontFamily: display, fontSize: 12, letterSpacing: 2, cursor: 'pointer',
  }),
  controls: {
    padding: '12px 24px', borderBottom: `1px solid ${COLORS.border}`,
    display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
  },
  simBtn: (loading) => ({
    padding: '8px 20px', borderRadius: 6, border: 'none',
    background: loading ? 'rgba(255,255,255,0.1)' : `linear-gradient(135deg, ${COLORS.accent}, #2a7edf)`,
    color: '#fff', fontSize: 13, fontFamily: display, letterSpacing: 1.5,
    cursor: loading ? 'wait' : 'pointer', fontWeight: 600,
  }),
  countBtn: (active) => ({
    padding: '4px 12px', borderRadius: 4,
    border: active ? `1px solid ${COLORS.accent}` : '1px solid rgba(255,255,255,0.1)',
    background: active ? `${COLORS.accent}22` : 'transparent',
    color: active ? COLORS.accent : COLORS.muted,
    fontSize: 11, fontFamily: mono, cursor: 'pointer',
  }),
  card: {
    background: 'rgba(255,255,255,0.03)', border: `1px solid ${COLORS.border}`,
    borderRadius: 8, padding: '12px 14px', marginBottom: 8,
  },
  scalingLabel: { fontSize: 10, fontFamily: mono, opacity: 0.5 },
  slider: { width: 100, accentColor: COLORS.accent },
};

// ── Build matchups for a given round from bracket + picks ──
function buildMatchups(bracket, picks, teamsData) {
  const rounds = {};

  // R64: directly from bracket
  const r64 = {};
  for (const [region, matchups] of Object.entries(bracket)) {
    r64[region] = matchups.map(([a, b], i) => ({
      team_a: a, team_b: b,
      seed_a: teamsData[a]?.seed || 0, seed_b: teamsData[b]?.seed || 0,
      key: `R64-${region}-${i}`,
    }));
  }
  rounds.R64 = r64;

  // R32: winners of adjacent R64 matchups
  const r32 = {};
  for (const region of Object.keys(bracket)) {
    const r64m = r64[region];
    const games = [];
    for (let i = 0; i < r64m.length; i += 2) {
      const a = picks[r64m[i].key];
      const b = picks[r64m[i + 1].key];
      games.push({
        team_a: a || null, team_b: b || null,
        seed_a: a ? (teamsData[a]?.seed || 0) : 0,
        seed_b: b ? (teamsData[b]?.seed || 0) : 0,
        key: `R32-${region}-${i / 2}`,
        needs: [!a && r64m[i].key, !b && r64m[i + 1].key].filter(Boolean),
      });
    }
    r32[region] = games;
  }
  rounds.R32 = r32;

  // S16: winners of adjacent R32 matchups
  const s16 = {};
  for (const region of Object.keys(bracket)) {
    const r32m = r32[region];
    const games = [];
    for (let i = 0; i < r32m.length; i += 2) {
      const a = picks[r32m[i].key];
      const b = picks[r32m[i + 1].key];
      games.push({
        team_a: a || null, team_b: b || null,
        seed_a: a ? (teamsData[a]?.seed || 0) : 0,
        seed_b: b ? (teamsData[b]?.seed || 0) : 0,
        key: `S16-${region}-${i / 2}`,
        needs: [!a && r32m[i].key, !b && r32m[i + 1].key].filter(Boolean),
      });
    }
    s16[region] = games;
  }
  rounds.S16 = s16;

  // E8: winners of adjacent S16 matchups (regional final)
  const e8 = {};
  for (const region of Object.keys(bracket)) {
    const s16m = s16[region];
    const a = picks[s16m[0].key];
    const b = picks[s16m[1].key];
    e8[region] = [{
      team_a: a || null, team_b: b || null,
      seed_a: a ? (teamsData[a]?.seed || 0) : 0,
      seed_b: b ? (teamsData[b]?.seed || 0) : 0,
      key: `E8-${region}-0`,
      needs: [!a && s16m[0].key, !b && s16m[1].key].filter(Boolean),
    }];
  }
  rounds.E8 = e8;

  // F4: South vs East, West vs Midwest
  const f4 = { 'Final Four': [] };
  for (const [r1, r2] of FF_PAIRS) {
    const a = picks[`E8-${r1}-0`];
    const b = picks[`E8-${r2}-0`];
    f4['Final Four'].push({
      team_a: a || null, team_b: b || null,
      seed_a: a ? (teamsData[a]?.seed || 0) : 0,
      seed_b: b ? (teamsData[b]?.seed || 0) : 0,
      key: `F4-${r1}_${r2}-0`,
      label: `${r1} vs ${r2}`,
      needs: [!a && `E8-${r1}-0`, !b && `E8-${r2}-0`].filter(Boolean),
    });
  }
  rounds.F4 = f4;

  // FINAL
  const f4Games = f4['Final Four'];
  const fa = picks[f4Games[0].key];
  const fb = picks[f4Games[1].key];
  rounds.FINAL = {
    'Championship': [{
      team_a: fa || null, team_b: fb || null,
      seed_a: fa ? (teamsData[fa]?.seed || 0) : 0,
      seed_b: fb ? (teamsData[fb]?.seed || 0) : 0,
      key: 'FINAL-0',
      needs: [!fa && f4Games[0].key, !fb && f4Games[1].key].filter(Boolean),
    }],
  };

  return rounds;
}

// ── Pickable Team Row ────────────────────────────────────
function PickableTeam({ name, seed, prob, isPicked, isEliminated, onClick, color, side, style: teamStyle }) {
  if (!name) {
    return (
      <div style={{
        padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 8,
        opacity: 0.2, borderBottom: side === 'top' ? `1px solid ${COLORS.border}` : 'none',
      }}>
        <span style={{ fontFamily: mono, fontSize: 11, width: 22, color: COLORS.muted }}>--</span>
        <span style={{ flex: 1, fontSize: 13, fontStyle: 'italic', color: COLORS.muted }}>TBD</span>
      </div>
    );
  }

  return (
    <div
      onClick={onClick}
      style={{
        padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 8,
        cursor: isEliminated ? 'default' : 'pointer',
        background: isPicked ? `${color}15` : 'transparent',
        borderLeft: isPicked ? `3px solid ${color}` : '3px solid transparent',
        borderBottom: side === 'top' ? `1px solid ${COLORS.border}` : 'none',
        opacity: isEliminated ? 0.3 : 1,
        transition: 'all 0.15s',
      }}
    >
      <span style={{ fontFamily: mono, fontSize: 11, color: isPicked ? color : COLORS.muted, fontWeight: 700, width: 22 }}>
        {seed}
      </span>
      <span style={{
        flex: 1, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6,
        fontWeight: isPicked ? 700 : 400,
        color: isPicked ? '#fff' : COLORS.text,
        textDecoration: isEliminated ? 'line-through' : 'none',
      }}>
        {name}
        {teamStyle && (
          <span style={{
            fontSize: 8, fontFamily: mono, padding: '1px 4px', borderRadius: 3,
            background: 'rgba(255,255,255,0.06)', color: COLORS.muted,
          }}>
            {teamStyle === 'perimeter' ? 'PER' : teamStyle === 'interior' ? 'INT' : teamStyle === 'transition' ? 'TRAN' : teamStyle === 'defense_first' ? 'DEF' : 'BAL'}
          </span>
        )}
      </span>
      {prob != null && (
        <span style={{
          fontFamily: mono, fontSize: 11, fontWeight: 600,
          color: prob > 70 ? COLORS.green : prob > 40 ? COLORS.text : COLORS.red,
          minWidth: 44, textAlign: 'right',
        }}>
          {prob.toFixed(1)}%
        </span>
      )}
    </div>
  );
}

// ── Interactive Matchup Card ─────────────────────────────
function InteractiveMatchupCard({ matchup, picked, onPick, color, scaling, refreshKey, onH2H }) {
  const { team_a, team_b, seed_a, seed_b, key } = matchup;
  const bothReady = team_a && team_b;

  const [matchupData, setMatchupData] = useState(null);

  // Fetch head-to-head probability from API whenever teams, scaling, or refreshKey changes
  useEffect(() => {
    if (!bothReady) { setMatchupData(null); return; }
    let cancelled = false;
    const roundKey = key.split('-')[0];
    const roundMap = { R64: 'r64', R32: 'r32', S16: 's16', E8: 'e8', F4: 'f4', FINAL: 'finals' };
    const roundName = roundMap[roundKey] || 'r64';

    api.matchup(team_a, team_b, roundName, scaling).then(data => {
      if (!cancelled) setMatchupData(data);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [team_a, team_b, key, bothReady, scaling, refreshKey]);

  const prob_a = matchupData?.win_prob_a ?? null;
  const prob_b = matchupData?.win_prob_b ?? null;
  const style_a = matchupData?.style_a;
  const style_b = matchupData?.style_b;

  const isPickedA = picked === team_a;
  const isPickedB = picked === team_b;
  const isElimA = picked && !isPickedA;
  const isElimB = picked && !isPickedB;

  return (
    <div style={{
      ...styles.card,
      padding: 0, overflow: 'hidden',
      border: picked ? `1px solid ${color}33` : `1px solid ${COLORS.border}`,
    }}>
      <PickableTeam
        name={team_a} seed={seed_a} prob={prob_a}
        isPicked={isPickedA} isEliminated={isElimA}
        onClick={() => bothReady && onPick(key, team_a)}
        color={color} side="top" style={style_a}
      />
      <PickableTeam
        name={team_b} seed={seed_b} prob={prob_b}
        isPicked={isPickedB} isEliminated={isElimB}
        onClick={() => bothReady && onPick(key, team_b)}
        color={color} side="bottom" style={style_b}
      />
      {bothReady && prob_a != null && (
        <div style={{ height: 3, display: 'flex' }}>
          <div style={{ width: `${prob_a}%`, height: '100%', background: isPickedA ? color : `${color}66`, transition: 'width 0.3s' }} />
          <div style={{ width: `${prob_b}%`, height: '100%', background: isPickedB ? COLORS.gold : 'rgba(255,255,255,0.06)', transition: 'width 0.3s' }} />
        </div>
      )}
      {bothReady && matchupData && (
        <div style={{
          padding: '4px 12px 6px', display: 'flex', gap: 12, fontSize: 9, alignItems: 'center',
          fontFamily: mono, color: COLORS.muted, background: 'rgba(255,255,255,0.015)',
        }}>
          <span>Predicted: {matchupData.predicted_score_a}-{matchupData.predicted_score_b}</span>
          {style_a && <span>vs: {style_a} / {style_b}</span>}
          <span>EM: {matchupData.adj_em_a} / {matchupData.adj_em_b}</span>
          <button
            onClick={(e) => { e.stopPropagation(); onH2H && onH2H(team_a, team_b); }}
            style={{
              marginLeft: 'auto', padding: '2px 8px', borderRadius: 3,
              border: `1px solid ${COLORS.accent}44`, background: 'transparent',
              color: COLORS.accent, fontSize: 9, fontFamily: mono, cursor: 'pointer',
            }}
          >H2H</button>
        </div>
      )}
    </div>
  );
}

// ── Champion Banner ──────────────────────────────────────
function ChampionBanner({ team, seed, teamsData }) {
  if (!team) return null;
  const region = teamsData[team]?.region || '';
  const color = COLORS.regions[region] || COLORS.gold;
  return (
    <div style={{
      margin: '16px 16px 0', padding: '20px 24px', borderRadius: 10,
      background: `linear-gradient(135deg, ${color}22, ${COLORS.gold}22)`,
      border: `1px solid ${COLORS.gold}44`,
      textAlign: 'center',
    }}>
      <div style={{ fontFamily: mono, fontSize: 10, color: COLORS.gold, letterSpacing: 2, marginBottom: 6 }}>
        YOUR PREDICTED CHAMPION
      </div>
      <div style={{ fontFamily: display, fontSize: 32, fontWeight: 700, color: '#fff', letterSpacing: 2 }}>
        {team}
      </div>
      <div style={{ fontFamily: mono, fontSize: 12, color: COLORS.muted, marginTop: 4 }}>
        ({seed}) {region}
      </div>
    </div>
  );
}

// ── Team Row (for rankings table) ───────────────────────
function TeamRow({ team, index, rounds }) {
  const regionColor = COLORS.regions[team.region] || COLORS.accent;
  const isTop3 = index < 3;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
      background: isTop3 ? 'rgba(255,200,50,0.04)' : 'rgba(255,255,255,0.02)',
      borderRadius: 6, marginBottom: 3,
      border: isTop3 ? '1px solid rgba(255,200,50,0.08)' : `1px solid ${COLORS.border}`,
    }}>
      <span style={{ fontFamily: mono, fontSize: 11, fontWeight: 700, width: 22, color: isTop3 ? COLORS.gold : COLORS.muted }}>{index + 1}</span>
      <span style={{ fontFamily: mono, fontSize: 10, width: 18, color: regionColor, fontWeight: 700 }}>{team.seed}</span>
      <span style={{ flex: 1, fontSize: 13, fontWeight: isTop3 ? 700 : 400 }}>{team.team}</span>
      {team.adjusted && (
        <span style={{ fontSize: 8, fontFamily: mono, color: COLORS.red, padding: '1px 4px', background: 'rgba(255,100,100,0.1)', borderRadius: 3 }}>
          ADJ {team.adj_factor}x
        </span>
      )}
      <span style={{ fontFamily: mono, fontSize: 9, color: regionColor, opacity: 0.6, width: 52 }}>{team.region}</span>
      {rounds.map(r => (
        <span key={r} style={{
          fontFamily: mono, fontSize: 10, width: 42, textAlign: 'right',
          color: parseFloat(team[r]) > 30 ? COLORS.gold : parseFloat(team[r]) > 10 ? '#fff' : COLORS.muted,
          fontWeight: parseFloat(team[r]) > 30 ? 700 : 400,
        }}>{team[r]}%</span>
      ))}
    </div>
  );
}

// ── Adjustments Panel ────────────────────────────────────
function AdjustmentsPanel({ adjustments, onUpdate, onRemove }) {
  const [newTeam, setNewTeam] = useState('');
  const [newFactor, setNewFactor] = useState(0.9);
  const [newNote, setNewNote] = useState('');

  const handleAdd = () => {
    if (newTeam && newFactor) {
      onUpdate(newTeam, newFactor, newNote);
      setNewTeam(''); setNewNote(''); setNewFactor(0.9);
    }
  };

  return (
    <div style={{ padding: '16px 24px' }}>
      <div style={{ fontFamily: display, fontSize: 14, letterSpacing: 2, color: COLORS.red, marginBottom: 12 }}>
        INJURY / FORM ADJUSTMENTS
      </div>
      <div style={{ fontSize: 11, opacity: 0.5, marginBottom: 16, lineHeight: 1.6 }}>
        Multiplier on efficiency margin. 1.0 = full strength. 0.90 = 10% nerf. Applied before win probability calculation.
      </div>
      {Object.entries(adjustments || {}).map(([team, adj]) => (
        <div key={team} style={{ ...styles.card, display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontWeight: 700, fontSize: 13, flex: 1 }}>{team}</span>
          <span style={{ fontFamily: mono, fontSize: 12, color: COLORS.red }}>{(typeof adj === 'object' ? adj.factor : adj)}x</span>
          <span style={{ fontSize: 10, opacity: 0.5, flex: 2 }}>{typeof adj === 'object' ? adj.note : ''}</span>
          <button onClick={() => onRemove(team)} style={{
            padding: '4px 8px', borderRadius: 4, border: `1px solid ${COLORS.red}33`,
            background: 'transparent', color: COLORS.red, fontSize: 10, cursor: 'pointer',
          }}>Remove</button>
        </div>
      ))}
      <div style={{ ...styles.card, marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <input value={newTeam} onChange={e => setNewTeam(e.target.value)} placeholder="Team name (exact)"
          style={{ flex: 1, minWidth: 140, padding: '8px 10px', borderRadius: 4, border: `1px solid ${COLORS.border}`, background: 'rgba(255,255,255,0.05)', color: COLORS.text, fontSize: 12, fontFamily: body }} />
        <input type="number" step="0.01" min="0.5" max="1.0" value={newFactor} onChange={e => setNewFactor(parseFloat(e.target.value))}
          style={{ width: 70, padding: '8px 10px', borderRadius: 4, border: `1px solid ${COLORS.border}`, background: 'rgba(255,255,255,0.05)', color: COLORS.text, fontSize: 12, fontFamily: mono }} />
        <input value={newNote} onChange={e => setNewNote(e.target.value)} placeholder="Reason"
          style={{ flex: 2, minWidth: 140, padding: '8px 10px', borderRadius: 4, border: `1px solid ${COLORS.border}`, background: 'rgba(255,255,255,0.05)', color: COLORS.text, fontSize: 12, fontFamily: body }} />
        <button onClick={handleAdd} style={{ padding: '8px 16px', borderRadius: 4, border: 'none', background: COLORS.accent, color: '#fff', fontSize: 12, cursor: 'pointer', fontWeight: 600 }}>Add</button>
      </div>
    </div>
  );
}

// ── Radar Chart (pure SVG) ────────────────────────────────
function RadarChart({ teamA, teamB, teamAName, teamBName, allTeams }) {
  const axes = [
    { key: 'efg_pct', label: 'eFG%', invert: false },
    { key: 'efg_pct_d', label: 'eFG% D', invert: true },
    { key: 'to_rate', label: 'TO Rate', invert: true },
    { key: 'orb_rate', label: 'ORB%', invert: false },
    { key: 'ft_rate', label: 'FT Rate', invert: false },
    { key: 'consistency', label: 'Consistency', invert: true },
  ];

  // Compute min/max across all 64 teams for normalization
  const ranges = {};
  const teamsList = Object.values(allTeams);
  for (const ax of axes) {
    const vals = teamsList.map(t => t[ax.key]).filter(v => v != null);
    ranges[ax.key] = { min: Math.min(...vals), max: Math.max(...vals) };
  }

  const normalize = (val, key, invert) => {
    const { min, max } = ranges[key];
    if (max === min) return 50;
    let norm = ((val - min) / (max - min)) * 100;
    if (invert) norm = 100 - norm;
    return Math.max(0, Math.min(100, norm));
  };

  const cx = 160, cy = 150, r = 110;
  const n = axes.length;
  const angleStep = (2 * Math.PI) / n;

  const getPoint = (value, i) => {
    const angle = -Math.PI / 2 + i * angleStep;
    const dist = (value / 100) * r;
    return { x: cx + dist * Math.cos(angle), y: cy + dist * Math.sin(angle) };
  };

  const makePolygon = (team) =>
    axes.map((ax, i) => {
      const val = normalize(team[ax.key] ?? 0, ax.key, ax.invert);
      const p = getPoint(val, i);
      return `${p.x},${p.y}`;
    }).join(' ');

  const gridLevels = [20, 40, 60, 80, 100];

  return (
    <div style={{ textAlign: 'center' }}>
      <svg width="320" height="320" viewBox="0 0 320 320">
        {/* Grid rings */}
        {gridLevels.map(level => (
          <polygon key={level}
            points={axes.map((_, i) => { const p = getPoint(level, i); return `${p.x},${p.y}`; }).join(' ')}
            fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
        ))}
        {/* Axis lines */}
        {axes.map((ax, i) => {
          const p = getPoint(100, i);
          return <line key={ax.key} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="rgba(255,255,255,0.1)" strokeWidth="1" />;
        })}
        {/* Team A polygon */}
        <polygon points={makePolygon(teamA)} fill={`${COLORS.accent}33`} stroke={COLORS.accent} strokeWidth="2" />
        {/* Team B polygon */}
        <polygon points={makePolygon(teamB)} fill={`${COLORS.gold}33`} stroke={COLORS.gold} strokeWidth="2" />
        {/* Axis labels */}
        {axes.map((ax, i) => {
          const angle = -Math.PI / 2 + i * angleStep;
          const labelR = r + 22;
          const lx = cx + labelR * Math.cos(angle);
          const ly = cy + labelR * Math.sin(angle);
          return (
            <text key={ax.key} x={lx} y={ly} textAnchor="middle" dominantBaseline="central"
              style={{ fontSize: 9, fontFamily: mono, fill: 'rgba(255,255,255,0.5)' }}>
              {ax.label}
            </text>
          );
        })}
      </svg>
      {/* Legend */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 20, marginTop: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 12, height: 3, background: COLORS.accent, borderRadius: 2 }} />
          <span style={{ fontFamily: mono, fontSize: 10, color: COLORS.accent }}>{teamAName}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 12, height: 3, background: COLORS.gold, borderRadius: 2 }} />
          <span style={{ fontFamily: mono, fontSize: 10, color: COLORS.gold }}>{teamBName}</span>
        </div>
      </div>
    </div>
  );
}

// ── Margin Distribution Bar Chart (pure SVG) ─────────────
function MarginDistChart({ teamName, margins, color }) {
  if (!margins || margins.length === 0) return null;

  const buckets = [
    { label: 'Blowout W', min: 20, max: Infinity, color: COLORS.green },
    { label: 'Comfortable W', min: 8, max: 19, color: '#3ab85a' },
    { label: 'Close W', min: 1, max: 7, color: '#6aad6a' },
    { label: 'Close L', min: -7, max: 0, color: '#c47a4a' },
    { label: 'Bad L', min: -Infinity, max: -8, color: COLORS.red },
  ];

  const counts = buckets.map(b => margins.filter(m => m >= b.min && m <= b.max).length);
  const maxCount = Math.max(...counts, 1);
  const barW = 46, gap = 6, chartH = 100;
  const totalW = buckets.length * (barW + gap) - gap;

  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontFamily: mono, fontSize: 10, color: COLORS.muted, marginBottom: 6 }}>
        {teamName} — MARGIN DISTRIBUTION ({margins.length} games)
      </div>
      <svg width={totalW + 40} height={chartH + 40} viewBox={`0 0 ${totalW + 40} ${chartH + 40}`}>
        {counts.map((count, i) => {
          const barH = (count / maxCount) * chartH;
          const x = 20 + i * (barW + gap);
          const y = chartH - barH + 10;
          return (
            <g key={i}>
              <rect x={x} y={y} width={barW} height={barH} rx="3" fill={buckets[i].color} opacity="0.8" />
              <text x={x + barW / 2} y={y - 4} textAnchor="middle"
                style={{ fontSize: 10, fontFamily: mono, fill: '#fff' }}>{count}</text>
              <text x={x + barW / 2} y={chartH + 24} textAnchor="middle"
                style={{ fontSize: 7, fontFamily: mono, fill: 'rgba(255,255,255,0.4)' }}>{buckets[i].label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ── Stat Comparison Table ─────────────────────────────────
function StatComparisonTable({ teamA, teamB, nameA, nameB }) {
  const rows = [
    { label: 'Record', key: 'record', type: 'text' },
    { label: 'Seed', key: 'seed', type: 'lower' },
    { label: 'Region', key: 'region', type: 'text' },
    { label: 'KenPom Rank', key: 'kenpom_rank', type: 'lower' },
    { label: 'Adj EM', key: 'adj_em', type: 'higher' },
    { label: 'Recent Form', key: 'recent_form', type: 'higher' },
    { label: 'Road/Neutral Margin', key: 'road_neutral_margin', type: 'higher' },
    { label: 'eFG%', key: 'efg_pct', type: 'higher' },
    { label: 'eFG% Defense', key: 'efg_pct_d', type: 'lower' },
    { label: 'TO Rate', key: 'to_rate', type: 'lower' },
    { label: 'TO Rate D', key: 'to_rate_d', type: 'higher' },
    { label: 'ORB Rate', key: 'orb_rate', type: 'higher' },
    { label: 'DRB Rate', key: 'drb_rate', type: 'higher' },
    { label: '3pt%', key: 'three_pct', type: 'higher' },
    { label: '3pt Rate', key: 'three_rate', type: 'higher' },
    { label: '2pt%', key: 'two_pct', type: 'higher' },
    { label: 'Consistency', key: 'consistency', type: 'lower' },
    { label: 'Close Game %', key: 'close_game_pct', type: 'higher' },
    { label: 'Win Streak', key: 'win_streak', type: 'higher' },
    { label: 'Last 10', key: 'last_10', type: 'higher' },
    { label: 'Avg Margin', key: 'avg_margin', type: 'higher' },
    { label: 'Max Margin', key: 'max_margin', type: 'higher' },
    { label: 'Worst Loss', key: 'worst_loss', type: 'higher' },
    { label: 'Scoring Variance', key: 'scoring_variance', type: 'lower' },
  ];

  const isBetter = (valA, valB, type) => {
    if (type === 'text' || valA == null || valB == null) return 0;
    const a = parseFloat(valA), b = parseFloat(valB);
    if (isNaN(a) || isNaN(b)) return 0;
    if (type === 'higher') return a > b ? -1 : a < b ? 1 : 0;
    return a < b ? -1 : a > b ? 1 : 0;
  };

  const fmt = (v) => (v == null ? '--' : typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(1)) : v);

  return (
    <div>
      {/* Header */}
      <div style={{
        display: 'flex', padding: '8px 12px', borderBottom: `1px solid ${COLORS.border}`,
        fontFamily: mono, fontSize: 10, color: COLORS.muted,
      }}>
        <span style={{ flex: 2 }}>STAT</span>
        <span style={{ flex: 1, textAlign: 'right', color: COLORS.accent }}>{nameA}</span>
        <span style={{ flex: 1, textAlign: 'right', color: COLORS.gold }}>{nameB}</span>
      </div>
      {rows.map(row => {
        const valA = teamA[row.key];
        const valB = teamB[row.key];
        const cmp = isBetter(valA, valB, row.type);
        return (
          <div key={row.key} style={{
            display: 'flex', padding: '6px 12px', alignItems: 'center',
            borderBottom: `1px solid ${COLORS.border}`,
            background: 'rgba(255,255,255,0.015)',
          }}>
            <span style={{ flex: 2, fontSize: 11, color: COLORS.muted }}>{row.label}</span>
            <span style={{
              flex: 1, textAlign: 'right', fontFamily: mono, fontSize: 12,
              fontWeight: cmp === -1 ? 700 : 400,
              color: cmp === -1 ? COLORS.green : COLORS.text,
            }}>{fmt(valA)}</span>
            <span style={{
              flex: 1, textAlign: 'right', fontFamily: mono, fontSize: 12,
              fontWeight: cmp === 1 ? 700 : 400,
              color: cmp === 1 ? COLORS.green : COLORS.text,
            }}>{fmt(valB)}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── Game Log (Last 10 + Losses) ──────────────────────────
function GameLog({ title, games, color }) {
  if (!games || games.length === 0) return null;

  const locLabel = (loc) => {
    if (loc === '@') return 'A';
    if (loc === 'N') return 'N';
    return 'H';
  };

  const locColor = (loc) => {
    if (loc === '@') return COLORS.red;
    if (loc === 'N') return COLORS.gold;
    return COLORS.green;
  };

  return (
    <div>
      <div style={{
        fontFamily: mono, fontSize: 10, color, letterSpacing: 1,
        padding: '8px 12px', borderBottom: `1px solid ${COLORS.border}`,
      }}>
        {title} ({games.length})
      </div>
      {games.map((g, i) => {
        const win = g.win;
        const margin = g.margin || 0;
        const opp = g.opp_name_abbr || '?';
        const seed = g.opp_seed;
        const inBracket = g.opp_in_bracket;
        const loc = g.game_location || '';
        const date = g.date || '';

        return (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '4px 12px',
            borderBottom: `1px solid ${COLORS.border}`,
            background: win ? 'rgba(74,223,106,0.03)' : 'rgba(255,107,107,0.05)',
            fontSize: 11,
          }}>
            <span style={{ fontFamily: mono, fontSize: 9, color: COLORS.muted, width: 70 }}>
              {date.slice(5)}
            </span>
            <span style={{
              fontFamily: mono, fontSize: 9, fontWeight: 700, width: 14, textAlign: 'center',
              color: locColor(loc),
            }}>
              {locLabel(loc)}
            </span>
            <span style={{
              fontFamily: mono, fontSize: 11, fontWeight: 700, width: 16,
              color: win ? COLORS.green : COLORS.red,
            }}>
              {win ? 'W' : 'L'}
            </span>
            <span style={{ flex: 1, color: inBracket ? '#fff' : COLORS.muted }}>
              {seed && <span style={{
                fontFamily: mono, fontSize: 9, color: COLORS.gold, fontWeight: 700, marginRight: 4,
              }}>({seed})</span>}
              {opp}
              {inBracket && <span style={{
                fontSize: 7, fontFamily: mono, color: COLORS.accent, marginLeft: 4,
                padding: '0 3px', background: `${COLORS.accent}15`, borderRadius: 2,
              }}>BRACKET</span>}
            </span>
            <span style={{ fontFamily: mono, fontSize: 10, color: COLORS.muted, width: 42, textAlign: 'right' }}>
              {g.team_game_score}-{g.opp_team_game_score}
            </span>
            <span style={{
              fontFamily: mono, fontSize: 10, fontWeight: 600, width: 36, textAlign: 'right',
              color: margin > 0 ? COLORS.green : margin < -10 ? COLORS.red : '#e88',
            }}>
              {margin > 0 ? '+' : ''}{margin}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Head to Head View ─────────────────────────────────────
function HeadToHeadView({ teamsData, scaling, initialTeamA, initialTeamB }) {
  const [teamAName, setTeamAName] = useState(initialTeamA || '');
  const [teamBName, setTeamBName] = useState(initialTeamB || '');
  const [matchupData, setMatchupData] = useState(null);
  const [gamesA, setGamesA] = useState(null);
  const [gamesB, setGamesB] = useState(null);
  const [filterA, setFilterA] = useState('');
  const [filterB, setFilterB] = useState('');

  // Update selections when initial props change (from bracket H2H button)
  useEffect(() => {
    if (initialTeamA) setTeamAName(initialTeamA);
    if (initialTeamB) setTeamBName(initialTeamB);
  }, [initialTeamA, initialTeamB]);

  // Sort teams by seed then name
  const teamList = Object.values(teamsData).sort((a, b) => a.seed - b.seed || a.name.localeCompare(b.name));

  // Auto-fetch matchup when both selected
  useEffect(() => {
    if (!teamAName || !teamBName || teamAName === teamBName) {
      setMatchupData(null);
      return;
    }
    let cancelled = false;
    api.matchup(teamAName, teamBName, 'r64', scaling).then(data => {
      if (!cancelled) setMatchupData(data);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [teamAName, teamBName, scaling]);

  // Fetch games for each team
  useEffect(() => {
    if (!teamAName) { setGamesA(null); return; }
    let cancelled = false;
    api.getTeamGames(teamAName).then(data => {
      if (!cancelled) setGamesA(data);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [teamAName]);

  useEffect(() => {
    if (!teamBName) { setGamesB(null); return; }
    let cancelled = false;
    api.getTeamGames(teamBName).then(data => {
      if (!cancelled) setGamesB(data);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [teamBName]);

  const teamA = teamsData[teamAName];
  const teamB = teamsData[teamBName];

  const selectStyle = {
    flex: 1, minWidth: 200, padding: '10px 12px', borderRadius: 6,
    border: `1px solid ${COLORS.border}`, background: 'rgba(255,255,255,0.05)',
    color: COLORS.text, fontSize: 13, fontFamily: body,
  };
  const searchStyle = {
    width: '100%', padding: '6px 10px', borderRadius: 4, marginBottom: 4,
    border: `1px solid ${COLORS.border}`, background: 'rgba(255,255,255,0.03)',
    color: COLORS.text, fontSize: 11, fontFamily: mono,
  };

  const filteredA = teamList.filter(t => !filterA || t.name.toLowerCase().includes(filterA.toLowerCase()));
  const filteredB = teamList.filter(t => !filterB || t.name.toLowerCase().includes(filterB.toLowerCase()));

  return (
    <div style={{ padding: '16px 24px 48px' }}>
      {/* Team Pickers */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 20, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontFamily: mono, fontSize: 9, color: COLORS.accent, letterSpacing: 1, marginBottom: 4 }}>TEAM A</div>
          <input placeholder="Search teams..." value={filterA} onChange={e => setFilterA(e.target.value)} style={searchStyle} />
          <select value={teamAName} onChange={e => { setTeamAName(e.target.value); setFilterA(''); }} style={selectStyle} size={1}>
            <option value="">Select team...</option>
            {filteredA.map(t => (
              <option key={t.name} value={t.name}>({t.seed}) {t.name} — {t.region}</option>
            ))}
          </select>
        </div>
        <div style={{
          fontFamily: display, fontSize: 22, color: COLORS.muted, alignSelf: 'center',
          letterSpacing: 3, padding: '20px 8px 0',
        }}>VS</div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontFamily: mono, fontSize: 9, color: COLORS.gold, letterSpacing: 1, marginBottom: 4 }}>TEAM B</div>
          <input placeholder="Search teams..." value={filterB} onChange={e => setFilterB(e.target.value)} style={searchStyle} />
          <select value={teamBName} onChange={e => { setTeamBName(e.target.value); setFilterB(''); }} style={selectStyle} size={1}>
            <option value="">Select team...</option>
            {filteredB.map(t => (
              <option key={t.name} value={t.name}>({t.seed}) {t.name} — {t.region}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Matchup Result Panel */}
      {matchupData && teamA && teamB && (
        <>
          {/* Win Probability Bar */}
          <div style={{
            ...styles.card, padding: '16px 20px', marginBottom: 16,
            background: 'rgba(255,255,255,0.03)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <span style={{ fontFamily: display, fontSize: 16, color: COLORS.accent, letterSpacing: 1 }}>
                ({teamA.seed}) {teamAName}
              </span>
              <span style={{ fontFamily: display, fontSize: 16, color: COLORS.gold, letterSpacing: 1 }}>
                ({teamB.seed}) {teamBName}
              </span>
            </div>
            {/* Prob bar */}
            <div style={{ display: 'flex', height: 32, borderRadius: 6, overflow: 'hidden', marginBottom: 8 }}>
              <div style={{
                width: `${matchupData.win_prob_a}%`, background: COLORS.accent,
                display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'width 0.4s',
              }}>
                <span style={{ fontFamily: mono, fontSize: 14, fontWeight: 700, color: '#fff' }}>
                  {matchupData.win_prob_a}%
                </span>
              </div>
              <div style={{
                width: `${matchupData.win_prob_b}%`, background: COLORS.gold,
                display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'width 0.4s',
              }}>
                <span style={{ fontFamily: mono, fontSize: 14, fontWeight: 700, color: '#000' }}>
                  {matchupData.win_prob_b}%
                </span>
              </div>
            </div>
            {/* Predicted Score & Style */}
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: mono, fontSize: 11 }}>
              <span style={{ color: COLORS.muted }}>
                Predicted: <span style={{ color: COLORS.text }}>{matchupData.predicted_score_a}</span>
                {' - '}
                <span style={{ color: COLORS.text }}>{matchupData.predicted_score_b}</span>
              </span>
              <span style={{ color: COLORS.muted }}>
                Style: <span style={{ color: COLORS.accent }}>{matchupData.style_a}</span>
                {' vs '}
                <span style={{ color: COLORS.gold }}>{matchupData.style_b}</span>
              </span>
            </div>
          </div>

          {/* Radar Chart */}
          <div style={{ ...styles.card, padding: '16px 20px', marginBottom: 16 }}>
            <div style={{ fontFamily: display, fontSize: 12, letterSpacing: 2, color: COLORS.muted, marginBottom: 8, textAlign: 'center' }}>
              SIX FACTORS COMPARISON
            </div>
            <RadarChart teamA={teamA} teamB={teamB} teamAName={teamAName} teamBName={teamBName} allTeams={teamsData} />
          </div>

          {/* Stat Comparison Table */}
          <div style={{ ...styles.card, padding: 0, overflow: 'hidden', marginBottom: 16 }}>
            <div style={{
              fontFamily: display, fontSize: 12, letterSpacing: 2, color: COLORS.muted,
              padding: '12px 12px 8px', borderBottom: `1px solid ${COLORS.border}`,
            }}>
              STAT COMPARISON
            </div>
            <StatComparisonTable teamA={teamA} teamB={teamB} nameA={teamAName} nameB={teamBName} />
          </div>

          {/* Margin Distributions */}
          <div style={{ ...styles.card, padding: '16px 20px', marginBottom: 16 }}>
            <div style={{ fontFamily: display, fontSize: 12, letterSpacing: 2, color: COLORS.muted, marginBottom: 12, textAlign: 'center' }}>
              SCORING DISTRIBUTIONS
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', justifyContent: 'center' }}>
              {gamesA && <MarginDistChart teamName={teamAName} margins={gamesA.margins} color={COLORS.accent} />}
              {gamesB && <MarginDistChart teamName={teamBName} margins={gamesB.margins} color={COLORS.gold} />}
            </div>
          </div>

          {/* Last 10 Games */}
          <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
            <div style={{ ...styles.card, flex: 1, minWidth: 300, padding: 0, overflow: 'hidden' }}>
              <div style={{
                fontFamily: display, fontSize: 12, letterSpacing: 2, color: COLORS.accent,
                padding: '10px 12px', borderBottom: `1px solid ${COLORS.border}`,
              }}>
                {teamAName} — LAST 10
              </div>
              {gamesA && <GameLog title="" games={[...gamesA.last_10].reverse()} color={COLORS.accent} />}
            </div>
            <div style={{ ...styles.card, flex: 1, minWidth: 300, padding: 0, overflow: 'hidden' }}>
              <div style={{
                fontFamily: display, fontSize: 12, letterSpacing: 2, color: COLORS.gold,
                padding: '10px 12px', borderBottom: `1px solid ${COLORS.border}`,
              }}>
                {teamBName} — LAST 10
              </div>
              {gamesB && <GameLog title="" games={[...gamesB.last_10].reverse()} color={COLORS.gold} />}
            </div>
          </div>

          {/* All Losses */}
          <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
            <div style={{ ...styles.card, flex: 1, minWidth: 300, padding: 0, overflow: 'hidden' }}>
              {gamesA && <GameLog title={`${teamAName} — ALL LOSSES`} games={gamesA.losses} color={COLORS.red} />}
            </div>
            <div style={{ ...styles.card, flex: 1, minWidth: 300, padding: 0, overflow: 'hidden' }}>
              {gamesB && <GameLog title={`${teamBName} — ALL LOSSES`} games={gamesB.losses} color={COLORS.red} />}
            </div>
          </div>
        </>
      )}

      {/* Empty state */}
      {(!teamAName || !teamBName || teamAName === teamBName) && (
        <div style={{ textAlign: 'center', padding: 48, opacity: 0.3, fontFamily: mono, fontSize: 13 }}>
          {teamAName === teamBName && teamAName ? 'Select two different teams' : 'Select two teams to compare'}
        </div>
      )}
    </div>
  );
}

// ── Main App ─────────────────────────────────────────────
export default function App() {
  const [view, setView] = useState('bracket');
  const [activeRound, setActiveRound] = useState('R64');
  const [simCount, setSimCount] = useState(10000);
  const [scaling, setScaling] = useState(11.0);
  const [loading, setLoading] = useState(false);
  const [simData, setSimData] = useState(null);
  const [adjustments, setAdjustments] = useState({});
  const [bracket, setBracket] = useState(null);
  const [teamsData, setTeamsData] = useState({});
  const [picks, setPicks] = useState({});
  const [error, setError] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [h2hTeamA, setH2hTeamA] = useState('');
  const [h2hTeamB, setH2hTeamB] = useState('');
  const simTimer = useRef(null);

  const goToH2H = useCallback((teamA, teamB) => {
    setH2hTeamA(teamA);
    setH2hTeamB(teamB);
    setView('h2h');
  }, []);

  // Load initial data
  useEffect(() => {
    (async () => {
      try {
        const [adjRes, bracketRes, teamsRes] = await Promise.all([
          api.getAdjustments(),
          api.getBracket(),
          api.getTeams(),
        ]);
        setAdjustments(adjRes.adjustments);
        setBracket(bracketRes.bracket);
        const td = {};
        for (const t of teamsRes.teams) { td[t.name] = t; }
        setTeamsData(td);

        // Auto-run initial simulation
        setLoading(true);
        const data = await api.simulate(simCount, {}, scaling);
        setSimData(data);
        setLoading(false);
      } catch (e) {
        setError(e.message);
        setLoading(false);
      }
    })();
  }, []);

  // Re-simulate when picks change (debounced)
  const runSimWithPicks = useCallback(async (currentPicks) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.simulate(simCount, currentPicks, scaling);
      setSimData(data);
      setRefreshKey(k => k + 1);
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  }, [simCount, scaling]);

  const handlePick = useCallback((key, team) => {
    setPicks(prev => {
      const next = { ...prev };
      // Toggle: if already picked, un-pick and clear downstream
      if (next[key] === team) {
        delete next[key];
        // Clear any downstream picks that depended on this
        clearDownstream(next, key);
      } else {
        // If changing pick, clear downstream of old pick
        if (next[key]) {
          clearDownstream(next, key);
        }
        next[key] = team;
      }

      // Debounce re-sim
      clearTimeout(simTimer.current);
      simTimer.current = setTimeout(() => runSimWithPicks(next), 400);

      return next;
    });
  }, [runSimWithPicks]);

  const clearDownstream = (picksObj, changedKey) => {
    // When a pick changes, remove all picks that depend on it downstream
    // This is brute-force but correct: rebuild matchups and check what's invalidated
    const keysToCheck = Object.keys(picksObj);
    let changed = true;
    while (changed) {
      changed = false;
      for (const k of keysToCheck) {
        if (!picksObj[k]) continue;
        const picked = picksObj[k];
        // Check if this picked team could still be in this matchup
        // by verifying it was picked in a prior round
        // Simple approach: just clear all rounds after the changed round
        const changedRound = changedKey.split('-')[0];
        const thisRound = k.split('-')[0];
        const roundOrder = { R64: 0, R32: 1, S16: 2, E8: 3, F4: 4, FINAL: 5 };
        if (roundOrder[thisRound] > roundOrder[changedRound]) {
          // Check if the picked team in this game came through the changed path
          // For simplicity, just clear if it matches the team that was un/re-picked
          // Actually let's be more aggressive: clear everything downstream
          delete picksObj[k];
          changed = true;
        }
      }
    }
  };

  const clearAllPicks = () => {
    setPicks({});
    clearTimeout(simTimer.current);
    simTimer.current = setTimeout(() => runSimWithPicks({}), 200);
  };

  const handleUpdateAdj = async (team, factor, note) => {
    try {
      await api.updateAdjustment(team, factor, note);
      const d = await api.getAdjustments();
      setAdjustments(d.adjustments);
    } catch (e) { setError(e.message); }
  };

  const handleRemoveAdj = async (team) => {
    try {
      await api.removeAdjustment(team);
      const d = await api.getAdjustments();
      setAdjustments(d.adjustments);
    } catch (e) { setError(e.message); }
  };

  // Build all round matchups from bracket + picks
  const allMatchups = bracket ? buildMatchups(bracket, picks, teamsData) : null;
  const currentRoundMatchups = allMatchups?.[activeRound];
  const pickCount = Object.keys(picks).length;
  const totalGames = 63;
  const champion = picks['FINAL-0'] || null;

  const roundLabelsShort = { R64: 'R64', R32: 'R32', S16: 'S16', E8: 'E8', F4: 'F4', FINAL: 'FINAL' };
  const roundsForTable = ['r64', 'r32', 's16', 'e8', 'f4', 'champion'];
  const roundLabelsForTable = { r64: 'R64', r32: 'R32', s16: 'S16', e8: 'E8', f4: 'F4', champion: 'W' };

  // Count picks per round
  const picksPerRound = {};
  for (const k of Object.keys(picks)) {
    const r = k.split('-')[0];
    picksPerRound[r] = (picksPerRound[r] || 0) + 1;
  }
  const gamesPerRound = { R64: 32, R32: 16, S16: 8, E8: 4, F4: 2, FINAL: 1 };

  return (
    <div style={styles.app}>
      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.title}>BRACKET SIMULATOR</h1>
        <div style={styles.subtitle}>EFFICIENCY-MARGIN MODEL — MONTE CARLO SIMULATION — 2026 NCAA TOURNAMENT</div>
      </div>

      {/* Nav */}
      <div style={styles.nav}>
        {['bracket', 'rankings', 'h2h', 'adjustments'].map(v => (
          <button key={v} onClick={() => setView(v)} style={styles.navBtn(view === v)}>
            {v === 'bracket' ? 'PICK YOUR BRACKET' : v === 'rankings' ? 'CHAMPIONSHIP ODDS' : v === 'h2h' ? 'HEAD TO HEAD' : 'ADJUSTMENTS'}
          </button>
        ))}
      </div>

      {/* Controls */}
      <div style={styles.controls}>
        <span style={styles.scalingLabel}>SIMS:</span>
        {[1000, 10000, 50000].map(n => (
          <button key={n} onClick={() => setSimCount(n)} style={styles.countBtn(simCount === n)}>
            {n >= 1000 ? `${n / 1000}K` : n}
          </button>
        ))}
        <span style={{ ...styles.scalingLabel, marginLeft: 8 }}>CHAOS:</span>
        <input type="range" min="9" max="14" step="0.5" value={scaling}
          onChange={e => setScaling(parseFloat(e.target.value))} style={styles.slider} />
        <span style={{ fontFamily: mono, fontSize: 11, color: COLORS.accent, minWidth: 30 }}>{scaling}</span>
        <span style={{ fontSize: 9, opacity: 0.3, fontFamily: mono }}>
          {scaling <= 10 ? 'CHALK' : scaling <= 11.5 ? 'NORMAL' : 'MADNESS'}
        </span>
        <button onClick={() => runSimWithPicks(picks)} disabled={loading} style={styles.simBtn(loading)}>
          {loading ? 'SIMULATING...' : 'RE-SIMULATE'}
        </button>
        {pickCount > 0 && (
          <>
            <span style={{ fontFamily: mono, fontSize: 10, color: COLORS.green }}>
              {pickCount}/{totalGames} picks
            </span>
            <button onClick={clearAllPicks} style={{
              padding: '4px 10px', borderRadius: 4, border: `1px solid ${COLORS.red}44`,
              background: 'transparent', color: COLORS.red, fontSize: 10, fontFamily: mono, cursor: 'pointer',
            }}>RESET</button>
          </>
        )}
        {loading && (
          <span style={{ fontSize: 10, fontFamily: mono, color: COLORS.muted }}>updating...</span>
        )}
      </div>

      {error && (
        <div style={{ padding: '12px 24px', background: 'rgba(255,100,100,0.1)', color: COLORS.red, fontSize: 12 }}>
          {error}
        </div>
      )}

      {/* Bracket View */}
      {view === 'bracket' && allMatchups && (
        <>
          {champion && <ChampionBanner team={champion} seed={teamsData[champion]?.seed} teamsData={teamsData} />}

          {/* Round tabs */}
          <div style={{ display: 'flex', borderBottom: `1px solid ${COLORS.border}` }}>
            {ROUNDS.map(r => {
              const done = (picksPerRound[r] || 0) >= gamesPerRound[r];
              const partial = (picksPerRound[r] || 0) > 0 && !done;
              return (
                <button key={r} onClick={() => setActiveRound(r)} style={{
                  flex: 1, padding: '10px 4px', border: 'none',
                  borderBottom: activeRound === r ? `3px solid ${COLORS.accent}` : '3px solid transparent',
                  background: activeRound === r ? `${COLORS.accent}15` : 'transparent',
                  color: activeRound === r ? COLORS.accent : done ? COLORS.green : partial ? COLORS.gold : COLORS.muted,
                  fontFamily: display, fontSize: 11, letterSpacing: 1.5, cursor: 'pointer',
                }}>
                  {roundLabelsShort[r]}
                  <span style={{ fontSize: 9, fontFamily: mono, marginLeft: 4, opacity: 0.6 }}>
                    {picksPerRound[r] || 0}/{gamesPerRound[r]}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Matchups for current round */}
          <div style={{ padding: '12px 16px 32px' }}>
            {currentRoundMatchups && Object.entries(currentRoundMatchups).map(([groupName, matchups]) => (
              <div key={groupName}>
                {(activeRound !== 'F4' && activeRound !== 'FINAL') && (
                  <div style={{
                    fontFamily: display, fontSize: 12, letterSpacing: 2, marginBottom: 8, marginTop: 12,
                    color: COLORS.regions[groupName] || COLORS.gold,
                  }}>
                    {groupName.toUpperCase()} — {ROUND_LABELS[activeRound]}
                  </div>
                )}
                {(activeRound === 'F4' || activeRound === 'FINAL') && (
                  <div style={{
                    fontFamily: display, fontSize: 14, letterSpacing: 2, marginBottom: 12, marginTop: 12,
                    color: COLORS.gold, textAlign: 'center',
                  }}>
                    {ROUND_LABELS[activeRound]}
                  </div>
                )}
                {matchups.map((m, i) => (
                  <InteractiveMatchupCard
                    key={m.key}
                    matchup={m}
                    picked={picks[m.key]}
                    onPick={handlePick}
                    color={COLORS.regions[groupName] || COLORS.gold}
                    scaling={scaling}
                    refreshKey={refreshKey}
                    onH2H={goToH2H}
                  />
                ))}
              </div>
            ))}
          </div>
        </>
      )}

      {/* Rankings View */}
      {view === 'rankings' && (
        <div style={{ padding: '16px 16px 32px' }}>
          {simData ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <span style={{ fontFamily: display, fontSize: 14, letterSpacing: 2, color: COLORS.gold }}>
                  ROUND-BY-ROUND PROBABILITIES
                </span>
                {pickCount > 0 && (
                  <span style={{ fontFamily: mono, fontSize: 10, color: COLORS.accent }}>
                    (with {pickCount} locked picks)
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px', marginBottom: 4 }}>
                <span style={{ width: 22 }} />
                <span style={{ width: 18 }} />
                <span style={{ flex: 1, fontSize: 9, fontFamily: mono, opacity: 0.3 }}>TEAM</span>
                <span style={{ width: 52 }} />
                {roundsForTable.map(r => (
                  <span key={r} style={{ fontFamily: mono, fontSize: 9, width: 42, textAlign: 'right', opacity: 0.4 }}>
                    {roundLabelsForTable[r]}
                  </span>
                ))}
              </div>
              {simData.results.filter(t => t.champion > 0 || t.f4 > 0.5).map((team, i) => (
                <TeamRow key={team.team} team={team} index={i} rounds={roundsForTable} />
              ))}
              <div style={{ marginTop: 20, padding: 14, background: 'rgba(255,255,255,0.02)', borderRadius: 8, border: `1px solid ${COLORS.border}` }}>
                <div style={{ fontSize: 10, fontFamily: mono, opacity: 0.35, letterSpacing: 1, marginBottom: 6 }}>MODEL INFO</div>
                <div style={{ fontSize: 11, lineHeight: 1.7, opacity: 0.5 }}>
                  Win prob = logistic(delta-EM / scaling). Scaling {simData.scaling_factor} (lower = more chalk, higher = more upsets).
                  {' '}Adjustments applied to {Object.keys(adjustments).length} teams. Does not model matchup-specific styles, travel, or crowd effects.
                </div>
              </div>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: 48, opacity: 0.4 }}>
              Run a simulation to see championship probabilities
            </div>
          )}
        </div>
      )}

      {/* Head to Head View */}
      {view === 'h2h' && Object.keys(teamsData).length > 0 && (
        <HeadToHeadView teamsData={teamsData} scaling={scaling} initialTeamA={h2hTeamA} initialTeamB={h2hTeamB} />
      )}

      {/* Adjustments View */}
      {view === 'adjustments' && (
        <AdjustmentsPanel adjustments={adjustments} onUpdate={handleUpdateAdj} onRemove={handleRemoveAdj} />
      )}
    </div>
  );
}
