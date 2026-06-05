from __future__ import annotations

from pathlib import Path
from typing import Any


def render_paper_markdown(paper: dict[str, Any]) -> str:
    summary = paper.get("summary", {})
    ideas = summary.get("ideas_to_try", [])
    qa_scores = summary.get("qa_scores", {})
    lines = [
        f"### {paper.get('title', 'Untitled')}",
        "",
        f"- arXiv: {paper.get('arxiv_id', '')}",
        f"- PDF: {paper.get('pdf_url', '')}",
        _qa_line(paper, qa_scores),
        "",
        "**Background needed**",
        "",
        str(summary.get("background_needed", "")),
        "",
        "**What the paper does**",
        "",
        str(summary.get("what_the_paper_does", "")),
        "",
        "**Novelty / contribution**",
        "",
        str(summary.get("novelty", "")),
        "",
        "**Method**",
        "",
        str(summary.get("method", "")),
        "",
        "**Math / technical core**",
        "",
        str(summary.get("math_technical_core", "")),
        "",
        "**Results / claims**",
        "",
        str(summary.get("results_claims", "")),
        "",
        "**Limitations / uncertainty**",
        "",
        str(summary.get("limitations_uncertainty", "")),
        "",
        "**Ideas to try**",
        "",
    ]
    if ideas:
        lines.extend(f"- {idea}" for idea in ideas)
    else:
        lines.append("- No strong idea extracted.")
    lines.extend(
        [
            "",
            "**QA reason**",
            "",
            str(summary.get("qa_reason", paper.get("qa_reason", ""))),
            "",
        ]
    )
    return "\n".join(lines)


def append_digest_batch(digest_dir: Path, digest_date: str, batch_time: str, papers: list[dict[str, Any]]) -> Path:
    digest_dir.mkdir(parents=True, exist_ok=True)
    path = digest_dir / f"{digest_date}.md"
    is_new = not path.exists()
    chunks = []
    if is_new:
        chunks.append(f"# Paper Radar Digest - {digest_date}\n")
    chunks.append(f"## {batch_time} Batch\n")
    chunks.extend(render_paper_markdown(paper) for paper in papers)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n\n".join(chunks).rstrip() + "\n\n")
    return path


def render_paper_short(paper: dict[str, Any]) -> str:
    summary = paper.get("summary", {})
    ideas = summary.get("ideas_to_try") or []
    idea = ideas[0] if ideas else ""
    link = paper.get("pdf_url") or f"https://arxiv.org/abs/{paper.get('arxiv_id', '')}"
    why = summary.get("what_the_paper_does", "")
    novelty = summary.get("novelty", "")
    published = paper.get("published_at", "")
    affiliations = paper.get("author_affiliations") or summary.get("author_affiliations") or []
    author_names = summary.get("author_names") or paper.get("authors") or []
    if isinstance(author_names, str):
        author_names = [author_names]
    title = paper.get("title") or "Untitled"
    lines = [f"📄 *{title}*"]
    if published:
        lines.append(f"📅 {published}")
    if author_names:
        names_str = ", ".join(author_names[:8])
        if len(author_names) > 8:
            names_str += f" +{len(author_names) - 8} more"
        lines.append(f"👥 {names_str}")
    if affiliations:
        unique_affs = list(dict.fromkeys(affiliations))
        lines.append(f"🏢 {', '.join(unique_affs[:5])}")
    lines.append(f"🔗 [{paper.get('arxiv_id', 'link')}]({link})")
    if why:
        lines.append(f"\n🔍 *What:* {why}")
    if novelty:
        lines.append(f"✨ *Novelty:* {novelty}")
    if idea:
        lines.append(f"💡 *Idea:* {idea}")
    return "\n".join(lines)


def render_telegram_full(digest_date: str, papers: list[dict[str, Any]], *, limit: int = 15) -> str:
    if not papers:
        return ""
    shown = papers[:limit]
    lines = [f"Paper Radar full {digest_date}: {len(papers)} paper(s) today."]
    lines.extend(render_paper_short(p) for p in shown)
    remaining = len(papers) - limit
    if remaining > 0:
        lines.append(f"... and {remaining} more")
    return "\n".join(lines)


def render_telegram_diff(digest_date: str, batch_time: str, papers: list[dict[str, Any]], *, limit: int = 15) -> str:
    if not papers:
        return ""
    shown = papers[:limit]
    lines = [f"Paper Radar +{len(papers)} {batch_time} {digest_date}:"]
    lines.extend(render_paper_short(p) for p in shown)
    remaining = len(papers) - limit
    if remaining > 0:
        lines.append(f"... and {remaining} more")
    return "\n".join(lines)


def render_telegram_recap(digest_date: str, papers: list[dict[str, Any]]) -> str:
    if not papers:
        return ""
    lines = [f"Paper Radar recap {digest_date}: {len(papers)} paper(s) kept."]
    lines.extend(render_paper_short(p) for p in papers[:10])
    return "\n".join(lines)


def _qa_line(paper: dict[str, Any], qa_scores: dict[str, Any]) -> str:
    relevance = qa_scores.get("relevance", paper.get("relevance_score", ""))
    grounding = qa_scores.get("grounding", paper.get("grounding_score", ""))
    idea = qa_scores.get("idea", paper.get("idea_score", ""))
    return f"- QA: relevance {relevance} / grounding {grounding} / idea {idea}"


def render_expanded_analysis(expansion: dict[str, Any], paper: dict[str, Any] | None = None) -> str:
    """Render expanded analysis for Telegram."""
    skeleton = expansion.get("skeleton", expansion)
    title = paper.get("title", "") if paper else ""
    arxiv_id = paper.get("arxiv_id", "") if paper else expansion.get("arxiv_id", "")

    lines: list[str] = []
    if title:
        lines.append(f"🔬 *Expanded: {title}*")
    if arxiv_id:
        lines.append(f"🔗 [{arxiv_id}](https://arxiv.org/abs/{arxiv_id})")
    lines.append("")

    sections = [
        ("📝 Deep Summary", "deep_summary"),
        ("❓ Problem Statement", "problem_statement"),
        ("⭐ Key Contribution", "key_contribution"),
        ("🔧 Methodology Detail", "methodology_detail"),
        ("📐 Mathematical Framework", "mathematical_framework"),
        ("📊 Experiments & Results", "experiments_and_results"),
        ("💪 Strengths", "strengths"),
        ("⚠️ Weaknesses", "weaknesses"),
        ("🔄 Reproducibility", "reproducibility"),
        ("📚 Related Work Context", "related_work_context"),
        ("🚀 Practical Applications", "practical_applications"),
        ("💡 Extension Ideas", "extension_ideas"),
        ("📖 Reading Recommendation", "reading_recommendation"),
    ]

    for label, key in sections:
        value = skeleton.get(key, "")
        if value:
            if isinstance(value, list):
                lines.append(f"*{label}*")
                lines.extend(f"• {item}" for item in value)
                lines.append("")
            else:
                lines.append(f"*{label}*")
                lines.append(str(value))
                lines.append("")

    return "\n".join(lines)
