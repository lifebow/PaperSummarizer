# The Ledger — feed page redesign

Date: 2026-07-20

## Goal
Recreate the approved design direction **"1a · The Ledger"** (see
`design_handoff_papersummarizer/README.md` and `PaperSummarizer.dc.html`) in the
existing FastAPI + Jinja + Tailwind-CDN web UI. High-fidelity: match the exact
colors, typography, and spacing from the handoff.

## Decisions (confirmed with user)
- **Match the design exactly.** Drop features present on the live site but absent
  from the spec: tier-2 keyword sub-filter chips, the affiliation-chip row (org
  folds into the byline instead), and the third direct-`PDF` link.
- **English UI chrome** (`FIND`, `Details`/`Hide details`, `Read PDF`, empty
  state), matching the prototype.
- **Native `<details>`** for expand/collapse (restyled to Ledger), with the
  **first paper `open`** by default to honor the spec's "first paper open".

## Approach — token-mapped Tailwind
Define the 6 Ledger tokens as CSS custom properties in `base.html`, flipping
light→dark via the existing `.dark` selector, and map them to Tailwind color
names in the CDN config so components use utilities (`bg-bg`, `text-ink`,
`border-rule`, `text-accent`, `bg-ideabg`). Add `Newsreader` (serif) and
`IBM Plex Mono` (mono) to `fontFamily`. Dark mode is free (vars flip); no
`dark:` duplication for the palette.

### Tokens
| Token   | Light                   | Dark                     |
|---------|-------------------------|--------------------------|
| bg      | `#f6f2e8`               | `#161310`                |
| ink     | `#1b1815`               | `#ece5d5`                |
| sub     | `#736c5e`               | `#9c937f`                |
| rule    | `rgba(27,24,21,0.15)`   | `rgba(236,229,213,0.16)` |
| accent  | `#8a2b2b`               | `#df8f6a`                |
| org     | `#3d6673`               | `#79aab5`                |
| ideaBg  | `rgba(138,43,43,0.06)`  | `rgba(223,143,106,0.10)` |

The `org` token (design update 2026-07-20) colors the affiliation in the byline
(weight 500) so `nơi công tác` reads apart from the author names.

## Scope
Two template files + a small `web.py` data addition.

- **`base.html`**: Newsreader + IBM Plex Mono fonts; token `:root`/`.dark`
  `<style>`; Tailwind color/font mapping; body → `bg-bg text-ink font-serif`.
  Keep the no-flash theme script + `toggleTheme()`.
- **`index.html`**: single centered column (~836px content, `article` frame
  46/52px), full-width blocks separated by 1px `rule` hairlines, no card boxes:
  1. Masthead — mono kicker `AI SAFETY & LLM RED-TEAMING` + right date
     `Thu · 2026-07-17`; serif wordmark `PaperSummarizer` 40px; 2px solid-ink
     bottom rule. Theme toggle by the date.
  2. Standfirst — italic serif `N papers logged today · M in scope for AI
     safety`, counted live from the day's papers; hairline under.
  3. Search row — mono `FIND` + underline-only input, placeholder
     `title, author, tag…`.
  4. Filter tabs — square (radius 0) All / AI Safety / Other; active = accent.
  5. Month navigator (replaced the horizontal day rail; design update 2026-07-20)
     — `Browse by month` label + `{days} · {papers}` summary; wrapping month tabs
     (`JUN '26` + count, active = 2px accent underline); wrapping day grid for the
     *selected month only* (`DD` + `safety/total`, active day = accent fill). A
     `?month=YYYY-MM` picks the browsed month; `?date=` (day chip) drives the
     fetch, so browsing a month never changes the loaded day.
  6. Paper blocks — meta row (accent tag, `Rel/Idea/Gnd n`), serif title (→ arXiv
     abs), italic subtitle (omit when absent), mono byline `authors · org`, serif
     abstract, restyled Details (native `<details>`, first `open`), always-visible
     `📖 Read PDF` (accent) + `arXiv`. Expanded = 2-col grid
     (Novelty/Method/Results/Limitations) + full-width **Ideas to try** panel.
  7. Empty state — italic serif `No papers match "…".`
- **`web.py`**: add weekday-formatted masthead date (`Thu · 2026-07-17`) and
  `MM/DD` chip labels (via `datetime`). Search still spans all dates.

## Graceful degradation
`subtitle` and the standfirst sentence are the only bits not 1:1 in the data
model. Subtitle: omit when the summary has no short tagline. Standfirst:
computed from `papers|length` and the count with a non-empty `_set_slugs`.

## Verification
Run the FastAPI app locally against the existing SQLite DB, load `/` in the
browser (light + dark), and compare against
`screenshots/1a-ledger-light.png` / `1a-ledger-dark.png`. Confirm expand,
search, tabs, and day-rail all work.
