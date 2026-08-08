## Variant: Fintech Light

**Design stance**
Tokens are money — so treat the tracking like a Stripe billing dashboard: pure white canvas, weight-300 elegance, deep navy headings, purple CTA, blue-tinted shadows. The budget/forecast framing is the entire product.

### Key choices
- Layout: marketing-style top nav, hero "balance card" ($84.19 spend), animated budget ring, daily spend chart, model split, sessions table with status filter, dark indigo insight band
- Typography: Source Sans 3 at weight 300 (Stripe's signature), Source Code Pro for IDs, tabular numerals everywhere money is shown
- Color: navy `#061b31`, Stripe purple `#533afd`, green success, ruby/magenta decorative
- Interaction: period toggle re-renders chart, session status filter, animated ring on load (56%), toast banner replaces inline on CTA clicks

### Trade-offs
- Strong at: instant "am I on budget?" read from the hero; premium feel; the money metaphor lands immediately
- Weak at: granular technical detail (message-level, per-model costs get pushed down); darker theme lovers

### Best for
- The user who cares about *cost* first and wants one glance at burn rate + headroom before the first coffee — plus anyone who'll have to show this to a non-engineer