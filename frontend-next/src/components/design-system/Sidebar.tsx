// documentation/04_Demo_UI_Architecture.md section 2 - SidebarNavigation.
// Screens marked (Phase 5B) are placeholder routes today - see
// docs/PHASE5B_ANTIGRAVITY_HANDOFF.md.

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/executive/enterprise", icon: "📊", label: "Executive" },
  { href: "/digital-twin", icon: "🏭", label: "Twin Room" },
  { href: "/incidents", icon: "🚨", label: "Incidents" },
  { href: "/decisions", icon: "⚖️", label: "Decisions" },
  { href: "/knowledge", icon: "🕸️", label: "Knowledge" },
  { href: "/agents/network", icon: "🧠", label: "Agents" },
  { href: "/memory", icon: "💾", label: "Memory" },
  { href: "/governance", icon: "🛡️", label: "Autonomy" },
  { href: "/integrations", icon: "🔌", label: "Hub" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <nav className="flex w-48 shrink-0 flex-col gap-1 border-r border-border-subtle bg-card px-3 py-4">
      {NAV_ITEMS.map((item) => {
        const active = pathname?.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`rounded-md px-3 py-2 text-sm ${
              active ? "bg-glass text-text-primary" : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <span className="mr-2">{item.icon}</span>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
