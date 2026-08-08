## Variant: Command Palette (Raycast)

### Design stance
The whole dashboard is a Raycast window: a real macOS titlebar, near-black blue-tint (`#07080a`), and — the centerpiece — a fully working **⌘K command palette**. It's not decoration: press ⌘K (or click the button), type "30d", "export", or "budget", arrow-key through results, hit Enter, and the dashboard actually reacts.

### Key choices
- Layout: macOS window frame around the whole app (traffic lights, titlebar, ⌘K hint), utility-bar top, four stat cards, chart + budget panes, session list
- Typography: Inter with positive letter-spacing (+0.2px) and weight-500 baseline — Raycast's airy dark-mode signature; Geist Mono for IDs; keyboard keycaps with gradient + inset shadows
- Color: `#07080a` bg, `#101111` surfaces, Raycast Red `#FF6363` reserved for hot flags, blue/green for info/success
- Interaction: working command palette, range segmented control, hover = opacity 0.6, macOS-style layered shadows throughout

### Trade-offs
- Strong at: feeling like a *real product* — the palette is a delightful artifact, and every number is readable at a glance
- Weak at: the palette is a feint (underlying views share one screen); light-mode users won't engage

### Best for
- Keyboard-first developers who will actually hit ⌘K; the variant that proves the product's *feel*