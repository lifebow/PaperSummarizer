from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from ._http import USER_AGENT, json_post

logger = logging.getLogger(__name__)


class LlmClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        http_post: Callable[..., dict[str, Any]] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.http_post = http_post or json_post

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        response = self.http_post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            payload={
                "model": self.model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=180,
        )
        content = response["choices"][0]["message"]["content"]
        return _extract_json_object(content)


def passes_quality_gate(
    scores: dict[str, Any],
    *,
    relevance_threshold: float = 7,
    grounding_threshold: float = 7,
    idea_threshold: float = 6,
) -> bool:
    return (
        float(scores.get("relevance_score", 0)) >= relevance_threshold
        and float(scores.get("grounding_score", 0)) >= grounding_threshold
        and float(scores.get("idea_score", 0)) >= idea_threshold
    )


def build_relevance_prompt(title: str, abstract: str, topics: list[str]) -> tuple[str, str]:
    system = "You judge whether a new AI paper matches the user's interests. Return strict JSON."
    user = json.dumps(
        {
            "task": "Score topic relevance from 0-10. Return relevance_score and reason.",
            "topics": topics,
            "title": title,
            "abstract": abstract,
        },
        ensure_ascii=False,
    )
    return system, user


_MAX_TEXT_CHARS = 10000
_EXPAND_MAX_TEXT_CHARS = 15000


def build_summary_prompt(title: str, abstract: str, full_text_markdown: str) -> tuple[str, str]:
    system = (
        "You summarize AI papers for idea mining. Return strict JSON with keys: "
        "background_needed, what_the_paper_does, novelty, method, math_technical_core, "
        "results_claims, limitations_uncertainty, ideas_to_try, author_names, author_affiliations. "
        "For author_names: list ALL author names from the paper header. "
        "For author_affiliations: extract the list of unique institution names "
        "(universities, companies, research labs) from the paper header under the title. "
        'Return both as lists of strings, e.g. author_names: ["John Doe", "Jane Smith"], '
        'author_affiliations: ["MIT", "Google DeepMind"]. '
        "If not available, return an empty list."
    )
    user = json.dumps(
        {
            "title": title,
            "abstract": abstract,
            "full_text_markdown": _truncate(full_text_markdown),
            "background_level": "deep but concise, especially math intuition and notation when needed",
        },
        ensure_ascii=False,
    )
    return system, user


def build_qa_prompt(summary: dict[str, Any], abstract: str, full_text_markdown: str) -> tuple[str, str]:
    system = "You are a QA judge. Check relevance, grounding, and idea quality. Return strict JSON."
    user = json.dumps(
        {
            "task": "Return relevance_score, grounding_score, idea_score, qa_reason, evidence_snippets.",
            "summary": summary,
            "abstract": abstract,
            "full_text_markdown": _truncate(full_text_markdown),
        },
        ensure_ascii=False,
    )
    return system, user


def _truncate(text: str, *, limit: int = _MAX_TEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [truncated]"


def build_expand_prompt(title: str, abstract: str, full_text_markdown: str) -> tuple[str, str]:
    """Build prompt for deep paper expansion analysis."""
    system = (
        "You perform deep analysis of AI research papers. Return strict JSON with these keys:\n"
        "- deep_summary: 3-5 sentence deep summary of the paper\n"
        "- problem_statement: what problem does the paper solve\n"
        "- key_contribution: the main contribution in one clear sentence\n"
        "- methodology_detail: detailed methodology, algorithm, architecture explanation\n"
        "- mathematical_framework: mathematical framework, notation, key assumptions\n"
        "- experiments_and_results: detailed experiments, benchmarks, metrics, comparisons\n"
        "- strengths: what makes this paper strong\n"
        "- weaknesses: limitations, assumptions, potential issues\n"
        "- reproducibility: assessment - code available? data? compute needed?\n"
        "- related_work_context: where this paper fits in the research landscape\n"
        "- practical_applications: potential real-world applications\n"
        "- extension_ideas: concrete ideas for extending or combining this work\n"
        "- reading_recommendation: who should read this and which sections to focus on"
    )
    user = json.dumps(
        {
            "title": title,
            "abstract": abstract,
            "full_text_markdown": _truncate(full_text_markdown, limit=_EXPAND_MAX_TEXT_CHARS),
            "analysis_depth": "thorough, with specific details and evidence from the paper",
        },
        ensure_ascii=False,
    )
    return system, user


def _extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(stripped[start : end + 1])
        raise
