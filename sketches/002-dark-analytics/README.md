## Variant: Dark Analytics

**Design stance**
A Linear-grade analytics product: near-black `#08090a`, precision Inter with Linear's OpenType features, translucent surfaces, and a single reserved indigo accent — the tool-first dashboard for power users who want the deepest signal density.

### Key choices
- Layout: fixed sidebar nav (Overview/Usage/Sessions/Budget/Models), content column with 4 stat cards, SVG bar chart, session list, budget panel
- Typography: Inter at Linear weights (400/510/500), JetBrains Mono for IDs
- Color: achromatic darks; `#5e6ad2`/`#7170ff` only for interactive accents; green/amber/red status only
- Interaction: 7d/14d/30d range switch re-renders the chart live; sidebar view switching (mock); export/alert toasts; hover tooltips on bars

### Trade-offs
- Strong at: feeling like a serious, precise internal tool; density with hierarchy; scalable nav
- Weak at: first-glance "how am I doing?" (fragmentation; budget truth splits into a panel)

### Best for
- The user who wants a full product: nav, views, alerts, export — a dashboard they'd build into their app