"""
플라뇌르 — Claude AI 자동 큐레이션 스크립트
data/feeds/ 캐시를 읽어 Claude API로 주간 news.json 자동 생성

실행: python scripts/curate_news.py
환경변수: ANTHROPIC_API_KEY 필요
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEEDS_DIR   = os.path.join(ROOT, "data", "feeds")
NEWS_PATH   = os.path.join(ROOT, "data", "news.json")
SOURCES_PATH = os.path.join(ROOT, "data", "sources.json")

DAY_CONFIG = [
    {"day": "monday",    "dayLabel": "월요일", "country": "france",  "countryLabel": "프랑스",   "flag": "🇫🇷", "sources": ["monsieur-phi", "le-precepteur"]},
    {"day": "tuesday",   "dayLabel": "화요일", "country": "germany", "countryLabel": "독일",     "flag": "🇩🇪", "sources": ["gert-scobel"]},
    {"day": "wednesday", "dayLabel": "수요일", "country": "italy",   "countryLabel": "이탈리아", "flag": "🇮🇹", "sources": ["rick-dufer", "tlon"]},
    {"day": "thursday",  "dayLabel": "목요일", "country": "uk",      "countryLabel": "영국",     "flag": "🇬🇧", "sources": ["philosophy-now", "overthink"]},
    {"day": "friday",    "dayLabel": "금요일", "country": "usa",     "countryLabel": "미국",     "flag": "🇺🇸", "sources": ["daily-stoic", "big-think"]},
]

SYSTEM_PROMPT = """당신은 철학 큐레이션 사이트 '플라뇌르(Flâneur)'의 편집자입니다.

## 플라뇌르 정체성
플라뇌르는 도시를 유유히 걷는 사람처럼 일상의 장면에서 철학적 질문을 발견합니다.
거창한 학술 논문이 아니라, 스쳐 지나가는 일상의 순간에서 "왜 우리는 이렇게 사는가"를 조용히 묻습니다.

## 항목 선택 기준 (중요도 순)
1. 일상·사회현상 밀접도 — 독자가 "아, 나도 이런 적 있는데" 즉각 공감 가능한가
2. 철학적 연결의 자연스러움 — 현상을 해석하는 철학적 시각이 억지스럽지 않은가
3. 플라뇌르 정체성 — 산책하듯 관찰하고 사유하는 톤인가
4. 새로운 시각 — 통념을 뒤집거나 다른 각도로 보게 하는가
5. 중복 최소화 — 같은 철학자·개념·사회현상 반복 금지

## 글쓰기 원칙
반드시 사회현상·일상 장면이 먼저, 철학은 그 다음이다.

❌ 잘못된 예: "에피쿠로스의 쾌락주의에 따르면 진정한 쾌락은 고통의 부재다."
✅ 올바른 예: "우리는 왜 휴대폰을 손에서 놓지 못하는가? 에피쿠로스는 이 질문에 흥미로운 답을 갖고 있다…"

## 각 항목 구성 (현상 → 철학 → 국가맥락)
- title: 현상/질문 중심 한국어 제목 (철학자 이름으로 시작하지 않음)
- summary: 2~3문장. 현상을 먼저 제시 후 철학적 시각 연결
- detail: 400~600자 한국어. 현상(3~4문장) → 철학적 해석(3~4문장) → 해당 국가 맥락(2~3문장)
- tags: 3~5개 한국어 키워드

