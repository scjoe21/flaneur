#!/usr/bin/env python3
"""
매주 토요일 실행: 다음 주 월~금 뉴스 자동 생성
1. data/feeds/{id}.json 캐시에서 우선순위 상위 항목 선택 (요일별 3개)
2. Claude API(claude-sonnet-4-6)로 title/summary/detail/tags 생성
3. 주간 테마 생성
4. data/news.json 저장
"""

import json
import os
import sys
import datetime
import pathlib

ROOT = pathlib.Path(__file__).parent.parent
FEEDS_DIR  = ROOT / "data" / "feeds"
SOURCES_FILE = ROOT / "data" / "sources.json"
NEWS_FILE  = ROOT / "data" / "news.json"

# 요일별 선택 개수
ITEMS_PER_DAY = 3

DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday"]
DAY_PREFIX = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri",
}
DAY_LABEL = {
    "monday": "월요일", "tuesday": "화요일", "wednesday": "수요일",
    "thursday": "목요일", "friday": "금요일",
}

WRITING_GUIDE = """당신은 철학 큐레이션 사이트 '플라뇌르(Flâneur)'의 편집자입니다.
플라뇌르는 도시를 유유히 걸으며 일상을 관찰하고 사유하는 사람을 뜻합니다.

글쓰기 원칙:
- 반드시 사회현상·일상 장면이 먼저, 철학은 그 다음
- 철학자 이름이나 개념으로 시작하지 말 것 (예: "에피쿠로스에 따르면..." 금지)
- "왜 우리는 ~하는가?" 형식의 일상적 질문으로 도입
- 한국 독자가 즉각 공감할 수 있는 구체적 장면 제시
- 산책하듯 자연스러운 사유의 흐름, 강의식 금지"""

DETAIL_STRUCTURE = """detail 구조 (총 800~1,200자):
1. 현상/도입 (2~3문장): 지금 사람들이 실제 겪는 장면이나 사회현상
2. 철학적 해석 (3~4문장): 해당 현상을 설명하는 철학자·개념 자연스럽게 연결
3. 반론 또는 심화 (2~3문장): 다른 시각이나 더 깊은 논의
4. 국가 맥락 (1~2문장): 해당 나라 문화에서 이 질문이 어떻게 나타나는지
5. 한국 독자 질문 (1문장): "한국적 질문:" 으로 시작"""


def get_next_week_info():
    """다음 주 월요일 기준 날짜 정보 계산"""
    today = datetime.date.today()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = today + datetime.timedelta(days=days_until_monday)
    next_friday = next_monday + datetime.timedelta(days=4)

    iso = next_monday.isocalendar()
    year, week_num = iso[0], iso[1]

    week_label = (
        f"{year}년 {next_monday.month}월 {next_monday.day}일"
        f" — {next_friday.month}월 {next_friday.day}일"
        if next_monday.month != next_friday.month
        else f"{year}년 {next_monday.month}월 {next_monday.day}일 — {next_friday.day}일"
    )

    return {
        "week": f"{year}-W{week_num:02d}",
        "weekLabel": week_label,
    }


