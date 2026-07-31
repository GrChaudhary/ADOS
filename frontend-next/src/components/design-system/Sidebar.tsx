"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/executive/enterprise", icon: "📊", label: "Executive" },
  { href: "/digital-twin", icon: "🏭", label: "Twin Room" },
  { href: "/incidents", icon: "🚨", label: "Incidents" },
  { href: "/decisions", icon: "⚖️", label: "Decisions" },
  { href: "/knowledge", icon: "🕸️", label: "Knowledge" },
  { href: "/memory", icon: "💾", label: "Memory" },
  { href: "/settings", icon: "🔑", label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <nav className="flex w-52 shrink-0 flex-col gap-1.5 border-r border-purple-500/20 bg-[#08051a]/60 backdrop-blur-xl px-3 py-6 relative z-20 shadow-2xl font-unbounded">
      <div className="px-3 pb-3 border-b border-purple-500/15 mb-2">
        <span className="text-[11px] tracking-wider text-purple-300/50 uppercase block font-bold">
          SYSTEM MODULES
        </span>
      </div>

      {NAV_ITEMS.map((item) => {
        const active = pathname?.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`rounded-xl px-3.5 py-2.5 text-sm transition-all flex items-center justify-between group ${
              active
                ? "bg-gradient-to-r from-purple-900/60 to-pink-900/40 text-white border border-pink-500/40 shadow-lg shadow-pink-500/10 font-bold"
                : "text-purple-200/70 hover:text-white hover:bg-purple-950/40 border border-transparent hover:border-purple-500/30"
            }`}
          >
            <div className="flex items-center gap-2.5">
              <span className="text-base group-hover:scale-110 transition-transform">{item.icon}</span>
              <span className="font-medium">{item.label}</span>
            </div>
            {active && (
              <span className="w-1.5 h-1.5 rounded-full bg-pink-400 animate-pulse shadow-[0_0_8px_#ec4899]" />
            )}
          </Link>
        );
      })}
    </nav>
  );
}

