# -*- coding: utf-8 -*-
"""DB 접근 계층.

- harness 모드: InMemoryDB (외부 호출 없음 — 기본 테스트 게이트가 여기서 돈다)
- live 모드   : SupabaseRestDB — PostgREST(HTTPS) 호출. 네이티브 드라이버를 쓰지 않는다.
                DDL 은 tools/apply_migrations.py 담당 (런타임은 DDL 을 하지 않는다).

⚠️ 이 Supabase 프로젝트는 다른 앱들과 공유된다. 모든 물리 테이블명은 `ytr_` 접두어를 쓰며,
   접두어는 TABLES 한 곳에서만 정의한다 (테스트가 이를 강제한다).
"""
from datetime import datetime
from typing import Iterable, Protocol, runtime_checkable

from core.config import Category, Region, Settings
from core.models import Channel, ChannelSnapshot, Video, VideoSnapshot

TABLES: dict[str, str] = {
    "categories": "ytr_categories",
    "regions": "ytr_regions",
    "channels": "ytr_channels",
    "channel_snapshots": "ytr_channel_snapshots",
    "videos": "ytr_videos",
    "video_snapshots": "ytr_video_snapshots",
    "trend_scores": "ytr_trend_scores",
    "quota_usage": "ytr_quota_usage",
}

PUBLISH_RPC = "ytr_publish_trend_scores"

# purge 대상과 기준 컬럼 (SPEC NFR-1: YouTube ToS 30일)
# 채널 메타(ytr_channels)는 계속 갱신되는 추적 대상이므로 대상이 아니다.
PURGE_TARGETS: list[tuple[str, str]] = [
    ("video_snapshots", "ts"),
    ("channel_snapshots", "ts"),
    ("videos", "published_at"),
]


def _require_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime 은 허용하지 않습니다 (UTC tz-aware 필요)")
    return dt


def encode_ts(dt: datetime) -> str:
    """타임스탬프를 PostgREST 쿼리 값으로 인코딩한다.

    ⚠️ ISO 문자열의 `+09:00`/`+00:00` 의 `+` 는 쿼리스트링에서 **공백으로 해석**된다.
       인코딩하지 않으면 PostgREST 가 `2026-07-04T00:27:24 00:00` 을 받고 400 을 낸다
       (실측 2026-08-03). purge 도 같은 경로를 쓰므로 ToS 삭제가 조용히 실패할 수 있었다.
    """
    from urllib.parse import quote

    return quote(_require_aware(dt).isoformat(), safe="")


def _as_dt(value) -> datetime | None:
    """행에서 읽은 시각 값을 tz-aware datetime 으로. ISO 문자열/datetime 모두 허용."""
    if value is None or isinstance(value, datetime):
        return value
    from datetime import timezone

    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def channel_from_row(row: dict) -> Channel:
    return Channel(
        id=row["id"],
        title=row.get("title") or "",
        handle=row.get("handle"),
        thumbnail_url=row.get("thumbnail_url"),
        country=row.get("country"),
        uploads_playlist=row.get("uploads_playlist"),
        subscriber_count=row.get("subscriber_count"),
        video_count=row.get("video_count"),
        view_count=row.get("view_count"),
        category_id=row.get("category_id"),
        region=row.get("region"),
        is_seed=bool(row.get("is_seed")),
    )


def video_from_row(row: dict) -> Video:
    return Video(
        id=row["id"],
        channel_id=row.get("channel_id") or "",
        title=row.get("title") or "",
        published_at=_as_dt(row.get("published_at")),
        thumbnail_url=row.get("thumbnail_url"),
        duration_seconds=row.get("duration_seconds"),
        is_short=bool(row.get("is_short")),
        category_id=row.get("category_id"),
        region=row.get("region"),
        view_count=row.get("view_count"),
        like_count=row.get("like_count"),
    )


def video_snapshot_from_row(row: dict) -> VideoSnapshot:
    return VideoSnapshot(
        video_id=row["video_id"],
        ts=_as_dt(row.get("ts")),
        view_count=row.get("view_count"),
        like_count=row.get("like_count"),
        comment_count=row.get("comment_count"),
    )


