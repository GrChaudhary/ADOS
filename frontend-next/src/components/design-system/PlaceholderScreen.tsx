// Trivial placeholder for the 5 screens Phase 5B owns - see
// docs/PHASE5B_ANTIGRAVITY_HANDOFF.md. Uses the same shell/design tokens
// as the real screens so the extension point is a working page, not just
// a route name.

interface PlaceholderScreenProps {
  title: string;
  routeDoc: string;
}

export function PlaceholderScreen({ title, routeDoc }: PlaceholderScreenProps) {
  return (
    <div className="rounded-lg border border-border-subtle bg-card p-8 text-center">
      <h1 className="text-xl font-semibold text-text-primary">{title}</h1>
      <p className="mt-2 text-sm text-text-secondary">
        Phase 5B — not yet built. Spec: {routeDoc}
      </p>
    </div>
  );
}
