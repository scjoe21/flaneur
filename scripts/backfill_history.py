"""
플라뇌르 — 발행 이력 백필 스크립트 (일회성/재실행 가능)

git에 커밋된 모든 과거 data/news.json 버전에서 글 제목·요약·태그를 추출해
data/published_history.json 을 풍부한 형태로 재구성한다.

중복 필터(curate.py)가 과거 글과 대조할 수 있도록, 각 주차에
  { "week", "tags": [...], "articles": [{"title","summary","tags"}] }
구조로 저장한다. (기존 tags-only 항목과 하위 호환)

실행: python scripts/backfill_history.py
"""

import json
import os
import subprocess

ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_REL     = "data/news.json"
HISTORY_PATH = os.path.join(ROOT, "data", "published_history.json")
MAX_WEEKS    = 26


def git(*args) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def week_sort_key(week_id: str):
    # "2026-W25" → (2026, 25)
    try:
        year, wk = week_id.split("-W")
        return (int(year), int(wk))
    except Exception:
        return (0, 0)


def main():
    # news.json 을 건드린 모든 커밋 (최신 → 과거)
    commits = git("log", "--format=%H", "--follow", "--", NEWS_REL).split()

    weeks = {}  # week_id → entry (최신 커밋 우선: 먼저 만난 것 유지)
    for h in commits:
        blob = git("show", f"{h}:{NEWS_REL}")
        if not blob.strip():
            continue
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        wk = data.get("week")
        if not wk or wk in weeks:
            continue
        items = data.get("items", [])
        articles = [
            {
                "title":   (it.get("title") or "").strip(),
                "summary": (it.get("summary") or "").strip(),
                "tags":    it.get("tags", []),
            }
            for it in items
            if (it.get("title") or "").strip()
        ]
        flat_tags = list(dict.fromkeys(t for a in articles for t in a["tags"]))
        weeks[wk] = {"week": wk, "tags": flat_tags, "articles": articles}

    ordered = sorted(weeks.values(), key=lambda e: week_sort_key(e["week"]))
    ordered = ordered[-MAX_WEEKS:]

    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump({"weeks": ordered}, f, ensure_ascii=False, indent=2)

    total_articles = sum(len(e["articles"]) for e in ordered)
    print(f"백필 완료: {len(ordered)}개 주차 / 글 {total_articles}개 → data/published_history.json")
    for e in ordered:
        print(f"  {e['week']}: 글 {len(e['articles'])}개, 태그 {len(e['tags'])}개")


if __name__ == "__main__":
    main()