def load_sources():
    """sources.json → {source_id: source_info} 매핑"""
    with open(SOURCES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {s["id"]: s for s in data["sources"]}


def load_feed_items(source_id):
    """캐시된 피드 로드, 없으면 빈 리스트"""
    path = FEEDS_DIR / f"{source_id}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    for item in items:
        item["_source_id"] = source_id
    return items


def select_items_for_day(day_key, source_ids):
    """해당 요일 소스에서 우선순위 상위 ITEMS_PER_DAY개 선택"""
    all_items = []
    for sid in source_ids:
        all_items.extend(load_feed_items(sid))

    # 우선순위 내림차순 정렬 후 URL 중복 제거
    seen_urls = set()
    unique = []
    for item in sorted(all_items, key=lambda x: x.get("priority", 0), reverse=True):
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(item)

    return unique[:ITEMS_PER_DAY]


def generate_item_content(client, raw_item, source_info):
    """Claude API로 단일 항목의 title/summary/detail/tags 생성"""
    import anthropic

    country_label = source_info.get("countryLabel", "")
    source_name   = source_info.get("name", raw_item.get("_source_id", ""))

    prompt = f"""다음 철학 콘텐츠를 플라뇌르 사이트용으로 작성해주세요.

원본 제목: {raw_item.get('title', '')}
원본 설명: {raw_item.get('description', '')[:600]}
출처 URL: {raw_item.get('url', '')}
소스: {source_name} ({country_label})

아래 JSON 형식으로만 응답하세요 (마크다운 코드블록 없이, 순수 JSON만):
{{
  "title": "한국어 제목 (현상·질문 중심, 철학 개념보다 일상 언어 우선, 25자 내외)",
  "summary": "한 줄 요약 (사회현상 먼저 → 철학 연결, 70~90자)",
  "detail": "상세 설명 (800~1200자, 아래 구조 준수)",
  "tags": ["태그1", "태그2", "태그3"]
}}

{DETAIL_STRUCTURE}

국가 맥락은 반드시 {country_label} 기준으로 작성하세요."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1800,
        system=WRITING_GUIDE,
        messages=[{"role": "user", "content": prompt}],
    )

    text = message.content[0].text.strip()

    # JSON 추출 (코드블록이 붙은 경우 대비)
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            stripped = part.strip()
            if stripped.startswith("{") or stripped.startswith("json\n"):
                text = stripped.lstrip("json").strip()
                break

    return json.loads(text)


def generate_theme(client, titles):
    """전체 제목 목록에서 주간 테마 생성"""
    import anthropic

    titles_str = "\n".join(f"- {t}" for t in titles)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": (
                f"다음 이번 주 철학 콘텐츠 제목들을 보고, 이번 주를 관통하는 테마를 한 줄로 만들어주세요.\n"
                f"형식: \"핵심 개념: 부제목 질문\" (예: \"욕망과 절제: 우리는 왜 멈추지 못하는가\")\n"
                f"15~40자, 콜론(:) 포함. 테마 텍스트만 출력하세요.\n\n"
                f"콘텐츠 제목:\n{titles_str}"
            ),
        }],
    )
    return message.content[0].text.strip().strip('"')


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY 환경변수가 없습니다.")
        sys.exit(1)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    sources = load_sources()
    week_info = get_next_week_info()
    print(f"생성 대상: {week_info['week']} ({week_info['weekLabel']})")

    # 요일별 소스 매핑 (sources.json의 day 필드 기준)
    day_to_sources: dict[str, list[str]] = {}
    for sid, info in sources.items():
        day = info.get("day")
        if day in DAY_ORDER:
            day_to_sources.setdefault(day, []).append(sid)

    items = []
    all_titles = []
    total_api_calls = 0

    for day_key in DAY_ORDER:
        source_ids = day_to_sources.get(day_key, [])
        if not source_ids:
            print(f"  {day_key}: 소스 없음, 스킵")
            continue

        raw_items = select_items_for_day(day_key, source_ids)
        if not raw_items:
            print(f"  {day_key}: 캐시된 피드 없음, 스킵")
            continue

        print(f"  {DAY_LABEL[day_key]}: {len(raw_items)}개 항목 선택")

        for idx, raw_item in enumerate(raw_items):
            title_preview = raw_item.get("title", "")[:40]
            print(f"    [{idx+1}/{len(raw_items)}] {title_preview}...")

            source_id = raw_item.get("_source_id", source_ids[0])
            source_info = sources.get(source_id, {})

            try:
                generated = generate_item_content(client, raw_item, source_info)
                total_api_calls += 1
            except Exception as e:
                print(f"    경고: 생성 실패 ({e}), 스킵")
                continue

            item = {
                "id": f"{DAY_PREFIX[day_key]}-{idx+1:02d}",
                "day": day_key,
                "dayLabel": DAY_LABEL[day_key],
                "country": source_info.get("country", ""),
                "countryLabel": source_info.get("countryLabel", ""),
                "source": source_info.get("name", source_id),
                "sourceUrl": raw_item.get("url", source_info.get("url", "")),
                "title": generated.get("title", raw_item.get("title", "")),
                "summary": generated.get("summary", ""),
                "detail": generated.get("detail", ""),
                "tags": generated.get("tags", []),
            }
            items.append(item)
            all_titles.append(item["title"])

    if not items:
        print("ERROR: 생성된 항목이 없습니다. 피드 캐시를 확인하세요.")
        sys.exit(1)

    # 주간 테마 생성
    print(f"\n주간 테마 생성 중... (총 제목 {len(all_titles)}개)")
    try:
        theme = generate_theme(client, all_titles)
        total_api_calls += 1
    except Exception as e:
        print(f"  경고: 테마 생성 실패 ({e}), 기본값 사용")
        theme = "이번 주의 철학적 사유"

    news = {
        "week": week_info["week"],
        "weekLabel": week_info["weekLabel"],
        "theme": theme,
        "items": items,
    }

    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(news, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {len(items)}개 항목, Claude API {total_api_calls}회 호출")
    print(f"테마: {theme}")
    print(f"저장: {NEWS_FILE}")


if __name__ == "__main__":
    main()
