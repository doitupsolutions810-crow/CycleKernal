import React from 'react';

export default function ColonyHud({ colony }) {
  const c = colony || {};
  const cards = [
    ['Active', c.active ?? 0],
    ['Promoted', c.promoted ?? 0],
    ['Held', c.held ?? 0],
    ['Dormant', c.dormant ?? 0],
  ];
  return (
    <div className="stats-grid" style={{ marginTop: 16 }}>
      {cards.map(([label, value]) => (
        <div className="stat-card" key={label}>
          <h3>{label}</h3>
          <div className="stat-value">{value}</div>
        </div>
      ))}
      <div className="stat-card" style={{ gridColumn: '1 / -1' }}>
        <h3>Colony genome</h3>
        <div className="stat-value" style={{ fontSize: 18 }}>{c.genome_id || '—'}</div>
      </div>
    </div>
  );
}
