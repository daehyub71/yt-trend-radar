# -*- coding: utf-8 -*-
"""YouTube Data API v3 래퍼.

- harness: tests/fixtures 의 저장된 응답으로 동작 (외부 호출 0)
- live   : requests 로 실제 호출. 모든 호출은 QuotaLedger 를 거친다.

배치 규칙: id 파라미터는 최대 50개 → 1 unit. 이 배치가 쿼터 전략의 핵심이다.
"""
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol

from core.config import Settings
from core.models import Channel, ChannelSnapshot, Video, VideoSnapshot, utcnow
from core.quota import MAX_IDS_PER_CALL, QuotaLedger, chunked

API_BASE = "https://www.googleapis.com/youtube/v3"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# YouTube Shorts 는 최대 3분이다. API 가 종횡비를 주지 않으므로 길이를 대용 지표로 쓴다.
# (오분류 가능성이 있으므로 랭킹에서 short/long 을 섞을지는 P2 결정 사항)
SHORTS_MAX_SECONDS = 180

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_duration(iso: str | None) -> int | None:
    """ISO 8601 기간(PT12M34S)을 초로 변환. 파싱 실패 시 None."""
    if not iso:
        return None
    m = _DURATION_RE.match(iso.strip())
    if not m or not any(m.groupdict().values()):
        return None
    g = {k: int(v) if v else 0 for k, v in m.groupdict().items()}
    return g["days"] * 86_400 + g["hours"] * 3_600 + g["minutes"] * 60 + g["seconds"]


def _int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _best_thumbnail(thumbs: dict | None) -> str | None:
    if not thumbs:
        return None
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbs and thumbs[key].get("url"):
            return thumbs[key]["url"]
    return None


# ---------------------------------------------------------------- 반환 타입


@dataclass
class VideoFetch:
    video: Video
    snapshot: VideoSnapshot


@dataclass
class ChannelFetch:
    channel: Channel
    snapshot: ChannelSnapshot


@dataclass
class ChannelRef:
    """search.list 로 발굴된 채널의 최소 정보. 통계는 별도 channels.list 로 채운다."""

    channel_id: str
    title: str = ""
    description: str = ""


# ---------------------------------------------------------------- 파싱


def _video_from_item(item: dict, ts: datetime) -> VideoFetch:
    sn = item.get("snippet") or {}
    st = item.get("statistics") or {}
    cd = item.get("contentDetails") or {}
    seconds = parse_duration(cd.get("duration"))
    video = Video(
        id=item["id"],
        channel_id=sn.get("channelId", ""),
        title=sn.get("title", ""),
        published_at=_parse_ts(sn.get("publishedAt")) or ts,
        thumbnail_url=_best_thumbnail(sn.get("thumbnails")),
        duration_seconds=seconds,
        is_short=bool(seconds is not None and seconds <= SHORTS_MAX_SECONDS),
        view_count=_int(st.get("viewCount")),
        like_count=_int(st.get("likeCount")),
    )
    snapshot = VideoSnapshot(
        video_id=video.id,
        ts=ts,
        view_count=_int(st.get("viewCount")),
        like_count=_int(st.get("likeCount")),
        comment_count=_int(st.get("commentCount")),
    )
    return VideoFetch(video=video, snapshot=snapshot)


def _channel_from_item(item: dict, ts: datetime) -> ChannelFetch:
    sn = item.get("snippet") or {}
    st = item.get("statistics") or {}
    uploads = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
    channel = Channel(
        id=item["id"],
        title=sn.get("title", ""),
        handle=sn.get("customUrl"),
        thumbnail_url=_best_thumbnail(sn.get("thumbnails")),
        country=sn.get("country"),
        uploads_playlist=uploads,
        subscriber_count=_int(st.get("subscriberCount")),
        video_count=_int(st.get("videoCount")),
        view_count=_int(st.get("viewCount")),
    )
    snapshot = ChannelSnapshot(
        channel_id=channel.id,
        ts=ts,
        subscriber_count=_int(st.get("subscriberCount")),
        view_count=_int(st.get("viewCount")),
        video_count=_int(st.get("videoCount")),
    )
    return ChannelFetch(channel=channel, snapshot=snapshot)


