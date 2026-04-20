"""
플라뇌르 — AI 큐레이션 스크립트
data/feeds/*.json 을 읽어 Claude API로 요일별 상위 3개를 선택하고
한국어 요약(summary + detail)을 작성한 뒤 data/news.json 에 저장합니다.

실행: ANTHROPIC_API_KEY 환경변수 필요
      python scripts/curate.py
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import anthropic

ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "data", "sources.json")
FEEDS_DIR    = os.path.join(ROOT, "data", "feeds")
NEWS_PATH    = os.path.join(ROOT, "data", "news.json")

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]
DAY_LABELS = {
    "monday":    "월요일",
    "tuesday":   "화요일",
    "wednesday": "수요일",
    "thursday":  "목요일",
    "friday":    "금요일",
}
DAY_PREFIX = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 주차 정보
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_week_info():
    now    = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    monday = now - timedelta(days=now.weekday())
    friday = monday + timedelta(days=4)
    label  = f"{year}년 {monday.month}월 {monday.day}일 — {friday.day}일"
    return f"{year}-W{week:02d}", label


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 피드 로딩
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_feeds_for_day(sources: list, day: str) -> list:
    """해당 요일 소스의 피드 항목 전체를 반환."""
    items = []
    for src in sources:
        if src["day"] != day:
            continue
        feed_path = os.path.join(FEEDS_DIR, f"{src['id']}.json")
        if not os.path.exists(feed_path):
            print(f"    [SKIP] {src['id']} — 캐시 없음")
            continue
        with open(feed_path, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("items", [])[:6]:    # 소스당 최대 6개 (소스 수 증가로 조정)
            items.append({
                "source":       src["name"],
                "channelUrl":   src["url"],
                "country":      src["country"],
                "countryLabel": src["countryLabel"],
                "flag":         src["flag"],
                "day":          day,
                "title":        item.get("title", "").strip(),
                "description":  item.get("description", "").strip()[:400],
                "url":          item.get("url", ""),
                "date":         item.get("date", ""),
                "thumbnail":    item.get("thumbnail", ""),
            })
    return items


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Claude 큐레이션
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYSTEM_PROMPT = """당신은 철학 큐레이션 사이트 '플라뇌르(Flâneur)'의 큐레이터입니다.
플라뇌르는 보들레르·벤야민의 산책자 개념에서 출발해, 일상과 사회현상을 철학적으로 관찰하는 사이트입니다.

## 선택 기준 (우선순위 순)
1. 일상·사회현상 밀접도 (가장 중요): 지금 실제로 사람들이 경험하는 구체적 장면·사회이슈. 독자가 "나도 이런 적 있는데"라고 즉각 공감할 수 있는가.
2. 철학적 연결의 자연스러움: 철학적 시각이 억지스럽지 않고 현상을 더 잘 이해하게 해주는가.
3. 플라뇌르 정체성: 거창한 주제보다 스쳐 지나가는 일상 장면·습관·관계에서 철학적 질문을 발견하는 시선.
4. 새로운 시각: 통념을 뒤집거나 익숙한 현상을 전혀 다른 각도로 보는 콘텐츠.
5. 중복 최소화: 같은 철학자·개념·사회현상 반복 금지.

## 글쓰기 원칙
- 반드시 사회현상·일상 장면이 먼저, 철학은 그 다음
- 철학자 이름·개념에서 출발하지 않음
- 한국적 상황·한국 독자 관점은 포함하지 않음 (운영자가 에세이에서 직접 연결)
- 그 나라 맥락 포함

## 응답
반드시 JSON만 반환. 다른 텍스트 없이."""


def build_user_prompt(day: str, items: list) -> str:
    items_block = ""
    for i, item in enumerate(items):
        items_block += (
            f"\n[{i+1}] 소스: {item['source']}\n"
            f"제목: {item['title']}\n"
            f"설명: {item['description']}\n"
            f"URL: {item['url']}\n"
            f"날짜: {item['date']}\n---"
        )

    return f"""{DAY_LABELS[day]} 항목 {len(items)}개 중 가장 적합한 3개를 선택하고 한국어 요약을 작성하세요.

