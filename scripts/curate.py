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
HISTORY_PATH = os.path.join(ROOT, "data", "published_history.json")

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

# '그 나라 맥락' 단락을 작성할 언어 (출처 국가 기준).
# 프랑스→프랑스어, 이탈리아→이탈리아어, 영국·미국→영어. 독일(화)은 제외 → 한국어 유지.
CONTEXT_LANG = {
    "monday":    "프랑스어(français)",
    "wednesday": "이탈리아어(italiano)",
    "thursday":  "영어(English)",
    "friday":    "영어(English)",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 주차 정보
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_week_info():
    """토요일 실행 기준: 다음 주 월~금 날짜 반환"""
    now = datetime.now(timezone.utc)
    days_to_next_monday = (7 - now.weekday()) % 7
    if days_to_next_monday == 0:
        days_to_next_monday = 7
    next_monday = (now + timedelta(days=days_to_next_monday)).date()
    next_friday  = next_monday + timedelta(days=4)
    year, week, _ = next_monday.isocalendar()
    if next_monday.month != next_friday.month:
        label = f"{year}년 {next_monday.month}월 {next_monday.day}일 — {next_friday.month}월 {next_friday.day}일"
    else:
        label = f"{year}년 {next_monday.month}월 {next_monday.day}일 — {next_friday.day}일"
    return f"{year}-W{week:02d}", label


def load_published_urls() -> set:
    """기존 news.json에서 이미 발행된 URL 목록 반환 (중복 방지)"""
    if not os.path.exists(NEWS_PATH):
        return set()
    with open(NEWS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {item["sourceUrl"] for item in data.get("items", []) if item.get("sourceUrl")}


def load_recent_tags(weeks: int = 8) -> list:
    """최근 N주 발행된 태그 목록 반환 (주제 중복 방지용)"""
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        history = json.load(f)
    entries = history.get("weeks", [])
    recent = entries[-weeks:] if len(entries) > weeks else entries
    tags = []
    for entry in recent:
        tags.extend(entry.get("tags", []))
    return list(dict.fromkeys(tags))  # 중복 제거, 순서 유지


def save_tags_to_history(week_id: str, items: list):
    """이번 주 발행 태그를 history에 누적 저장 (최대 26주 보관)"""
    history = {"weeks": []}
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            history = json.load(f)

    all_tags = [t for item in items for t in item.get("tags", [])]
    weeks = history.get("weeks", [])

    for i, entry in enumerate(weeks):
        if entry["week"] == week_id:
            weeks[i] = {"week": week_id, "tags": all_tags}
            break
    else:
        weeks.append({"week": week_id, "tags": all_tags})

    history["weeks"] = weeks[-26:]

    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 피드 로딩
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_feeds_for_day(sources: list, day: str, published_urls: set = None) -> list:
    """해당 요일 소스의 피드 항목 전체를 반환. published_urls에 있는 항목은 제외."""
    if published_urls is None:
        published_urls = set()
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
            if item.get("url") in published_urls:
                continue
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


def build_user_prompt(day: str, items: list, recent_tags: list = None) -> str:
    items_block = ""
    for i, item in enumerate(items):
        items_block += (
            f"\n[{i+1}] 소스: {item['source']}\n"
            f"제목: {item['title']}\n"
            f"설명: {item['description']}\n"
            f"URL: {item['url']}\n"
            f"날짜: {item['date']}\n---"
        )

    avoid_section = ""
    if recent_tags:
        avoid_section = (
            f"\n## 최근 8주간 이미 다룬 주제·태그 (이와 동일하거나 유사한 주제 선택 금지)\n"
            f"{', '.join(recent_tags)}\n"
            f"→ 위 태그와 겹치는 철학자·개념·사회현상은 선택하지 마세요. 다른 주제를 우선하세요.\n"
        )

    lang = CONTEXT_LANG.get(day)
    if lang:
        context_instruction = (
            f"[그 나라 맥락] **이 단락만은 반드시 {lang}로 작성합니다.** "
            f"한국어를 한 글자도 섞지 말고 전체를 {lang} 원문으로 쓰되, "
            f"A2(초급) 수준의 짧고 쉬운 문장만 사용한다. "
            f"해당 철학이 나온 나라에서 이 현상이 어떻게 나타나는지, "
            f"그 나라 문화·사회가 이 질문을 어떻게 다루는지 4~5문장으로 서술하고, "
            f"구체적 사례나 문화적 태도를 담는다. "
            f"맨 앞에 그 언어로 된 짧은 헤더 라벨을 붙인다(예: 프랑스→ En France, 이탈리아→ In Italia, 영국→ In Britain, 미국→ In America). "
            f"JSON 이스케이프 오류를 피하기 위해 큰따옴표(\") 대신 작은따옴표나 기예메(« »)를 사용한다."
        )
    else:
        context_instruction = (
            "[그 나라 맥락] 해당 철학이 나온 나라에서 이 현상이 어떻게 나타나는지, "
            "그 나라 문화·사회가 이 질문을 어떻게 다루는지 4~5문장으로 한국어로 서술. "
            "한국과 다른 결을 보여주는 구체적 사례나 문화적 태도를 담는다."
        )

    return f"""{DAY_LABELS[day]} 항목 {len(items)}개 중 가장 적합한 3개를 선택하고 한국어 요약을 작성하세요.
{avoid_section}

각 항목은 다음 구조로 작성합니다:
- title: 한국어 제목 (원제목을 번역하거나 핵심을 재구성, 30자 이내)
- summary: 한 줄 요약 (독자의 호기심을 자극, 40~60자)
- detail: 본문. 아래 순서로 작성:
    [현상/질문] "왜 우리는 ~하는가?" 형식으로 구체적 일상 장면·사회현상을 독자가 생생하게 떠올릴 수 있도록 5~7문장으로 묘사. 장면의 디테일, 감각, 감정까지 담아 독자를 그 상황 안으로 끌어들인다.
    [철학적 해석] 현상과 자연스럽게 연결되는 철학자·개념을 소개하고, 그 철학이 이 현상을 어떻게 다르게 보게 해주는지 5~7문장으로 서술. 개념 설명에 그치지 않고 독자가 "아, 그래서 이런 거였구나"라고 느낄 수 있도록 현상과의 연결을 충분히 풀어낸다.
    {context_instruction}
    총 1,500~2,000자 (단, '그 나라 맥락' 단락이 외국어인 경우 그 단락은 분량 제한 없이 A2 수준으로 짧게)
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


_VALID_ESCAPES = set('"\\/bfnrtu')


def _fix_string_escapes(text: str) -> str:
    """JSON 문자열 값 내부의 리터럴 제어문자/잘못된 backslash escape를 정리.
    - 문자열 내부 리터럴 줄바꿈/탭은 \\n/\\r/\\t로 변환
    - "\\X" 형태에서 X가 유효한 escape 문자가 아니면 backslash를 \\\\로 이스케이프
    구조적 줄바꿈은 건드리지 않는다.
    """
    result = []
    in_string = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if not in_string:
            if ch == '"':
                in_string = True
            result.append(ch)
            i += 1
            continue
        # in_string
        if ch == '"':
            in_string = False
            result.append(ch)
            i += 1
        elif ch == '\\':
            nxt = text[i + 1] if i + 1 < n else ''
            if nxt in _VALID_ESCAPES:
                result.append(ch)
                result.append(nxt)
                i += 2
            else:
                # 잘못된 escape (\C, \', \k 등): backslash를 두 개로 이스케이프
                result.append('\\\\')
                i += 1
        elif ch == '\n':
            result.append('\\n')
            i += 1
        elif ch == '\r':
            result.append('\\r')
            i += 1
        elif ch == '\t':
            result.append('\\t')
            i += 1
        else:
            result.append(ch)
            i += 1
    return ''.join(result)


def extract_json(text: str) -> dict:
    """응답에서 JSON 블록 추출. 파싱 실패 시 문자열 내부 제어문자/잘못된 escape를 정리 후 재시도."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_fix_string_escapes(text))


def curate_day(client: anthropic.Anthropic, day: str, items: list, recent_tags: list = None) -> list:
    """Claude API로 해당 요일 상위 3개 선택 + 한국어 요약 반환. JSON 파싱 실패 시 1회 재시도."""
    messages = [{"role": "user", "content": build_user_prompt(day, items, recent_tags)}]

    for attempt in range(2):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        raw = response.content[0].text
        try:
            result = extract_json(raw)
            break
        except json.JSONDecodeError as e:
            if attempt == 0:
                print(f"    [RETRY] JSON 파싱 실패({e}), 재시도...")
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": (
                    "JSON 파싱 오류가 발생했습니다. "
                    "문자열 내부의 줄바꿈은 반드시 \\n으로 이스케이프하고, "
                    "따옴표는 \\'로 이스케이프한 올바른 JSON만 다시 출력하세요."
                )})
            else:
                raise

    result  = result
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
# JSON 유효성 검사 및 자동 수정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _validate_and_fix_json(path: str):
    """저장된 JSON 파일을 검증하고, 이스케이프 누락된 따옴표가 있으면 자동 수정한다."""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    try:
        json.loads(content)
        return  # 정상
    except json.JSONDecodeError as first_err:
        print(f"[경고] JSON 유효성 오류 감지: {first_err}")

    fixed = 0
    for _ in range(50):
        try:
            json.loads(content)
            break
        except json.JSONDecodeError as e:
            bad = e.pos - 1
            if 0 <= bad < len(content) and content[bad] == '"':
                content = content[:bad] + '\\"' + content[bad + 1:]
                fixed += 1
            else:
                print(f"[오류] 자동 수정 불가 (pos={e.pos}, char={repr(content[e.pos:e.pos+1])})")
                sys.exit(1)
    else:
        print("[오류] 50회 시도 후에도 JSON 수정 실패")
        sys.exit(1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  → JSON 자동 수정: 따옴표 {fixed}개 이스케이프 처리됨")


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

    # 멱등성: 같은 주차가 이미 발행되어 있으면, 빠진 요일만 보충 큐레이션한다.
    # (FORCE=1이면 전부 재생성. 모든 요일 완비 + FORCE 없음이면 스킵)
    existing_items = []
    days_to_run = list(DAYS)
    force = bool(os.environ.get("FORCE"))
    if not force:
        try:
            with open(NEWS_PATH, encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("week") == week_id:
                existing_items = existing.get("items", [])
                existing_days = {it.get("day") for it in existing_items}
                missing = [d for d in DAYS if d not in existing_days]
                if not missing:
                    print(f"이미 {week_id} 모든 요일 발행됨 — 건너뜁니다. (재생성하려면 FORCE=1)")
                    return
                days_to_run = missing
                print(f"이미 {week_id} 일부 발행됨. 빠진 요일 보충: {missing}\n")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    published_urls = load_published_urls()
    if published_urls:
        print(f"기존 발행 URL {len(published_urls)}개 제외\n")

    recent_tags = load_recent_tags(weeks=8)
    if recent_tags:
        print(f"최근 8주 발행 태그 {len(recent_tags)}개 로드 (주제 중복 방지)\n")

    new_items = []

    for day in days_to_run:
        print(f"[{DAY_LABELS[day]}] 피드 로딩...", flush=True)
        day_items = load_feeds_for_day(sources, day, published_urls)

        if not day_items:
            print(f"  → 피드 없음, 건너뜀\n")
            continue

        print(f"  → {len(day_items)}개 항목 검토 중...", flush=True)
        try:
            curated = curate_day(client, day, day_items, recent_tags)
            prefix  = DAY_PREFIX[day]
            for i, item in enumerate(curated, start=1):
                item["id"] = f"{prefix}-{i:02d}"
            new_items.extend(curated)
            titles = [c["title"] for c in curated]
            print(f"  → 선택: {titles}\n")
        except Exception as e:
            print(f"  → 큐레이션 실패: {e}\n")

    if not new_items:
        print("큐레이션된 항목이 없습니다. 기존 news.json을 유지합니다.")
        sys.exit(1)

    # 보충 모드면 기존 + 신규 병합 후 요일 순으로 정렬, 전체 모드면 신규만
    if existing_items and not force:
        day_order = {d: i for i, d in enumerate(DAYS)}
        merged = existing_items + new_items
        merged.sort(key=lambda it: day_order.get(it.get("day"), 99))
        all_items = merged
    else:
        all_items = new_items

    news = {
        "week":       week_id,
        "weekLabel":  week_label,
        "theme":      "",   # 운영자가 직접 설정
        "curatedAt":  datetime.now(timezone.utc).isoformat(),
        "items":      all_items,
    }

    with open(NEWS_PATH, "w", encoding="utf-8") as f:
        json.dump(news, f, ensure_ascii=False, indent=2)

    _validate_and_fix_json(NEWS_PATH)
    save_tags_to_history(week_id, all_items)
    print(f"완료: {len(all_items)}개 항목 → data/news.json 저장 / 태그 히스토리 갱신")


if __name__ == "__main__":
    main()
