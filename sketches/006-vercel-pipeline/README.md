## Variant: Pipeline (Vercel)

### Design stance
Token usage as a deployment pipeline: Develop (input) → Preview (reasoning) → Ship (output), each stage wearing Vercel's workflow colors. Monochrome precision on white, Geist's aggressive negative tracking, and shadow-as-border instead of CSS borders. If you deploy code, you'll read this dashboard instantly.

### Key choices
- Layout: pipeline strip front and center (3 stages with live share bars), metric cards, sessions as a deploy-style table with Ready/Building/Error pills, budget panel
- Typography: Geist — 48px/-2.4px display head, -1.28px at 32px, -0.96px at 24px; Geist Mono uppercase technical labels
- Color: `#171717` on pure white, shadow-borders `rgba(0,0,0,0.08) 0 0 0 1px`, workflow accents (dev blue / preview pink / ship red) as *semantic labels*, not decorations
- Structure: cards get the full Vercel 4-layer shadow stack (border + soft + ambient + inner `#fafafa` glow)
- Interaction: range pill recalculates pipeline shares live, status filters, row click toast

### Trade-offs
- Strong at: the "where do tokens go" story is told once, perfectly; light theme reads calm and premium
- Weak at: no per-message detail; pipeline metaphor forces a 3-part model of usage that may not match real sessions

### Best for
Sole-operator devs who want the cleanest possible spend story, and teams that already speak Vercel