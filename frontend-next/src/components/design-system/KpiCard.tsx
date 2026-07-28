type AccentColor = "emerald" | "status-red" | "cobalt" | "amber" | "purple";

const ACCENT_TEXT_CLASS: Record<AccentColor, string> = {
  emerald: "text-emerald-400 drop-shadow-[0_0_12px_rgba(16,185,129,0.5)]",
  "status-red": "text-red-400 drop-shadow-[0_0_12px_rgba(239,68,68,0.5)]",
  cobalt: "text-cyan-400 drop-shadow-[0_0_12px_rgba(6,182,212,0.5)]",
  amber: "text-amber-400 drop-shadow-[0_0_12px_rgba(245,158,11,0.5)]",
  purple: "text-pink-400 drop-shadow-[0_0_12px_rgba(236,72,153,0.5)]",
};

const ACCENT_BORDER_CLASS: Record<AccentColor, string> = {
  emerald: "border-emerald-500/30 hover:border-emerald-500/60",
  "status-red": "border-red-500/30 hover:border-red-500/60",
  cobalt: "border-cyan-500/30 hover:border-cyan-500/60",
  amber: "border-amber-500/30 hover:border-amber-500/60",
  purple: "border-pink-500/30 hover:border-pink-500/60",
};

interface KpiCardProps {
  label: string;
  value: string;
  trend?: string;
  accentColor?: AccentColor;
}

export function KpiCard({ label, value, trend, accentColor = "emerald" }: KpiCardProps) {
  return (
    <div className={`p-5 rounded-2xl jarvis-glass-card border transition-all duration-300 ${ACCENT_BORDER_CLASS[accentColor]}`}>
      <div className="text-xs font-mono uppercase tracking-wider text-purple-300/70">{label}</div>
      <div className={`mt-2 text-2xl font-orbitron font-extrabold ${ACCENT_TEXT_CLASS[accentColor]}`}>{value}</div>
      {trend && <div className="mt-2 text-xs text-purple-200/60 font-sans">{trend}</div>}
    </div>
  );
}

