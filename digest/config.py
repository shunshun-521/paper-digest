"""Load YAML settings and read secrets from the environment."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class LLMSettings(BaseModel):
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.3
    use_vision: bool = True
    max_input_chars: int = 120000

    def api_key(self) -> str | None:
        value = os.environ.get(self.api_key_env, "").strip()
        return value or None


class SourceSettings(BaseModel):
    alphaxiv_for_you: bool = True
    alphaxiv_hot: bool = True
    hf_daily: bool = True
    arxiv_fallback_categories: list[str] = Field(
        default_factory=lambda: ["cs.CL", "cs.LG", "cs.CV", "cs.AI"]
    )


class NotifySettings(BaseModel):
    email: bool = True
    wechat: bool = True
    wechat_provider: str = "serverchan"


class DeploySettings(BaseModel):
    target: str = "cloudflare"
    site_base_url: str = ""


class Settings(BaseModel):
    timezone: str = "Asia/Shanghai"
    papers_per_day: int = 5
    candidates_on_page: int = 12
    journal_items_max: int = 2
    llm: LLMSettings = Field(default_factory=LLMSettings)
    sources: SourceSettings = Field(default_factory=SourceSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)
    deploy: DeploySettings = Field(default_factory=DeploySettings)


class Topic(BaseModel):
    id: str
    name: str
    default: bool = False
    description: str = ""


class TopicsFile(BaseModel):
    topics: list[Topic] = Field(default_factory=list)


class JournalFeed(BaseModel):
    name: str
    url: str


class FeedsFile(BaseModel):
    journals: list[JournalFeed] = Field(default_factory=list)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def load_settings(root: Path | None = None) -> Settings:
    root = root or repo_root()
    return Settings.model_validate(_read_yaml(root / "config" / "settings.yaml"))


def load_topics(root: Path | None = None) -> list[Topic]:
    root = root or repo_root()
    return TopicsFile.model_validate(_read_yaml(root / "config" / "topics.yaml")).topics


def load_feeds(root: Path | None = None) -> list[JournalFeed]:
    root = root or repo_root()
    return FeedsFile.model_validate(_read_yaml(root / "config" / "feeds.yaml")).journals


def env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None
