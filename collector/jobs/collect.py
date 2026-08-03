# -*- coding: utf-8 -*-
"""수집 파이프라인 — 시드 채널의 통계·새 영상을 스냅샷으로 적재 (SPEC FR-6).

## 쿼터 설계 (이 프로젝트가 성립하는 이유)

    채널 통계   channels.list  1u / 50개   → 90채널 = 2u
    새 영상 감지 채널 RSS        **0u**      → 90요청, API 아님
    영상 통계   videos.list    1u / 50개   → ~300영상 = 6u
    ------------------------------------------------------
    1회 약 10u · 하루 3회 = 30u  (일 상한 10,000u)

발굴(search.list, 100u/회)은 이 잡에서 하지 않는다 — `jobs/refill_seeds` 소관이다.

## 왜 이미 추적 중인 영상을 매번 다시 찍는가

속도(velocity)는 **스냅샷 2개 이상**이 있어야 계산된다. 새 영상만 찍으면 모든 영상이
영원히 스냅샷 1개짜리로 남아 보드가 비어버린다. 그래서 추적 창(TRACK_DAYS) 안의
기존 영상 + RSS 신규를 합쳐 매 회차 다시 찍는다.

실행:
  python -m jobs.collect
  python -m jobs.collect --dry-run
"""
import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from core.config import Settings, Taxonomy, load_env_file, load_seeds, load_taxonomy
from core.db import get_db
from core.models import Video, utcnow
from core.quota import QuotaExceeded, QuotaLedger
from engine.classifier import classify_text
from sources.rss_watcher import get_rss_watcher
from sources.yt_client import get_youtube_client

# 추적 창. 지수 산출은 영상 나이 7일 / 속도 구간 48h 를 쓰므로 여유를 둔다.
# 보관 정책(30일) 안이어야 한다.
TRACK_DAYS = 14

RSS_DELAY = 0.25  # 공공 피드 예의 (90채널 × 0.25s ≈ 23초)


@dataclass
class CollectResult:
    channels: int = 0
    channel_snapshots: int = 0
    videos: int = 0
    video_snapshots: int = 0
    rss_channels: int = 0
    rss_new_videos: int = 0
    quota_units: int = 0
    quota_rows: list[dict] = field(default_factory=list)
    quota_exhausted: bool = False
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"채널 {self.channels}",
            f"채널스냅샷 {self.channel_snapshots}",
            f"영상 {self.videos}",
            f"영상스냅샷 {self.video_snapshots}",
            f"RSS 신규 {self.rss_new_videos}",
            f"쿼터 {self.quota_units}u",
        ]
        if self.quota_exhausted:
            parts.append("⚠️쿼터소진")
        if self.errors:
            parts.append(f"오류 {len(self.errors)}")
        return " · ".join(parts)


def select_video_ids(tracked_ids: list[str], fresh_ids: list[str]) -> list[str]:
    """이번 회차에 통계를 조회할 영상 id — 기존 추적분 + RSS 신규, 중복 제거·순서 고정."""
    return sorted(dict.fromkeys([*tracked_ids, *fresh_ids]))


def classify_video(video: Video, channel_category: str | None, taxonomy: Taxonomy) -> str | None:
    """영상 카테고리. 제목이 말해주면 그것을, 아니면 채널 카테고리를 쓴다.

    제목만으로 판정되지 않는 영상이 많다("7월 정산" 같은). 미분류로 버리면 보드가 얇아지므로
    채널 카테고리로 떨어뜨린다 — 채널은 seeds 에서 검증을 거친 배치다.
    """
    cid, _ = classify_text(video.title, taxonomy)
    return cid or channel_category


