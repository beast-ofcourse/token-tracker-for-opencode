## Variant: Incident Room (Sentry)

### Design stance
Stop thinking of sessions as rows — think of them as incidents. Deep purple-black canvas, uppercase technical labels, lime-green "resolve" accents and glowing severity dots. You triage token spend the same way Sentry triages crashes: what's expensive, why, and what needs attention.

### Key choices
- Layout: left project rail (opensource / quanta-cli / quantum-app) + incident stream ordered by cost
- Typography: Rubik with 4-tier weights (400/500/600/700), uppercase + 0.2px letter-spacing labels everywhere (signature Sentry pattern); JetBrains Mono for IDs/token counts
- Color: `#1f1633` / `#150f23` purple-blacks, `#6a5fc1` interactive, `#c2ef4e` lime used once per section
- Interaction: severity filter chips (all/high/med/low), click-to-expand incident details showing per-message token breakdown, overlay toasts, inset-shadow buttons

### Trade-offs
- Strong at: making spend anomalies feel urgent and actionable; message-level drilldown is the deepest of the three
- Weak at: a user who just wants "the number" has to scan; severity taxonomy is a metaphor you must buy into

### Best for
- Power users who want spend anomalies surfaced aggressively, with per-message forensic detail