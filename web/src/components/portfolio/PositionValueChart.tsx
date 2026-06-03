type Point = { as_of: string; market_value: number };

function parseTime(iso: string): number {
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? Date.now() : t;
}

function formatLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(5, 10);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function computeYScale(values: number[]) {
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  let dataSpan = dataMax - dataMin;

  let minV: number;
  let maxV: number;

  if (dataSpan === 0) {
    const mid = dataMin;
    const cushion = Math.max(mid * 0.005, 2);
    minV = mid - cushion;
    maxV = mid + cushion;
  } else {
    const pad = Math.max(dataSpan * 0.1, 0.01);
    minV = dataMin - pad;
    maxV = dataMax + pad;
  }

  const span = maxV - minV;
  const decimals = span >= 200 ? 0 : span >= 20 ? 1 : 2;
  const yTicks = [minV, minV + span / 2, maxV];

  const formatValue = (v: number) =>
    `$${v.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })}`;

  return { minV, maxV, span, yTicks, formatValue };
}

export function PositionValueChart({ history }: { history: Point[] }) {
  if (history.length < 2) {
    return (
      <p className="text-sm text-gray-500 py-8 text-center">
        Not enough history to chart this position yet.
      </p>
    );
  }

  const width = 640;
  const height = 240;
  const pad = { top: 16, right: 16, bottom: 32, left: 56 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const times = history.map((p) => parseTime(p.as_of));
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const timeSpan = maxT - minT || 1;

  const values = history.map((p) => p.market_value);
  const { minV, span, yTicks, formatValue } = computeYScale(values);

  const points = history.map((p, i) => {
    const t = times[i];
    const x = pad.left + ((t - minT) / timeSpan) * innerW;
    const y = pad.top + innerH - ((p.market_value - minV) / span) * innerH;
    return { x, y, ...p };
  });

  const labelIndices = (() => {
    const indices = new Set<number>();
    if (history.length <= 7) {
      history.forEach((_, i) => indices.add(i));
      return indices;
    }
    const seen = new Set<string>();
    history.forEach((p, i) => {
      const dayKey = p.as_of.slice(0, 10);
      if (!seen.has(dayKey)) {
        seen.add(dayKey);
        indices.add(i);
      }
    });
    indices.add(0);
    indices.add(history.length - 1);
    return indices;
  })();

  const line = points.map((p) => `${p.x},${p.y}`).join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-60" role="img" aria-label="Position value over time">
      {yTicks.map((v, i) => {
        const y = pad.top + innerH - ((v - minV) / span) * innerH;
        return (
          <g key={i}>
            <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} stroke="#e5e7eb" strokeDasharray="4 4" />
            <text x={pad.left - 8} y={y + 4} textAnchor="end" className="fill-gray-500 text-[10px]">
              {formatValue(v)}
            </text>
          </g>
        );
      })}
      <polyline fill="none" stroke="#3b82f6" strokeWidth={2} points={line} />
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={3} fill="#3b82f6" />
      ))}
      {points.map((p, i) =>
        labelIndices.has(i) ? (
          <text key={`lbl-${i}`} x={p.x} y={height - 8} textAnchor="middle" className="fill-gray-500 text-[10px]">
            {formatLabel(p.as_of)}
          </text>
        ) : null
      )}
    </svg>
  );
}