def collect(db, client, watcher, taxonomy: Taxonomy, seeds: dict[str, list[str]],
            now: datetime, rss_delay: float = 0.0) -> CollectResult:
    """수집 1회. 쿼터가 바닥나면 예외로 죽지 않고 **수집한 만큼 저장하고 멈춘다**."""
    res = CollectResult()
    cutoff = now - timedelta(days=TRACK_DAYS)

    # 채널 → 카테고리 (seeds.yaml 이 진실)
    category_of: dict[str, str] = {}
    for category_id, channel_ids in seeds.items():
        for cid in channel_ids:
            category_of.setdefault(cid, category_id)
    if not category_of:
        return res

    # --- 1. 채널 통계 (배치 50, 1u) --------------------------------------
    try:
        fetched = client.fetch_channels(list(category_of))
    except QuotaExceeded:
        res.quota_exhausted = True
        fetched = []

    channels = []
    for f in fetched:
        f.channel.category_id = category_of.get(f.channel.id)
        f.channel.is_seed = True
        channels.append(f.channel)
    if channels:
        res.channels = db.upsert_channels(channels)
        res.channel_snapshots = db.insert_channel_snapshots([f.snapshot for f in fetched])

    # --- 2. RSS 로 새 영상 감지 (쿼터 0) ---------------------------------
    fresh_ids: list[str] = []
    for cid in category_of:
        try:
            feed = watcher.fetch(cid)
        except Exception as e:  # noqa: BLE001 - 피드 하나가 죽어도 수집은 계속된다
            res.errors.append(f"rss:{cid}:{type(e).__name__}")
            continue
        res.rss_channels += 1
        for entry in feed.entries:
            if entry.published_at >= cutoff:
                fresh_ids.append(entry.video_id)
        if rss_delay:
            time.sleep(rss_delay)
    res.rss_new_videos = len(set(fresh_ids))

    # --- 3. 영상 통계 (배치 50, 1u) --------------------------------------
    tracked = [v.id for v in db.fetch_videos_published_since(cutoff)]
    video_ids = select_video_ids(tracked, fresh_ids)
    if video_ids and not res.quota_exhausted:
        try:
            vfetched = client.fetch_videos(video_ids)
        except QuotaExceeded:
            res.quota_exhausted = True
            vfetched = []

        videos, snaps = [], []
        for f in vfetched:
            if f.video.published_at < cutoff:
                continue  # 추적 창 밖 — 저장하지 않는다 (보관 정책과도 맞는다)
            f.video.category_id = classify_video(
                f.video, category_of.get(f.video.channel_id), taxonomy
            )
            videos.append(f.video)
            snaps.append(f.snapshot)
        if videos:
            res.videos = db.upsert_videos(videos)
            res.video_snapshots = db.insert_video_snapshots(snaps)

    # --- 4. 쿼터 사용량 기록 ---------------------------------------------
    day = now.date().isoformat()
    res.quota_units = client.quota.spent
    res.quota_rows = [
        {"day": day, "endpoint": ep, "calls": client.quota.calls[ep],
         "units": client.quota.units[ep]}
        for ep in sorted(client.quota.calls)
    ]
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="쿼터 계획만 출력")
    ap.add_argument("--no-purge", action="store_true", help="보관 정책 집행을 건너뜀")
    args = ap.parse_args()

    load_env_file()
    settings = Settings.from_env()
    tax = load_taxonomy()
    seed_map = {cid: [s.channel_id for s in entries if s.channel_id]
                for cid, entries in load_seeds().items()}
    n_channels = sum(len(v) for v in seed_map.values())

    print(f"모드: YT_MODE={settings.yt_mode} DB_MODE={settings.db_mode}")
    print(f"시드 채널 {n_channels}개 · 추적 창 {TRACK_DAYS}일")
    print(f"예상 쿼터: channels.list {-(-n_channels // 50)}u + videos.list ~10u (RSS 0u)")

    if args.dry_run:
        print("dry-run — 호출하지 않음")
        return 0

    db = get_db(settings)
    quota = QuotaLedger.from_settings(settings)
    now = utcnow()

    res = collect(
        db=db,
        client=get_youtube_client(settings, quota=quota),
        watcher=get_rss_watcher(settings),
        taxonomy=tax,
        seeds=seed_map,
        now=now,
        rss_delay=RSS_DELAY,
    )
    print(f"\n수집 결과: {res.summary()}")
    for e in res.errors[:10]:
        print(f"  ⚠️ {e}")

    if res.quota_rows and hasattr(db, "record_quota_usage"):
        db.record_quota_usage(res.quota_rows)
        print(f"쿼터 기록: {len(res.quota_rows)}행")

    if not args.no_purge:
        cutoff = now - timedelta(days=settings.retention_days)
        deleted = db.purge_older_than(cutoff)
        print(f"보관 정책: {sum(deleted.values())}건 삭제 ({settings.retention_days}일)")

    # 쿼터 소진은 경고지 실패가 아니다 — 다음 주기에 이어서 수집한다
    return 0 if res.channel_snapshots or res.video_snapshots else 1


if __name__ == "__main__":
    sys.exit(main())
