"""사용자가 정한 범주의 '오늘' 뉴스 헤드라인 수집 (Google News RSS, API 키 불필요).

수집한 헤드라인만 LLM 에 넘겨 요약하게 하므로, 모델이 뉴스를 지어내지 않는다.
"""
from __future__ import annotations

import email.utils
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import requests

RSS = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{hl}"


@dataclass
class Article:
    title: str
    source: str
    published: float  # epoch
    link: str


def parse_rss(xml_text: str) -> list[Article]:
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        pub = item.findtext("pubDate") or ""
        try:
            ts = email.utils.parsedate_to_datetime(pub).timestamp()
        except (TypeError, ValueError):
            ts = 0.0
        out.append(Article(title, source, ts, (item.findtext("link") or "").strip()))
    return out


class NewsService:
    def __init__(self, cfg: dict[str, Any], session: requests.Session | None = None):
        self.cfg = cfg
        self.http = session or requests.Session()
        self._cache: dict[str, tuple[float, list[Article]]] = {}

    @property
    def categories(self) -> list[str]:
        return list(self.cfg.get("categories", {}))

    def fetch(self, category: str, max_age_h: float = 24) -> list[Article]:
        cats = self.cfg.get("categories", {})
        if category not in cats:
            raise KeyError(f"설정에 없는 범주: {category}. 가능한 범주: {', '.join(cats)}")
        cached = self._cache.get(category)
        if cached and time.time() - cached[0] < 600:
            return cached[1]
        q = urllib.parse.quote(f"{cats[category]} when:1d")
        url = RSS.format(q=q, hl=self.cfg.get("language", "ko"), gl=self.cfg.get("country", "KR"))
        r = self.http.get(url, timeout=10, headers={"User-Agent": "coffee-robot/0.1"})
        r.raise_for_status()
        now = time.time()
        items = [a for a in parse_rss(r.text) if not a.published or now - a.published < max_age_h * 3600]
        items.sort(key=lambda a: a.published, reverse=True)
        items = items[: int(self.cfg.get("max_items_per_category", 4))]
        self._cache[category] = (now, items)
        return items

    def briefing(self, categories: list[str] | None = None) -> dict[str, Any]:
        """LLM 도구 결과용 딕셔너리."""
        result: dict[str, Any] = {}
        for cat in categories or self.categories:
            try:
                result[cat] = [{"title": a.title, "source": a.source} for a in self.fetch(cat)]
            except Exception as e:
                result[cat] = {"error": str(e)}
        return result
