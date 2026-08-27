# Local SEO Spider — Design Direction

## Three directions considered

### Field Manual
**Very Brief Intro:** An editorial technical-workbench that makes an audit feel like a purposeful inspection, with high-signal labels, sturdy rules, and a restrained paper-and-ink palette.

**Probability:** 0.06

### Signal Grid
**Very Brief Intro:** A navy-and-steel monitoring room where compact cards and structural alignment foreground operational clarity and scan progress.

**Probability:** 0.03

### Quiet Terminal
**Very Brief Intro:** A softened monochrome console that borrows the focus of a terminal without imitating cyberpunk visual language.

**Probability:** 0.08

## Chosen approach: Field Manual

### Design Movement
**Swiss editorial design meets a technical field notebook.** The crawler should feel like a serious local instrument: calm, precise, and auditable rather than an abstract analytics dashboard.

### Core Principles
1. **Evidence before decoration:** URL facts, severities, and clear next actions are always visually dominant.
2. **Structured asymmetry:** a persistent left rail anchors the workflow while the main canvas holds broad, legible inspection panels.
3. **Measured density:** compact data tables coexist with generous breathing room around major task transitions.
4. **Human-readable machinery:** plain language, numbered sequences, and short labels make technical checks approachable without hiding their detail.

### Color Philosophy
The base is warm paper (`#F7F4EE`) and ink (`#182523`) to evoke a durable inspection ledger. Deep spruce (`#173D3A`) carries confident operational actions; safety amber (`#C96B16`) signals attention without alarmism; brick (`#AF3E37`) is reserved for true blocking problems. The palette communicates local control and calm scrutiny rather than surveillance or growth marketing.

### Layout Paradigm
The primary view uses a **rail-and-ledger** structure: a fixed narrow navigation and crawl-context rail on the left, an offset workbench in the center, and inline evidence drawers in the reading flow. On narrow screens, the rail becomes a top context strip and tables gain horizontal scroll rather than collapsing facts into ambiguous cards.

### Signature Elements
1. **Inspection stamps:** small outlined state labels such as `LOCAL DATA`, `ROBOTS RESPECTED`, and severity tags.
2. **Ledger rules:** thin divider lines with a short index marker to organize panels and table groups.
3. **Crawl trace:** a minimal dotted path motif that marks page queues, progress, and exports.

### Interaction Philosophy
Every action must communicate scope and consequence. Starting a crawl requires an explicit ownership statement and displays the selected URL cap and delay. HTMX updates replace only the relevant audit panel and preserve form context; recoverable failures remain visible with a retry action and their technical detail in an expandable disclosure.

### Animation
Motion is intentionally subtle: panels fade and rise by no more than 8px over 180–240ms with a decisive ease-out; progress is conveyed by an animated crawl trace only while work is active. Severity changes never rely on motion alone. `prefers-reduced-motion` eliminates movement while retaining every state indicator.

### Typography System
**Outfit** provides compact, geometric headings and display numerals. **Work Sans** handles labels, paragraph text, tables, and inputs. Headings use tight tracking and semibold weights; technical values use a system monospace fallback only in evidence snippets, URLs, and status codes. Body text never falls below 14px and table headers use uppercase letterspacing only where labels are short.

### Brand Essence
**A local, evidence-led SEO inspection tool for site owners who need reproducible technical audits without sending crawl data to a cloud platform.**

Personality: **methodical, candid, self-contained**.

### Brand Voice
Headlines are concise and declarative; CTAs name the exact operation; supporting text states scope and safeguards without hype.

Example lines:

> Inspect the site you are authorized to assess.

> Export the evidence, not just the score.

### Wordmark & Logo
The mark is a compact **segmented crawl loop**: three broken concentric path segments that resolve into a magnifying aperture, suggesting a crawl frontier becoming inspection evidence. The wordmark uses a custom-spaced Outfit treatment with a stamped period in the signature spruce.

### Signature Brand Color
**Ledger Spruce — `#173D3A`**.

## Style Decisions

- The dotted crawl trace is a visible recurring navigation and evidence motif: it connects the hero, inspection stages, scope groups, and the crawl ledger.
- The logo remains the segmented crawl-loop magnifying aperture and is served as a first-class brand asset rather than substituted with a generic mark.
- Form panels use named target and boundary record groups with rule-led divisions so they read as inspection ledgers rather than generic SaaS cards.
