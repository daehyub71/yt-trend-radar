# -*- coding: utf-8 -*-
"""config/categories.yaml → DB 동기화.

카테고리/지역의 단일 진실은 YAML 이고, DB 테이블은 그 사본이다 (웹이 이름을 읽기 위함).
YAML 을 고친 뒤 이 잡을 돌리면 반영된다. 삭제는 하지 않는다 —
없어진 카테고리는 참조 무결성 때문에 수동 확인이 필요하다.

실행:  python -m jobs.sync_config
"""
import sys

from core.config import Settings, load_env_file, load_taxonomy
from core.db import get_db


def main() -> int:
    load_env_file()
    settings = Settings.from_env()
    tax = load_taxonomy()
    db = get_db(settings)

    print(f"모드: DB_MODE={settings.db_mode}")
    n_cat = db.upsert_categories(tax.categories)
    n_reg = db.upsert_regions(tax.regions)
    print(f"  카테고리 {n_cat}건, 지역 {n_reg}건 업서트")

    ids = db.fetch_category_ids()
    print(f"  DB 카테고리: {ids}")
    print(f"  DB 지역    : {db.fetch_region_ids()}")

    missing = [c.id for c in tax.categories if c.id not in ids]
    if missing:
        print(f"  ⚠️ 반영되지 않은 카테고리: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