def channel_snapshot_from_row(row: dict) -> ChannelSnapshot:
    return ChannelSnapshot(
        channel_id=row["channel_id"],
        ts=_as_dt(row.get("ts")),
        subscriber_count=row.get("subscriber_count"),
        view_count=row.get("view_count"),
        video_count=row.get("video_count"),
    )


def _group(items, key) -> dict:
    out: dict = {}
    for it in items:
        out.setdefault(getattr(it, key), []).append(it)
    return out


@runtime_checkable
class Database(Protocol):
    def ping(self) -> bool: ...
    def upsert_categories(self, categories: Iterable[Category]) -> int: ...
    def upsert_regions(self, regions: Iterable[Region]) -> int: ...
    def fetch_category_ids(self) -> list[str]: ...
    def fetch_region_ids(self) -> list[str]: ...
    def upsert_channels(self, channels: Iterable[Channel]) -> int: ...
    def upsert_videos(self, videos: Iterable[Video]) -> int: ...
    def insert_channel_snapshots(self, snapshots: Iterable[ChannelSnapshot]) -> int: ...
    def insert_video_snapshots(self, snapshots: Iterable[VideoSnapshot]) -> int: ...
    def purge_older_than(self, cutoff: datetime) -> dict[str, int]: ...


class InMemoryDB:
    """harness 구현 — 삽입 순서를 보존한다 (dict 기본 동작)."""

    def __init__(self) -> None:
        self.categories: dict[str, dict] = {}
        self.regions: dict[str, dict] = {}
        self.channels: dict[str, dict] = {}
        self.videos: dict[str, dict] = {}
        # 스냅샷 PK 는 (id, ts) — 중복 수집이 행을 늘리지 않는다
        self.channel_snapshots: dict[tuple[str, str], dict] = {}
        self.video_snapshots: dict[tuple[str, str], dict] = {}
        self.trend_scores: list[dict] = []
        self.quota_usage: dict[tuple[str, str], dict] = {}

    def ping(self) -> bool:
        return True

    # -- 카테고리/지역 -------------------------------------------------
    def upsert_categories(self, categories: Iterable[Category]) -> int:
        rows = list(categories)
        for c in rows:
            self.categories[c.id] = {
                "id": c.id,
                "name": c.name,
                "weight": c.weight,
                "sort_order": c.sort_order,
            }
        return len(rows)

    def upsert_regions(self, regions: Iterable[Region]) -> int:
        rows = list(regions)
        for r in rows:
            self.regions[r.id] = {"id": r.id, "name": r.name}
        return len(rows)

    def fetch_category_ids(self) -> list[str]:
        return sorted(self.categories, key=lambda k: self.categories[k]["sort_order"])

    def fetch_region_ids(self) -> list[str]:
        return list(self.regions)

    # -- 채널/영상 -----------------------------------------------------
    def upsert_channels(self, channels: Iterable[Channel]) -> int:
        rows = list(channels)
        for ch in rows:
            self.channels[ch.id] = ch.to_row()
        return len(rows)

    def upsert_videos(self, videos: Iterable[Video]) -> int:
        rows = list(videos)
        for v in rows:
            row = v.to_row()
            row["_published_at"] = _require_aware(v.published_at)
            self.videos[v.id] = row
        return len(rows)

    def fetch_channel_ids(self) -> list[str]:
        return list(self.channels)

    def fetch_video_ids(self) -> list[str]:
        return list(self.videos)

    # -- 스냅샷 --------------------------------------------------------
    def insert_channel_snapshots(self, snapshots: Iterable[ChannelSnapshot]) -> int:
        rows = list(snapshots)
        for s in rows:
            row = s.to_row()  # naive datetime 이면 여기서 ValueError
            row["_ts"] = s.ts
            self.channel_snapshots[(s.channel_id, row["ts"])] = row
        return len(rows)

    def insert_video_snapshots(self, snapshots: Iterable[VideoSnapshot]) -> int:
        rows = list(snapshots)
        for s in rows:
            row = s.to_row()
            row["_ts"] = s.ts
            self.video_snapshots[(s.video_id, row["ts"])] = row
        return len(rows)

    def fetch_channel_snapshots(self, channel_id: str) -> list[dict]:
        return [r for (cid, _), r in self.channel_snapshots.items() if cid == channel_id]

    def fetch_video_snapshots(self, video_id: str) -> list[dict]:
        return [r for (vid, _), r in self.video_snapshots.items() if vid == video_id]

    # -- 벌크 조회 (compute 용 — per-id 조회는 N+1 이라 쓰지 않는다) ----------
    def fetch_all_channels(self) -> list[Channel]:
        return [channel_from_row(r) for r in self.channels.values()]

    def fetch_videos_published_since(self, cutoff: datetime) -> list[Video]:
        _require_aware(cutoff)
        return [
            video_from_row(r) for r in self.videos.values() if r["_published_at"] >= cutoff
        ]

    def fetch_video_snapshots_since(self, cutoff: datetime) -> dict[str, list[VideoSnapshot]]:
        _require_aware(cutoff)
        rows = [video_snapshot_from_row(r) for r in self.video_snapshots.values()
                if r["_ts"] >= cutoff]
        return _group(rows, "video_id")

    def fetch_channel_snapshots_since(self, cutoff: datetime) -> dict[str, list[ChannelSnapshot]]:
        _require_aware(cutoff)
        rows = [channel_snapshot_from_row(r) for r in self.channel_snapshots.values()
                if r["_ts"] >= cutoff]
        return _group(rows, "channel_id")

    def publish_trend_scores(self, rows: list[dict]) -> int:
        self.trend_scores = list(rows)  # 원자적 전량 교체 (RPC 와 동일 의미)
        return len(rows)

    def record_quota_usage(self, rows: list[dict]) -> int:
        """(day, endpoint) 누적. 같은 날 여러 번 실행돼도 합산돼야 한다."""
        for r in rows:
            key = (r["day"], r["endpoint"])
            cur = self.quota_usage.get(key, {"day": r["day"], "endpoint": r["endpoint"],
                                             "calls": 0, "units": 0})
            cur["calls"] += r.get("calls", 0)
            cur["units"] += r.get("units", 0)
            self.quota_usage[key] = cur
        return len(rows)

    def fetch_quota_usage(self, day: str) -> list[dict]:
        return [r for (d, _), r in self.quota_usage.items() if d == day]

    def quota_spent_today(self, day: str) -> int:
        return sum(r["units"] for r in self.fetch_quota_usage(day))

    # -- purge ---------------------------------------------------------
    def purge_older_than(self, cutoff: datetime) -> dict[str, int]:
        _require_aware(cutoff)
        deleted: dict[str, int] = {}

        for store, key in (
            ("video_snapshots", self.video_snapshots),
            ("channel_snapshots", self.channel_snapshots),
        ):
            stale = [k for k, r in key.items() if r["_ts"] < cutoff]
            for k in stale:
                del key[k]
            deleted[store] = len(stale)

        stale_videos = [vid for vid, r in self.videos.items() if r["_published_at"] < cutoff]
        for vid in stale_videos:
            del self.videos[vid]
            for k in [k for k in self.video_snapshots if k[0] == vid]:
                del self.video_snapshots[k]  # ON DELETE CASCADE 재현
        deleted["videos"] = len(stale_videos)
        return deleted


