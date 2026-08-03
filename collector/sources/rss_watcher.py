# -*- coding: utf-8 -*-
"""채널 RSS 피드 감시 — 쿼터 0 (PLAN §1).

https://www.youtube.com/feeds/videos.xml?channel_id=UC...
API 가 아니라 공개 피드이므로 YouTube Data API 쿼터를 소모하지 않는다.
새 영상 감지의 기본 수단이며, 채널당 최신 15개만 노출된다(실측) —
하루 3회 폴링이면 일 15개 초과 업로드 채널을 제외하고 누락이 없다.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree as ET

from core.config import Settings

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


@dataclass
class FeedEntry:
    video_id: str
    title: str
    published_at: datetime
    thumbnail_url: str | None = None
    view_count: int | None = None


@dataclass
class Feed:
    channel_id: str
    channel_title: str = ""
    entries: list[FeedEntry] = field(default_factory=list)


def _text(node, path: str) -> str | None:
    el = node.find(path, NS)
    return el.text if el is not None and el.text else None


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _resolve_channel_id(root) -> str:
    """피드에서 채널 ID(UC...)를 복원한다.

    ⚠️ 실측 quirk (2026-07): **루트의 `<yt:channelId>` 는 `UC` 접두어가 잘려 나온다.**
       (`UCDqOf2y4k-...` → `DqOf2y4k-...`) 반면 entry 레벨은 온전한 형태다.
       따라서 루트 값을 그대로 믿으면 DB 외래키가 어긋난다. 신뢰 순서대로 시도한다.
    """
    # 1) entry 레벨 yt:channelId — 온전한 UC 형태
    for entry in root.findall("atom:entry", NS):
        cid = _text(entry, "yt:channelId")
        if cid and cid.startswith("UC"):
            return cid

    # 2) 루트 링크에서 복원 (/channel/UC... 또는 ?channel_id=UC...)
    for link in root.findall("atom:link", NS):
        href = link.get("href") or ""
        if "/channel/" in href:
            cid = href.rsplit("/channel/", 1)[-1].split("?")[0].split("/")[0]
            if cid.startswith("UC"):
                return cid
        if "channel_id=" in href:
            cid = href.split("channel_id=", 1)[-1].split("&")[0]
            if cid.startswith("UC"):
                return cid

    # 3) 최후: 잘린 루트 값에 접두어를 복원
    raw = _text(root, "yt:channelId") or ""
    if raw and not raw.startswith("UC"):
        return f"UC{raw}"
    return raw


def parse_feed(xml: str) -> Feed:
    root = ET.fromstring(xml)
    feed = Feed(
        channel_id=_resolve_channel_id(root),
        channel_title=_text(root, "atom:title") or "",
    )
    for entry in root.findall("atom:entry", NS):
        thumb = entry.find("media:group/media:thumbnail", NS)
        stats = entry.find("media:group/media:community/media:statistics", NS)
        views = None
        if stats is not None and stats.get("views"):
            try:
                views = int(stats.get("views"))
            except (TypeError, ValueError):
                views = None
        feed.entries.append(
            FeedEntry(
                video_id=_text(entry, "yt:videoId") or "",
                title=_text(entry, "atom:title") or "",
                published_at=_parse_ts(_text(entry, "atom:published")),
                thumbnail_url=thumb.get("url") if thumb is not None else None,
                view_count=views,
            )
        )
    return feed


class RssWatcher(Protocol):
    def fetch(self, channel_id: str) -> Feed: ...


class _BaseWatcher:
    quota = None  # RSS 는 쿼터를 쓰지 않는다 (테스트가 이를 확인한다)

    def fetch(self, channel_id: str) -> Feed:  # pragma: no cover - 하위 클래스에서 구현
        raise NotImplementedError

    def new_since(self, channel_id: str, cutoff: datetime) -> list[FeedEntry]:
        """cutoff 이후에 공개된 항목만 돌려준다."""
        if cutoff.tzinfo is None:
            raise ValueError("naive datetime 은 허용하지 않습니다 (UTC tz-aware 필요)")
        return [e for e in self.fetch(channel_id).entries if e.published_at > cutoff]


class HarnessRssWatcher(_BaseWatcher):
    def __init__(self, fixtures: Path | None = None) -> None:
        self.fixtures = fixtures or FIXTURES

    def fetch(self, channel_id: str) -> Feed:
        path = self.fixtures / f"feed_{channel_id}.xml"
        if not path.exists():
            return Feed(channel_id=channel_id)
        return parse_feed(path.read_text(encoding="utf-8"))


class LiveRssWatcher(_BaseWatcher):
    def __init__(self, timeout: int = 25) -> None:
        self.timeout = timeout

    def fetch(self, channel_id: str) -> Feed:
        import requests

        r = requests.get(FEED_URL.format(channel_id=channel_id), timeout=self.timeout)
        if r.status_code == 404:
            return Feed(channel_id=channel_id)  # 삭제/비공개 채널
        if not r.ok:
            raise RuntimeError(f"RSS HTTP {r.status_code} for {channel_id}")
        return parse_feed(r.text)


def get_rss_watcher(settings: Settings) -> RssWatcher:
    # RSS 는 API 키가 필요 없다 — live 라도 키 검증을 하지 않는다.
    return LiveRssWatcher() if settings.yt_mode == "live" else HarnessRssWatcher()
