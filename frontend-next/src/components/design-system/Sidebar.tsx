"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavItem {
  href: string;
  icon: string;
  label: string;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: "Core Platform",
    items: [
      { href: "/jarvis", icon: "🧠", label: "Jarvis / MOA" },
      { href: "/incidents", icon: "🚨", label: "Incidents" },
      { href: "/executive/enterprise", icon: "📊", label: "Executive" },
    ],
  },
  {
    title: "Governance & Platform",
    items: [
      { href: "/governance", icon: "🛡️", label: "Governance" },
      { href: "/capability-onboarding", icon: "🚀", label: "BYOC Studio" },
      { href: "/integrations", icon: "🔌", label: "Integrations" },
      { href: "/memory", icon: "💾", label: "Memory" },
      { href: "/settings", icon: "🔑", label: "Settings" },
    ],
  },
  {
    title: "Operations Pod",
    items: [
      { href: "/digital-twin", icon: "🏭", label: "Twin Room" },
      { href: "/knowledge", icon: "🕸️", label: "Knowledge Graph" },
      { href: "/decisions", icon: "⚖️", label: "Decisions & Replay" },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <nav className="flex w-52 shrink-0 flex-col gap-4 border-r border-purple-500/20 bg-[#08051a]/60 backdrop-blur-xl px-3 py-6 relative z-20 shadow-2xl font-unbounded overflow-y-auto">
      {NAV_SECTIONS.map((section) => (
        <div key={section.title} className="space-y-1">
          <div className="px-3 pb-1">
            <span className="text-[10px] tracking-wider text-purple-300/50 uppercase block font-bold">
              {section.title}
            </span>
          </div>

          {section.items.map((item) => {
            const active = pathname?.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-xl px-3.5 py-2 text-xs transition-all flex items-center justify-between group ${
                  active
                    ? "bg-gradient-to-r from-purple-900/60 to-pink-900/40 text-white border border-pink-500/40 shadow-lg shadow-pink-500/10 font-bold"
                    : "text-purple-200/70 hover:text-white hover:bg-purple-950/40 border border-transparent hover:border-purple-500/30"
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <span className="text-sm group-hover:scale-110 transition-transform">{item.icon}</span>
                  <span className="font-medium">{item.label}</span>
                </div>
                {active && (
                  <span className="w-1.5 h-1.5 rounded-full bg-pink-400 animate-pulse shadow-[0_0_8px_#ec4899]" />
                )}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}


