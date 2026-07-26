// documentation/03_Design_System.md section 6 - pulse-emerald/pulse-red
// keyframes (globals.css), used for live line/incident status badges.

interface StatusPulseProps {
  status: "healthy" | "critical";
  label: string;
}

export function StatusPulse({ status, label }: StatusPulseProps) {
  const dotClass = status === "healthy" ? "bg-emerald status-active-green" : "bg-status-red status-incident-red";
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className={`h-2.5 w-2.5 rounded-full ${dotClass}`} />
      {label}
    </span>
  );
}
