## Variant: Terminal Monitor

### Design stance
The dashboard *is* a terminal. Warm near-black `#201d1d` canvas, JetBrains Mono everywhere, flat surfaces with zero shadows — the exact visual language of opencode itself, so the tool feels native to the thing it's tracking.

### Key choices
- Layout: single column, tabbed panels (usage / sessions / budget)
- Typography: JetBrains Mono 100% — no sans-serif voice at all
- Color: warm dark `#201d1d` + off-white `#fdfcfc`, Apple-HIG semantic colors for status
- Interaction: tab switching, model filter chips, click-to-expand session rows revealing message-level token detail; blinking terminal cursor

### Trade-offs
- Strong at: credibility with CLI users; dense data reads like a familiar tool; message-level drill-down
- Weak at: glanceable at-a-glance insight (numbers first, trends second); no chart library sophistication

### Best for
- The developer who lives in the terminal and wants a `req`-style monitor, not a "product dashboard"