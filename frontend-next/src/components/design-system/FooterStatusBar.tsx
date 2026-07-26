// documentation/04_Demo_UI_Architecture.md section 2 - FooterStatusBar.
// Static connector labels for now - Phase 5B's Integration Monitor (/integrations)
// is where live connector health actually gets wired up.

export function FooterStatusBar() {
  return (
    <footer className="flex items-center gap-6 border-t border-border-subtle bg-card px-6 py-2 text-xs text-text-secondary">
      <span>Agent Swarm: 8 Active</span>
      <span>watsonx ITSM: Connected</span>
      <span>SAP ERP: Connected</span>
    </footer>
  );
}
