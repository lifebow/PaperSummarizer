from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TopicConfig:
    categories: list[str] = field(default_factory=lambda: ["cs.AI"])
    queries: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DaemonConfig:
    interval_minutes: int = 60
    timezone: str = "Asia/Ho_Chi_Minh"
    daily_recap_time: str = "21:00"
    daily_recap_times: list[str] = field(default_factory=lambda: ["11:00", "23:00"])
    first_run_lookback_hours: int = 48
    release_window_start: str = ""
    release_window_end: str = ""


@dataclass(frozen=True)
class FilterConfig:
    max_papers_per_batch: int = 20
    relevance_threshold: int = 7
    grounding_threshold: int = 7
    idea_threshold: int = 6


@dataclass(frozen=True)
class PathConfig:
    database: Path = Path("data/paper_radar.sqlite3")
    tmp_pdfs: Path = Path("data/tmp_pdfs")
    digests: Path = Path("digests")


@dataclass(frozen=True)
class SemanticScholarConfig:
    enabled: bool = True
    api_keys: list[str] = field(default_factory=list)
    api_key_env: str = "SEMANTIC_SCHOLAR_API_KEYS"
    fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LlmConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""


@dataclass(frozen=True)
class BotConfig:
    webhook_url: str = ""
    webhook_port: int = 8080


@dataclass(frozen=True)
class PipelineConfig:
    llm_concurrency: int = 4
    download_concurrency: int = 3
    max_papers_per_run: int = 50
    max_llm_calls_per_run: int = 0
    max_summary_candidates_per_run: int = 20
    enable_relevance_cache: bool = True
    merge_summary_qa: bool = False
    release_discovery_limit: int = 2000
    normal_discovery_limit: int = 100
    hydrate_metadata_per_run: int = 300


@dataclass(frozen=True)
class AppConfig:
    topics: TopicConfig = field(default_factory=TopicConfig)
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    semantic_scholar: SemanticScholarConfig = field(default_factory=SemanticScholarConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    bot: BotConfig = field(default_factory=BotConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


def load_config(config_path: str | Path = "config.yaml", env_path: str | Path = ".env") -> AppConfig:
    config_path = Path(config_path)
    env_values = _load_env_file(Path(env_path))
    raw = _parse_simple_yaml(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}

    topics = raw.get("topics", {})
    daemon = raw.get("daemon", {})
    filters = raw.get("filters", {})
    paths = raw.get("paths", {})
    s2 = raw.get("semantic_scholar", {})
    llm = raw.get("llm", {})
    telegram = raw.get("telegram", {})
    bot = raw.get("bot", {})
    pipeline = raw.get("pipeline", {})

    s2_key_env = str(s2.get("api_key_env", "SEMANTIC_SCHOLAR_API_KEYS"))
    llm_base_env = str(llm.get("base_url_env", "OPENAI_BASE_URL"))
    llm_key_env = str(llm.get("api_key_env", "OPENAI_API_KEY"))
    llm_model_env = str(llm.get("model_env", "OPENAI_MODEL"))
    telegram_token_env = str(telegram.get("bot_token_env", "TELEGRAM_BOT_TOKEN"))
    telegram_chat_env = str(telegram.get("chat_id_env", "TELEGRAM_CHAT_ID"))

    _default_recap_times = ["11:00", "23:00"]
    _daily_recap_times = daemon.get("daily_recap_times")
    if isinstance(_daily_recap_times, list) and _daily_recap_times:
        resolved_recap_times = [str(t) for t in _daily_recap_times]
    elif "daily_recap_time" in daemon:
        resolved_recap_times = [str(daemon["daily_recap_time"])]
    else:
        resolved_recap_times = _default_recap_times

    return AppConfig(
        topics=TopicConfig(
            categories=list(topics.get("categories", ["cs.AI"])),
            queries=list(topics.get("queries", [])),
        ),
        daemon=DaemonConfig(
            interval_minutes=int(daemon.get("interval_minutes", 60)),
            timezone=str(daemon.get("timezone", "Asia/Ho_Chi_Minh")),
            daily_recap_time=str(daemon.get("daily_recap_time", "21:00")),
            daily_recap_times=resolved_recap_times,
            first_run_lookback_hours=int(daemon.get("first_run_lookback_hours", 48)),
            release_window_start=str(daemon.get("release_window_start", "")),
            release_window_end=str(daemon.get("release_window_end", "")),
        ),
        filters=FilterConfig(
            max_papers_per_batch=int(filters.get("max_papers_per_batch", 20)),
            relevance_threshold=int(filters.get("relevance_threshold", 7)),
            grounding_threshold=int(filters.get("grounding_threshold", 7)),
            idea_threshold=int(filters.get("idea_threshold", 6)),
        ),
        paths=PathConfig(
            database=Path(str(paths.get("database", "data/paper_radar.sqlite3"))),
            tmp_pdfs=Path(str(paths.get("tmp_pdfs", "data/tmp_pdfs"))),
            digests=Path(str(paths.get("digests", "digests"))),
        ),
        semantic_scholar=SemanticScholarConfig(
            enabled=bool(s2.get("enabled", True)),
            api_keys=_split_keys(_env(s2_key_env, env_values)),
            api_key_env=s2_key_env,
            fields=list(s2.get("fields", [])),
        ),
        llm=LlmConfig(
            base_url=_env(llm_base_env, env_values),
            api_key=_env(llm_key_env, env_values),
            model=_env(llm_model_env, env_values),
        ),
        telegram=TelegramConfig(
            bot_token=_env(telegram_token_env, env_values),
            chat_id=_env(telegram_chat_env, env_values),
        ),
        bot=BotConfig(
            webhook_url=_env(str(bot.get("webhook_url_env", "BOT_WEBHOOK_URL")), env_values),
            webhook_port=int(bot.get("webhook_port", 8080)),
        ),
        pipeline=PipelineConfig(
            llm_concurrency=int(pipeline.get("llm_concurrency", 4)),
            download_concurrency=int(pipeline.get("download_concurrency", 3)),
            max_papers_per_run=int(pipeline.get("max_papers_per_run", 50)),
            max_llm_calls_per_run=int(pipeline.get("max_llm_calls_per_run", 0)),
            max_summary_candidates_per_run=int(pipeline.get("max_summary_candidates_per_run", 20)),
            enable_relevance_cache=bool(pipeline.get("enable_relevance_cache", True)),
            merge_summary_qa=bool(pipeline.get("merge_summary_qa", False)),
            release_discovery_limit=int(pipeline.get("release_discovery_limit", 2000)),
            normal_discovery_limit=int(pipeline.get("normal_discovery_limit", 100)),
            hydrate_metadata_per_run=int(pipeline.get("hydrate_metadata_per_run", 300)),
        ),
    )


def _env(name: str, env_values: dict[str, str]) -> str:
    if name in os.environ:
        return os.environ[name]
    return env_values.get(name, "")


def _split_keys(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    pending_list_key: tuple[int, dict[str, Any], str] | None = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        if line.startswith("- "):
            if pending_list_key is None:
                raise ValueError(f"List item without key: {raw_line}")
            list_indent, parent, key = pending_list_key
            if indent <= list_indent:
                raise ValueError(f"Invalid list indentation: {raw_line}")
            if isinstance(parent.get(key), dict) and not parent[key]:
                parent[key] = []
            parent.setdefault(key, []).append(_parse_scalar(line[2:].strip()))
            continue

        pending_list_key = None
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
            pending_list_key = (indent, parent, key)
        else:
            parent[key] = _parse_scalar(value)

    return root


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value
