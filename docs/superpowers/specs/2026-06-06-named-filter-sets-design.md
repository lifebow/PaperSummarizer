# Named Filter Sets — Design Spec

Date: 2026-06-06
Status: Approved (design)

## Goal

Let the user define named filter sets (e.g. "AI Safety", "Computer Vision")
in config, and filter the web UI by set with a two-tier control. Adding a new
set later requires only a config edit, no code change.

## Decisions (locked)

- **Ingestion:** relevance acceptance uses the **union** of all sets' queries.
  Today only the "AI Safety" set exists, so ingestion is unchanged. Adding a
  "Computer Vision" set later widens the union; matching papers are accepted
  from the next scan onward (not retroactive).
- **Web UX:** two-tier filter. Tier 1 = set chips (`All | <sets...> | Other`).
  Tier 2 = keyword chips of the selected set (multi-select OR), shown only when
  a specific set is selected.
- Categories stay shared (`topics.categories`) for discovery; no per-set
  categories.
- Tags remain on-the-fly (no DB persistence).

## Config

```yaml
topics:
  categories: ["cs.AI","cs.CL","cs.CR","cs.PF","cs.SE","cs.CV"]
  filters:
    - name: "AI Safety"
      queries: ["AI safety", "LLM jailbreak", "prompt injection", ...]
    # - name: "Computer Vision"
    #   queries: ["object detection", "image segmentation", ...]
```

- **Backward-compat:** if `topics.filters` is absent but `topics.queries` is
  present (old flat format), wrap it as a single set named `"AI Safety"`.
- `config.topics.queries` continues to exist, computed as the de-duplicated,
  order-preserving union of all sets' queries. The relevance pipeline and
  `_topic_fingerprint` keep using `topics.queries` unchanged.

## Web

- Routes: `GET /?date=<d>&set=<slug>&topics=<kw,kw>`.
- Tier 1 chips: `All`, one per filter set, and `Other`.
- Tier 2 chips: the selected set's keyword slugs (only rendered when a concrete
  set is selected).
- Filtering:
  - No set / `All` → all accepted papers for the day.
  - `Other` → papers matching no set's keywords.
  - A set → papers matching that set; if keyword slugs are also selected,
    intersect to papers carrying at least one of those keywords.
- Cards keep the existing per-keyword chips.

## Modules

- `config.py`: `FilterSet(name, queries)` dataclass; `TopicConfig.filters`;
  loader builds `filters` (new format or backward-compat wrap) and computes
  `queries` as the union.
- `topics.py`: add `paper_filter_sets(paper, filter_sets) -> list[str]` (which
  set names match) — pure, unit-tested. `tag_paper` unchanged.
- `web.py`: build two-tier context; read `set` + `topics`.
- `templates/index.html`: tier-2 chip row, shown when a set is selected.

## Testing

- Loader: new `filters` format; backward-compat from flat `queries`; union
  computation (dedupe, order).
- `paper_filter_sets()`: matches one set, multiple sets, none (Other).
- Routes: filter by set; set + keyword intersection; Other bucket; unknown set
  slug ignored; tier-2 chips appear only when a set is selected.

## Out of scope (YAGNI)

- Per-set arXiv categories.
- Persisting set membership in the DB.
- Adding the Computer Vision queries now (user will add later).
