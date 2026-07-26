// documentation/03_Design_System.md section 5.1 - Stat KPI Card (Glassmorphic Metric Tile)

type AccentColor = "emerald" | "status-red" | "cobalt" | "amber" | "purple";

// Static, literal class names - Tailwind's scanner can't see through
// runtime template-literal interpolation like `text-${accentColor}`, it
// only detects class names that appear verbatim in source.
const ACCENT_TEXT_CLASS: Record<AccentColor, string> = {
  emerald: "text-emerald",
  "status-red": "text-status-red",
  cobalt: "text-cobalt",
  amber: "text-amber",
  purple: "text-purple",
};

interface KpiCardProps {
  label: string;
  value: string;
  trend?: string;
  accentColor?: AccentColor;
}

export function KpiCard({ label, value, trend, accentColor = "emerald" }: KpiCardProps) {
  return (
    <div className="rounded-lg border border-border-subtle bg-glass px-5 py-4 shadow-[0_4px_20px_rgba(0,0,0,0.4)] backdrop-blur-md">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${ACCENT_TEXT_CLASS[accentColor]}`}>{value}</div>
      {trend && <div className="mt-1 text-xs text-text-secondary">{trend}</div>}
    </div>
  );
}