## 중요
- 한국적 상황·한국 독자 관점은 detail에 포함하지 않음 (운영자가 에세이에서 연결)
- 이번 주 주제는 사전에 설정하지 않음 (선별된 항목에서 자연스럽게 형성됨)
- 소스의 실제 영상/글 제목과 설명을 최대한 반영하여 요약"""


def get_week_info():
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    friday = monday + timedelta(days=4)
    iso = now.isocalendar()
    return {
        "week": f"{iso[0]}-W{iso[1]:02d}",
        "weekLabel": f"{iso[0]}년 {monday.month}월 {monday.day}일 — {friday.month}월 {friday.day}일",
    }


def load_source_urls():
    """sources.json에서 id → url 매핑 반환"""
    with open(SOURCES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {s["id"]: s["url"] for s in data["sources"]}


def load_feed_items(source_ids, max_per_source=10):
    all_items = []
    for sid in source_ids:
        path = os.path.join(FEEDS_DIR, f"{sid}.json")
        if not os.path.exists(path):
            print(f"  [SKIP] {sid} 캐시 없음")
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        items = sorted(data.get("items", []), key=lambda x: x.get("priority", 0), reverse=True)
        for item in items[:max_per_source]:
            all_items.append({
                "sourceId":    sid,
                "sourceName":  data["sourceName"],
                "title":       item["title"],
                "description": item.get("description", "")[:400],
                "url":         item["url"],
                "date":        item.get("date", ""),
                "priority":    item.get("priority", 0),
            })
    return sorted(all_items, key=lambda x: x["priority"], reverse=True)


def call_claude_api(api_key, messages, system):
    """urllib로 Anthropic API 직접 호출 (anthropic 패키지 불필요)"""
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "system": system,
        "messages": messages,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["content"][0]["text"].strip()


def trim_detail_to_80(text):
    """detail 텍스트를 단락 경계에서 원문의 약 80% 길이로 다듬는다."""
    if not text:
        return text
    paras = [p for p in text.split('\n\n') if p.strip()]
    if len(paras) <= 1:
        # 단락이 하나뿐이면 문장 단위로 80% 적용
        target = int(len(text) * 0.80)
        return text[:target].rsplit('。', 1)[0] + '。' if '。' in text[:target] else text[:target]
    target = len(text) * 0.80
    total = 0
    kept = []
    for p in paras:
        if total + len(p) + 2 <= target * 1.05:
            kept.append(p)
            total += len(p) + 2
        else:
            if total >= target * 0.70:
                break
            kept.append(p)
            break
    return '\n\n'.join(kept)


def parse_json_response(text):
    """Claude 응답에서 JSON 배열 추출"""
    # 마크다운 코드블록 제거
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                return json.loads(part)
    # 직접 JSON 파싱 시도
    start = text.find("[")
    end   = text.rfind("]") + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])
    raise ValueError("JSON 배열을 찾을 수 없습니다")


def curate_day(api_key, day_cfg, items, source_urls):
    """하루치 항목을 Claude로 큐레이션"""
    items_text = ""
    for i, item in enumerate(items[:12], 1):
        items_text += (
            f"\n[{i}] 출처: {item['sourceName']} (ID: {item['sourceId']}) | "
            f"날짜: {item['date']} | 점수: {item['priority']}\n"
            f"제목: {item['title']}\n"
            f"설명: {item['description']}\n"
            f"URL: {item['url']}\n"
        )

    user_msg = (
        f"다음은 {day_cfg['flag']} {day_cfg['countryLabel']} ({day_cfg['dayLabel']}) "
        f"소스에서 수집된 최신 항목들입니다.\n{items_text}\n"
        f"위 항목 중 플라뇌르 선택 기준에 가장 부합하는 **3개**를 선별하여 "
        f"한국어 요약을 작성해주세요.\n\n"
        f"다음 JSON 배열 형식으로만 응답하세요 (다른 텍스트 없이):\n"
        f'[\n'
        f'  {{\n'
        f'    "sourceId": "원본 소스 ID",\n'
        f'    "sourceName": "소스 이름",\n'
        f'    "itemUrl": "해당 영상/글 URL",\n'
        f'    "title": "현상 중심 한국어 제목",\n'
        f'    "summary": "2~3문장 요약",\n'
        f'    "detail": "400~600자 상세 설명",\n'
        f'    "tags": ["태그1", "태그2", "태그3"]\n'
        f'  }}\n'
        f']'
    )

    text = call_claude_api(api_key, [{"role": "user", "content": user_msg}], SYSTEM_PROMPT)
    curated = parse_json_response(text)

    # sourceUrl은 채널/사이트 URL로 통일
    for item in curated:
        sid = item.get("sourceId", "")
        item["sourceUrl"] = source_urls.get(sid, item.get("itemUrl", ""))

    return curated


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("오류: ANTHROPIC_API_KEY 환경변수가 없습니다")
        sys.exit(1)

    source_urls = load_source_urls()
    week_info   = get_week_info()

    print(f"플라뇌르 자동 큐레이션 — {week_info['week']} ({week_info['weekLabel']})")
    print("=" * 60)

    all_items   = []
    day_counter = {cfg["day"]: 1 for cfg in DAY_CONFIG}

    for day_cfg in DAY_CONFIG:
        day = day_cfg["day"]
        print(f"\n{day_cfg['flag']} {day_cfg['dayLabel']} 처리 중...", end=" ", flush=True)

        items = load_feed_items(day_cfg["sources"])
        if not items:
            print("피드 없음, 건너뜀")
            continue

        print(f"{len(items)}개 항목 → Claude 큐레이션...", end=" ", flush=True)

        try:
            curated = curate_day(api_key, day_cfg, items, source_urls)
            print(f"완료 ({len(curated)}개 선별)")

            prefix = day[:3]
            for item in curated:
                idx = day_counter[day]
                day_counter[day] += 1
                all_items.append({
                    "id":           f"{prefix}-{idx:02d}",
                    "day":          day,
                    "dayLabel":     day_cfg["dayLabel"],
                    "country":      day_cfg["country"],
                    "countryLabel": day_cfg["countryLabel"],
                    "source":       item.get("sourceName", ""),
                    "sourceUrl":    item.get("sourceUrl", ""),
                    "title":        item.get("title", ""),
                    "summary":      item.get("summary", ""),
                    "detail":       trim_detail_to_80(item.get("detail", "")),
                    "tags":         item.get("tags", []),
                })
        except Exception as e:
            print(f"오류: {e}")
            import traceback; traceback.print_exc()

    if not all_items:
        print("\n오류: 큐레이션된 항목이 없습니다")
        sys.exit(1)

    news = {
        **week_info,
        "theme": "",
        "items": all_items,
    }

    with open(NEWS_PATH, "w", encoding="utf-8") as f:
        json.dump(news, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {len(all_items)}개 항목 → data/news.json 저장")
    print("※ theme 필드는 admin.html에서 직접 설정하거나 비워두면 표시되지 않습니다")


if __name__ == "__main__":
    main()