# ---------------------------------------------------------------- 클라이언트


def _channel_refs_from_search(data: dict) -> list[ChannelRef]:
    """검색 응답에서 채널 결과만 추린다.

    type=channel 을 줘도 방어적으로 검증한다 — 영상/재생목록이 섞이면 이후 파이프라인이
    존재하지 않는 채널을 추적하게 된다.
    """
    out: list[ChannelRef] = []
    for item in data.get("items", []):
        ident = item.get("id") or {}
        cid = ident.get("channelId") or ""
        if ident.get("kind") != "youtube#channel" or not cid.startswith("UC"):
            continue
        sn = item.get("snippet") or {}
        out.append(
            ChannelRef(
                channel_id=cid,
                title=sn.get("channelTitle") or sn.get("title", ""),
                description=sn.get("description", ""),
            )
        )
    return out


def _channel_refs_from_video_search(data: dict) -> list[ChannelRef]:
    """최근 인기 영상 검색 결과에서 채널을 추린다 (채널당 1회).

    `type=channel` 검색은 채널 권위도(≈규모)에 편향돼 대형 채널만 나온다. 반면
    "최근 조회수 상위 영상의 채널"은 **지금 성과를 내는** 채널이라 소형·신규가 섞인다.
    이 서비스가 찾는 대상에 더 맞는 발굴 경로다.
    """
    out: list[ChannelRef] = []
    seen: set[str] = set()
    for item in data.get("items", []):
        ident = item.get("id") or {}
        if ident.get("kind") != "youtube#video":
            continue
        sn = item.get("snippet") or {}
        cid = sn.get("channelId") or ""
        if not cid.startswith("UC") or cid in seen:
            continue
        seen.add(cid)
        out.append(
            ChannelRef(
                channel_id=cid,
                title=sn.get("channelTitle", ""),
                description=sn.get("description", ""),
            )
        )
    return out


class YouTubeClient(Protocol):
    quota: QuotaLedger

    def fetch_videos(self, video_ids: Iterable[str]) -> list[VideoFetch]: ...
    def fetch_channels(self, channel_ids: Iterable[str]) -> list[ChannelFetch]: ...
    def search_channels(self, query: str, max_results: int = 25) -> list[ChannelRef]: ...
    def search_channels_via_videos(
        self, query: str, days: int = 30, max_results: int = 50
    ) -> list[ChannelRef]: ...


class _BaseClient:
    def __init__(self, quota: QuotaLedger | None = None) -> None:
        self.quota = quota or QuotaLedger()

    def _batches(self, ids: Iterable[str]) -> list[list[str]]:
        unique = list(dict.fromkeys(i for i in ids if i))
        return list(chunked(unique, MAX_IDS_PER_CALL))


class HarnessYouTubeClient(_BaseClient):
    """fixtures 기반 구현. 요청한 id 중 fixture 에 있는 것만 돌려준다."""

    def __init__(self, quota: QuotaLedger | None = None, fixtures: Path | None = None) -> None:
        super().__init__(quota)
        self.fixtures = fixtures or FIXTURES

    def _load(self, name: str) -> dict:
        return json.loads((self.fixtures / name).read_text(encoding="utf-8"))

    def fetch_videos(self, video_ids: Iterable[str]) -> list[VideoFetch]:
        batches = self._batches(video_ids)
        if not batches:
            return []
        items = {it["id"]: it for it in self._load("videos_list.json").get("items", [])}
        ts = utcnow()
        out: list[VideoFetch] = []
        for batch in batches:
            self.quota.charge("videos.list")
            out.extend(_video_from_item(items[i], ts) for i in batch if i in items)
        return out

    def fetch_channels(self, channel_ids: Iterable[str]) -> list[ChannelFetch]:
        batches = self._batches(channel_ids)
        if not batches:
            return []
        items = {it["id"]: it for it in self._load("channels_list.json").get("items", [])}
        ts = utcnow()
        out: list[ChannelFetch] = []
        for batch in batches:
            self.quota.charge("channels.list")
            out.extend(_channel_from_item(items[i], ts) for i in batch if i in items)
        return out

    def search_channels(self, query: str, max_results: int = 25) -> list[ChannelRef]:
        self.quota.charge("search.list")
        return _channel_refs_from_search(self._load("search_channels.json"))[:max_results]

    def search_channels_via_videos(
        self, query: str, days: int = 30, max_results: int = 50
    ) -> list[ChannelRef]:
        self.quota.charge("search.list")
        return _channel_refs_from_video_search(self._load("search_videos.json"))[:max_results]


