# -*- coding: utf-8 -*-
"""도메인 모델 — DB 행과 1:1 대응 (PLAN §3).

모든 시각 값은 timezone-aware UTC 로 다룬다. 지수 계산이 Δt 실측에 의존하므로
naive datetime 은 허용하지 않는다 (수집 주기가 흔들려도 결과가 맞아야 함).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise ValueError("naive datetime 은 허용하지 않습니다 (UTC tz-aware 필요)")
    return dt.astimezone(timezone.utc).isoformat()


@dataclass
class Channel:
    id: str
    title: str
    handle: str | None = None
    thumbnail_url: str | None = None
    country: str | None = None
    uploads_playlist: str | None = None
    subscriber_count: int | None = None
    video_count: int | None = None
    view_count: int | None = None
    category_id: str | None = None
    region: str | None = None
    is_seed: bool = False

    def to_row(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "handle": self.handle,
            "thumbnail_url": self.thumbnail_url,
            "country": self.country,
            "uploads_playlist": self.uploads_playlist,
            "subscriber_count": self.subscriber_count,
            "video_count": self.video_count,
            "view_count": self.view_count,
            "category_id": self.category_id,
            "region": self.region,
            "is_seed": self.is_seed,
            "last_seen_at": _iso(utcnow()),
            "updated_at": _iso(utcnow()),
        }


@dataclass
class ChannelSnapshot:
    channel_id: str
    ts: datetime
    subscriber_count: int | None = None
    view_count: int | None = None
    video_count: int | None = None

    def to_row(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "ts": _iso(self.ts),
            "subscriber_count": self.subscriber_count,
            "view_count": self.view_count,
            "video_count": self.video_count,
        }


@dataclass
class Video:
    id: str
    channel_id: str
    title: str
    published_at: datetime
    thumbnail_url: str | None = None
    duration_seconds: int | None = None
    is_short: bool = False
    category_id: str | None = None
    region: str | None = None
    view_count: int | None = None
    like_count: int | None = None

    def to_row(self) -> dict:
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "title": self.title,
            "published_at": _iso(self.published_at),
            "thumbnail_url": self.thumbnail_url,
            "duration_seconds": self.duration_seconds,
            "is_short": self.is_short,
            "category_id": self.category_id,
            "region": self.region,
            "view_count": self.view_count,
            "like_count": self.like_count,
            "updated_at": _iso(utcnow()),
        }


@dataclass
class VideoSnapshot:
    video_id: str
    ts: datetime
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None

    def to_row(self) -> dict:
        return {
            "video_id": self.video_id,
            "ts": _iso(self.ts),
            "view_count": self.view_count,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
        }


@dataclass
class TrendScore:
    """랭킹 보드 한 줄. 웹이 조인 없이 카드를 그릴 수 있도록 표시 필드를 함께 담는다."""

    scope: str  # 'video' | 'channel'
    kind: str  # 'trending' | 'rising'
    category_id: str
    rank: int
    score: float
    target_id: str
    region: str | None = None
    title: str | None = None
    channel_id: str | None = None
    channel_title: str | None = None
    thumbnail_url: str | None = None
    published_at: datetime | None = None
    view_count: int | None = None
    subscriber_count: int | None = None
    delta_views: int | None = None
    window_hours: float | None = None

    def to_row(self) -> dict:
        return {
            "scope": self.scope,
            "kind": self.kind,
            "category_id": self.category_id,
            "region": self.region or "",
            "rank": self.rank,
            "score": self.score,
            "target_id": self.target_id,
            "title": self.title,
            "channel_id": self.channel_id,
            "channel_title": self.channel_title,
            "thumbnail_url": self.thumbnail_url,
            "published_at": _iso(self.published_at) or "",
            "view_count": self.view_count,
            "subscriber_count": self.subscriber_count,
            "delta_views": self.delta_views,
            "window_hours": self.window_hours,
        }


@dataclass
class QuotaUsage:
    day: str
    endpoint: str
    calls: int = 0
    units: int = 0