class SupabaseRestDB:
    """PostgREST 클라이언트. service_role 키로 쓰기 — 이 키는 서버에만 존재해야 한다."""

    def __init__(self, url: str, service_key: str, timeout: int = 30) -> None:
        self.base = url.rstrip("/")
        self._key = service_key
        self.timeout = timeout

    # -- 내부 ---------------------------------------------------------
    def _headers(self, extra: dict | None = None) -> dict:
        h = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, path: str, **kw):
        import requests

        r = requests.request(
            method,
            f"{self.base}{path}",
            headers=self._headers(kw.pop("headers", None)),
            timeout=self.timeout,
            **kw,
        )
        if not r.ok:
            # 에러 본문에 키가 포함되지 않도록 상태/메시지만 노출한다.
            raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        return r

    def _upsert(self, table_key: str, rows: list[dict], on_conflict: str) -> int:
        if not rows:
            return 0
        self._request(
            "POST",
            f"/rest/v1/{TABLES[table_key]}?on_conflict={on_conflict}",
            json=rows,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
        return len(rows)

    @staticmethod
    def _deleted_count(response) -> int:
        """Content-Range 헤더(`0-4/5` 또는 `*/5`)에서 삭제 건수를 읽는다."""
        rng = response.headers.get("Content-Range", "")
        if "/" in rng:
            tail = rng.split("/")[-1]
            if tail.isdigit():
                return int(tail)
        try:
            return len(response.json())
        except Exception:  # noqa: BLE001
            return 0

    # -- Database 프로토콜 ---------------------------------------------
    def ping(self) -> bool:
        self._request("GET", f"/rest/v1/{TABLES['categories']}?select=id&limit=1")
        return True

    def upsert_categories(self, categories: Iterable[Category]) -> int:
        rows = [
            {"id": c.id, "name": c.name, "weight": c.weight, "sort_order": c.sort_order}
            for c in categories
        ]
        return self._upsert("categories", rows, "id")

    def upsert_regions(self, regions: Iterable[Region]) -> int:
        rows = [{"id": r.id, "name": r.name} for r in regions]
        return self._upsert("regions", rows, "id")

    def fetch_category_ids(self) -> list[str]:
        r = self._request(
            "GET", f"/rest/v1/{TABLES['categories']}?select=id&order=sort_order.asc"
        )
        return [row["id"] for row in r.json()]

    def fetch_region_ids(self) -> list[str]:
        r = self._request("GET", f"/rest/v1/{TABLES['regions']}?select=id&order=id.asc")
        return [row["id"] for row in r.json()]

    def upsert_channels(self, channels: Iterable[Channel]) -> int:
        return self._upsert("channels", [c.to_row() for c in channels], "id")

    def upsert_videos(self, videos: Iterable[Video]) -> int:
        rows = []
        for v in videos:
            _require_aware(v.published_at)
            rows.append(v.to_row())
        return self._upsert("videos", rows, "id")

    def insert_channel_snapshots(self, snapshots: Iterable[ChannelSnapshot]) -> int:
        rows = [s.to_row() for s in snapshots]
        return self._upsert("channel_snapshots", rows, "channel_id,ts")

    def insert_video_snapshots(self, snapshots: Iterable[VideoSnapshot]) -> int:
        rows = [s.to_row() for s in snapshots]
        return self._upsert("video_snapshots", rows, "video_id,ts")

    def fetch_channel_ids(self) -> list[str]:
        r = self._request("GET", f"/rest/v1/{TABLES['channels']}?select=id")
        return [row["id"] for row in r.json()]

    def fetch_video_ids(self) -> list[str]:
        r = self._request("GET", f"/rest/v1/{TABLES['videos']}?select=id")
        return [row["id"] for row in r.json()]

    def fetch_channel_snapshots(self, channel_id: str) -> list[dict]:
        r = self._request(
            "GET",
            f"/rest/v1/{TABLES['channel_snapshots']}?channel_id=eq.{channel_id}&order=ts.asc",
        )
        return r.json()

    def fetch_video_snapshots(self, video_id: str) -> list[dict]:
        r = self._request(
            "GET", f"/rest/v1/{TABLES['video_snapshots']}?video_id=eq.{video_id}&order=ts.asc"
        )
        return r.json()

    # -- 벌크 조회 -----------------------------------------------------
    def _paged(self, path: str, page_size: int = 1000) -> list[dict]:
        """PostgREST 기본 상한(1000행)을 넘겨 전량을 가져온다."""
        out: list[dict] = []
        offset = 0
        while True:
            sep = "&" if "?" in path else "?"
            r = self._request(
                "GET",
                f"{path}{sep}limit={page_size}&offset={offset}",
            )
            batch = r.json()
            out.extend(batch)
            if len(batch) < page_size:
                return out
            offset += page_size

    def fetch_all_channels(self) -> list[Channel]:
        rows = self._paged(f"/rest/v1/{TABLES['channels']}?select=*&order=id.asc")
        return [channel_from_row(r) for r in rows]

    def fetch_videos_published_since(self, cutoff: datetime) -> list[Video]:
        rows = self._paged(
            f"/rest/v1/{TABLES['videos']}?select=*"
            f"&published_at=gte.{encode_ts(cutoff)}&order=id.asc"
        )
        return [video_from_row(r) for r in rows]

    def fetch_video_snapshots_since(self, cutoff: datetime) -> dict[str, list[VideoSnapshot]]:
        rows = self._paged(
            f"/rest/v1/{TABLES['video_snapshots']}?select=*"
            f"&ts=gte.{encode_ts(cutoff)}&order=video_id.asc,ts.asc"
        )
        return _group([video_snapshot_from_row(r) for r in rows], "video_id")

    def fetch_channel_snapshots_since(self, cutoff: datetime) -> dict[str, list[ChannelSnapshot]]:
        rows = self._paged(
            f"/rest/v1/{TABLES['channel_snapshots']}?select=*"
            f"&ts=gte.{encode_ts(cutoff)}&order=channel_id.asc,ts.asc"
        )
        return _group([channel_snapshot_from_row(r) for r in rows], "channel_id")

    def purge_older_than(self, cutoff: datetime) -> dict[str, int]:
        iso = encode_ts(cutoff)  # '+' 를 인코딩하지 않으면 400 — ToS 삭제가 실패한다
        deleted: dict[str, int] = {}
        for table_key, column in PURGE_TARGETS:
            r = self._request(
                "DELETE",
                f"/rest/v1/{TABLES[table_key]}?{column}=lt.{iso}",
                headers={"Prefer": "count=exact,return=minimal"},
            )
            deleted[table_key] = self._deleted_count(r)
        return deleted

    def publish_trend_scores(self, rows: list[dict]) -> int:
        r = self._request("POST", f"/rest/v1/rpc/{PUBLISH_RPC}", json={"rows": rows})
        return int(r.json() or 0)

    def record_quota_usage(self, rows: list[dict]) -> int:
        """일별 쿼터 사용량 누적.

        ⚠️ 원장은 프로세스마다 0에서 시작하므로, 같은 날 여러 번 실행하면 실제 소모를
           알 수 없다 (2026-08-03 실제로 겪었다). 이 표가 그 누적을 보관한다.
           덮어쓰기가 아니라 **합산**해야 하므로 기존 값을 읽어 더한다.
        """
        if not rows:
            return 0
        merged = []
        for r in rows:
            day, ep = r["day"], r["endpoint"]
            cur = self._request(
                "GET",
                f"/rest/v1/{TABLES['quota_usage']}?day=eq.{day}&endpoint=eq.{ep}&select=calls,units",
            ).json()
            base = cur[0] if cur else {"calls": 0, "units": 0}
            merged.append(
                {
                    "day": day,
                    "endpoint": ep,
                    "calls": base["calls"] + r.get("calls", 0),
                    "units": base["units"] + r.get("units", 0),
                }
            )
        return self._upsert("quota_usage", merged, "day,endpoint")

    def fetch_quota_usage(self, day: str) -> list[dict]:
        return self._request(
            "GET", f"/rest/v1/{TABLES['quota_usage']}?day=eq.{day}&select=*"
        ).json()

    def quota_spent_today(self, day: str) -> int:
        return sum(r.get("units", 0) for r in self.fetch_quota_usage(day))


def get_db(settings: Settings) -> Database:
    if settings.db_mode == "live":
        settings.require_db_credentials()
        return SupabaseRestDB(settings.supabase_url, settings.supabase_service_key)
    return InMemoryDB()