class LiveYouTubeClient(_BaseClient):
    def __init__(self, api_key: str, quota: QuotaLedger | None = None, timeout: int = 30) -> None:
        super().__init__(quota)
        self._key = api_key
        self.timeout = timeout

    def _get(self, endpoint: str, params: dict) -> dict:
        import requests

        self.quota.charge(endpoint)  # 호출 전에 회계 — 예산 초과면 요청조차 하지 않는다
        r = requests.get(
            f"{API_BASE}/{endpoint.split('.')[0]}",
            params={**params, "key": self._key},
            timeout=self.timeout,
        )
        if not r.ok:
            # 에러 본문에 키가 실릴 수 있으므로 reason 만 추출한다.
            try:
                err = r.json().get("error", {})
                reasons = [e.get("reason") for e in err.get("errors", [])]
            except Exception:  # noqa: BLE001
                reasons = []
            raise RuntimeError(f"{endpoint} HTTP {r.status_code} reasons={reasons}")
        return r.json()

    def fetch_videos(self, video_ids: Iterable[str]) -> list[VideoFetch]:
        out: list[VideoFetch] = []
        for batch in self._batches(video_ids):
            data = self._get(
                "videos.list",
                {"part": "snippet,statistics,contentDetails", "id": ",".join(batch), "maxResults": 50},
            )
            ts = utcnow()
            out.extend(_video_from_item(it, ts) for it in data.get("items", []))
        return out

    def fetch_channels(self, channel_ids: Iterable[str]) -> list[ChannelFetch]:
        out: list[ChannelFetch] = []
        for batch in self._batches(channel_ids):
            data = self._get(
                "channels.list",
                {"part": "snippet,statistics,contentDetails", "id": ",".join(batch), "maxResults": 50},
            )
            ts = utcnow()
            out.extend(_channel_from_item(it, ts) for it in data.get("items", []))
        return out

    def search_channels(self, query: str, max_results: int = 25) -> list[ChannelRef]:
        """채널 발굴. 100 units/회 — 반드시 예산제로만 호출한다 (SPEC FR-6)."""
        data = self._get(
            "search.list",
            {
                "part": "snippet",
                "type": "channel",
                "q": query,
                "maxResults": min(max_results, 50),
                "regionCode": "KR",
                "relevanceLanguage": "ko",
                "order": "relevance",
            },
        )
        return _channel_refs_from_search(data)[:max_results]

    def search_channels_via_videos(
        self, query: str, days: int = 30, max_results: int = 50
    ) -> list[ChannelRef]:
        """최근 N일 조회수 상위 영상 → 그 채널. 소형·신규 채널 발굴 경로 (100 units/회)."""
        from datetime import timedelta

        after = (utcnow() - timedelta(days=days)).replace(microsecond=0)
        data = self._get(
            "search.list",
            {
                "part": "snippet",
                "type": "video",
                "q": query,
                "maxResults": min(max_results, 50),
                "regionCode": "KR",
                "relevanceLanguage": "ko",
                "order": "viewCount",
                "publishedAfter": after.isoformat().replace("+00:00", "Z"),
            },
        )
        return _channel_refs_from_video_search(data)[:max_results]


def get_youtube_client(settings: Settings, quota: QuotaLedger | None = None) -> YouTubeClient:
    ledger = quota or QuotaLedger.from_settings(settings)
    if settings.yt_mode == "live":
        settings.require_yt_credentials()
        return LiveYouTubeClient(settings.yt_api_key, ledger)
    return HarnessYouTubeClient(ledger)