각 항목은 다음 구조로 작성합니다:
- title: 한국어 제목 (원제목을 번역하거나 핵심을 재구성, 30자 이내)
- summary: 한 줄 요약 (독자의 호기심을 자극, 40~60자)
- detail: 본문. 아래 순서로 작성:
    [현상/질문] "왜 우리는 ~하는가?" 형식으로 구체적 일상 장면·사회현상 3~4문장
    [철학적 해석] 현상과 자연스럽게 연결되는 철학자·개념 3~4문장
    [그 나라 맥락] 해당 철학이 나온 나라에서 이 현상이 어떻게 나타나는지 2~3문장
    총 500~700자
- tags: 핵심 키워드 3개 (한국어)

## 항목 목록
{items_block}

## 응답 형식 (JSON만)
{{
  "selected": [
    {{
      "index": 1,
      "title": "...",
      "summary": "...",
      "detail": "...",
      "tags": ["...", "...", "..."]
    }}
  ]
}}"""


def extract_json(text: str) -> dict:
    """응답에서 JSON 블록 추출."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return json.loads(text)


def curate_day(client: anthropic.Anthropic, day: str, items: list) -> list:
    """Claude API로 해당 요일 상위 3개 선택 + 한국어 요약 반환."""
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(day, items)}],
    )

    result  = extract_json(response.content[0].text)
    curated = []

    for sel in result.get("selected", []):
        idx = int(sel["index"]) - 1
        if not (0 <= idx < len(items)):
            print(f"    [WARN] 잘못된 index {sel['index']}, 건너뜀")
            continue
        orig = items[idx]
        curated.append({
            "day":          day,
            "dayLabel":     DAY_LABELS[day],
            "country":      orig["country"],
            "countryLabel": orig["countryLabel"],
            "source":       orig["source"],
            "sourceUrl":    orig["url"],          # 원본 영상/글 URL
            "channelUrl":   orig["channelUrl"],   # 채널/사이트 URL
            "thumbnail":    orig.get("thumbnail", ""),
            "title":        sel["title"],
            "summary":      sel["summary"],
            "detail":       sel["detail"],
            "tags":         sel.get("tags", []),
            "originalTitle": orig["title"],
        })

    return curated


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("오류: ANTHROPIC_API_KEY 환경변수가 없습니다.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    with open(SOURCES_PATH, encoding="utf-8") as f:
        sources = json.load(f)["sources"]

    week_id, week_label = get_week_info()
    print(f"주차: {week_id} ({week_label})\n")

    all_items = []

    for day in DAYS:
        print(f"[{DAY_LABELS[day]}] 피드 로딩...", flush=True)
        day_items = load_feeds_for_day(sources, day)

        if not day_items:
            print(f"  → 피드 없음, 건너뜀\n")
            continue

        print(f"  → {len(day_items)}개 항목 검토 중...", flush=True)
        try:
            curated = curate_day(client, day, day_items)
            prefix  = DAY_PREFIX[day]
            for i, item in enumerate(curated, start=1):
                item["id"] = f"{prefix}-{i:02d}"
            all_items.extend(curated)
            titles = [c["title"] for c in curated]
            print(f"  → 선택: {titles}\n")
        except Exception as e:
            print(f"  → 큐레이션 실패: {e}\n")

    if not all_items:
        print("큐레이션된 항목이 없습니다. 기존 news.json을 유지합니다.")
        sys.exit(1)

    news = {
        "week":       week_id,
        "weekLabel":  week_label,
        "theme":      "",   # 운영자가 직접 설정
        "curatedAt":  datetime.now(timezone.utc).isoformat(),
        "items":      all_items,
    }

    with open(NEWS_PATH, "w", encoding="utf-8") as f:
        json.dump(news, f, ensure_ascii=False, indent=2)

    print(f"완료: {len(all_items)}개 항목 → data/news.json 저장")


if __name__ == "__main__":
    main()
