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
from collections import Counter
from datetime import datetime, timezone, timedelta

import anthropic

ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "data", "sources.json")
FEEDS_DIR    = os.path.join(ROOT, "data", "feeds")
NEWS_PATH    = os.path.join(ROOT, "data", "news.json")
HISTORY_PATH = os.path.join(ROOT, "data", "published_history.json")

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
DAY_LABELS = {
    "monday":    "월요일",
    "tuesday":   "화요일",
    "wednesday": "수요일",
    "thursday":  "목요일",
    "friday":    "금요일",
    "saturday":  "토요일",
}
DAY_PREFIX = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat",
}

# '그 나라 맥락' 단락을 작성할 언어 (출처 국가 기준).
# 프랑스→프랑스어, 이탈리아→이탈리아어, 영국·미국→영어, 일본(토)→일본어. 독일(화)은 제외 → 한국어 유지.
CONTEXT_LANG = {
    "monday":    "프랑스어(français)",
    "wednesday": "이탈리아어(italiano)",
    "thursday":  "영어(English)",
    "friday":    "영어(English)",
    "saturday":  "일본어(日本語)",
}

# 중복 필터가 과거 글과 대조할 때 거슬러 보는 주차 수.
# (불완전함·신체·침묵 등 반복 테마가 두 달 이상 간격으로 재등장하므로 넉넉히 본다.
#  소스 확대로 후보 풀이 깊어져 더 오래 거슬러 봐도 발행 편수에 무리가 없다.)
HISTORY_LOOKBACK = 16
PER_DAY = 3        # 요일당 기본 발행 편수 (1차 목표)
WEEKLY_TARGET = 18 # 주간 총 발행 편수 (월~토 6일 × 3개, 반드시 채운다)
MAX_PER_DAY = 5    # 보충 시 한 요일에 허용하는 최대 편수 (나라별 3~5개 → 균형 유지)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 주차 정보
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_week_info():
    """토요일 실행 기준: 다음 주 월~토 날짜 반환"""
    now = datetime.now(timezone.utc)
    days_to_next_monday = (7 - now.weekday()) % 7
    if days_to_next_monday == 0:
        days_to_next_monday = 7
    next_monday = (now + timedelta(days=days_to_next_monday)).date()
    next_saturday = next_monday + timedelta(days=5)
    year, week, _ = next_monday.isocalendar()
    if next_monday.month != next_saturday.month:
        label = f"{year}년 {next_monday.month}월 {next_monday.day}일 — {next_saturday.month}월 {next_saturday.day}일"
    else:
        label = f"{year}년 {next_monday.month}월 {next_monday.day}일 — {next_saturday.day}일"
    return f"{year}-W{week:02d}", label


import re

# 철학자 성(姓) 추출 시 무시할 관사·전치사 토큰
_PHIL_STOP = {"the", "von", "van", "der", "den", "de", "del", "della",
              "di", "le", "la", "of", "el", "dos", "da", "san", "saint"}


def philosopher_keys(field: str) -> set:
    """철학자 표기 문자열에서 비교용 정규화 키(주로 성) 집합을 뽑는다.

    '니체 (Friedrich Nietzsche)' → {'nietzsche'} 처럼 라틴 표기가 있으면 마지막 토큰(성)을 쓴다.
    라틴 표기가 없으면 한글/원어 표기를 공백 제거해 그대로 키로 쓴다.
    여러 철학자를 '/·,;·&·그리고'로 나눠 각각 키를 만든다.
    """
    keys = set()
    if not field:
        return keys
    for part in re.split(r"[/,;·&]| 그리고 ", field):
        part = part.strip()
        if not part:
            continue
        m = re.search(r"[(（]([^)）]*)[)）]", part)   # 괄호 안 원어/라틴
        latin = m.group(1) if m else part
        toks = [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z'\-]+", latin)]
        toks = [t for t in toks if len(t) >= 3 and t not in _PHIL_STOP]
        if toks:
            keys.add(toks[-1])          # 성은 보통 마지막
        else:
            kk = re.sub(r"[\s·]+", "", part)  # 라틴 표기 없음 → 한글 정규화
            if kk:
                keys.add(kk)
    return keys


def load_published_urls() -> set:
    """기존 news.json에서 이미 발행된 URL 목록 반환 (중복 방지)"""
    if not os.path.exists(NEWS_PATH):
        return set()
    with open(NEWS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {item["sourceUrl"] for item in data.get("items", []) if item.get("sourceUrl")}


def load_recent_articles(weeks: int = HISTORY_LOOKBACK) -> list:
    """최근 N주 발행된 글 목록 반환 (중복 필터·프롬프트용).

    반환: [{"week", "title", "summary", "tags"}] (과거→최신 순).
    구버전(tags만 있는) 항목도 안전하게 읽는다.
    """
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        history = json.load(f)
    entries = history.get("weeks", [])
    recent = entries[-weeks:] if len(entries) > weeks else entries
    articles = []
    for entry in recent:
        wk = entry.get("week", "")
        for art in entry.get("articles", []):
            title = (art.get("title") or "").strip()
            if not title:
                continue
            articles.append({
                "week":    wk,
                "title":   title,
                "summary": (art.get("summary") or "").strip(),
                "tags":    art.get("tags", []),
            })
    return articles


def save_history(week_id: str, items: list):
    """이번 주 발행 글(제목·요약·태그)을 history에 누적 저장 (최대 26주 보관).

    중복 필터가 다음 주 큐레이션 때 대조할 수 있도록 글 단위 정보를 남긴다.
    """
    history = {"weeks": []}
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            history = json.load(f)

    articles = [
        {
            "title":       (item.get("title") or "").strip(),
            "summary":     (item.get("summary") or "").strip(),
            "philosopher": (item.get("philosopher") or "").strip(),
            "tags":        item.get("tags", []),
        }
        for item in items
        if (item.get("title") or "").strip()
    ]
    all_tags = list(dict.fromkeys(t for a in articles for t in a["tags"]))
    entry = {"week": week_id, "tags": all_tags, "articles": articles}

    weeks = history.get("weeks", [])
    for i, e in enumerate(weeks):
        if e.get("week") == week_id:
            weeks[i] = entry
            break
    else:
        weeks.append(entry)

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
        for item in data.get("items", [])[:8]:    # 소스당 최대 8개 (주간 18개 보충용 후보 풀 확대)
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
4. 주제의 다양성: 한 주(그리고 같은 요일 안)의 글들이 서로 다른 삶의 영역(노동·관계·기술·소비·몸·시간·자연·정치 등)을 다루도록 고른다. 비슷한 결의 글을 여러 개 뽑지 말 것.
5. 새로운 시각: 통념을 뒤집거나 익숙한 현상을 전혀 다른 각도로 보는 콘텐츠.
6. 중복 최소화 (엄격 적용): 같은 철학자·개념·사회현상은 물론, 논지·결론·문제의식이 비슷하기만 해도 반복하지 않는다. 제목·표현이 달라도 본질이 겹치면 중복이다.

## 반드시 제외할 콘텐츠 (아무리 흥미로워도 선택하지 않는다)
플라뇌르는 산책자의 차분한 시선으로 '평범한 일상'에서 사유를 길어올린다. 자극이 아니라 관찰과 성찰이 핵심이다. 주제는 다양하되 톤은 극단으로 치우치지 않는다.
- 엽기적·기괴하거나 충격·혐오를 노린 소재 (잔혹 범죄 묘사, 신체 훼손, 그로테스크한 장면 등)
- 극단적 정치·이념 선동, 음모론, 특정 집단을 향한 혐오·비하·조롱
- 노골적 성적 내용, 선정적이거나 자극만을 노린 클릭베이트
- 일상과 동떨어진 지나치게 사변적·난해한 학술 논쟁 (독자가 자기 삶과 연결하기 어려운 것)
위에 해당하는 항목만 남았다면, 요일별 목표 편수를 못 채우더라도 선택하지 않는다.

## 글쓰기 원칙
- 반드시 사회현상·일상 장면이 먼저, 철학은 그 다음
- 철학자 이름·개념에서 출발하지 않음
- 한국적 상황·한국 독자 관점은 포함하지 않음 (운영자가 에세이에서 직접 연결)
- 그 나라 맥락 포함

## 응답
반드시 JSON만 반환. 다른 텍스트 없이."""


def build_user_prompt(day: str, items: list, recent_articles: list = None,
                      need: int = PER_DAY, banned_names: list = None) -> str:
    items_block = ""
    for i, item in enumerate(items):
        items_block += (
            f"\n[{i+1}] 소스: {item['source']}\n"
            f"제목: {item['title']}\n"
            f"설명: {item['description']}\n"
            f"URL: {item['url']}\n"
            f"날짜: {item['date']}\n---"
        )

    philosopher_section = ""
    if banned_names:
        philosopher_section = (
            f"\n## 이번 주(월~토) 이미 다룬 철학자 — 절대 다시 다루지 마세요\n"
            f"{', '.join(banned_names)}\n"
            f"→ 위 인물을 **중심으로** 다루는 항목은 (한글·원어 표기가 달라도 동일 인물이면) 선택하지 마세요.\n"
            f"   이번에 고르는 {need}개도 서로 **다른 철학자**를 중심으로 해야 합니다. 같은 철학자를 두 번 쓰지 마세요.\n"
        )

    avoid_section = ""
    if recent_articles:
        past_block = "\n".join(
            f"- {a['title']}" + (f" — {a['summary']}" if a['summary'] else "")
            for a in recent_articles
        )
        avoid_section = (
            f"\n## 이미 발행한 과거 글 (절대 같은 내용을 반복하지 마세요)\n"
            f"{past_block}\n"
            f"→ 위 글들과 **같은 사회현상·질문·철학자·핵심개념**을 다루는 항목은 선택하지 마세요.\n"
            f"   제목·표현이 달라도 본질이 겹치면 중복입니다. (예: '불완전함/완벽주의', "
            f"'몸과 스크린/디지털 신체', '조직의 침묵/실수 은폐', '남성 외모 압박' 등은 이미 여러 번 다뤘습니다.)\n"
            f"   과거에 다루지 않은 새로운 현상·관점을 우선하세요.\n"
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
        # 독일(화)은 외국어 표기 대상에서 제외 → 반드시 한국어로.
        # (출처·주제가 독일어권이면 모델이 독일어로 쓰려는 경향이 있어 명시적으로 금지한다.)
        context_instruction = (
            "[그 나라 맥락] **이 단락은 반드시 한국어로만 작성합니다.** "
            "독일어를 비롯한 어떤 외국어도 한 문장·한 단어도 섞지 마세요. "
            "해당 철학이 나온 나라에서 이 현상이 어떻게 나타나는지, "
            "그 나라 문화·사회가 이 질문을 어떻게 다루는지 4~5문장으로 한국어로 서술한다. "
            "한국과 다른 결을 보여주는 구체적 사례나 문화적 태도를 담는다. "
            "(고유명사·개념어는 필요하면 괄호 안에 원어를 병기할 수 있으나, 문장 자체는 한국어로 쓴다.)"
        )

    return f"""{DAY_LABELS[day]} 항목 {len(items)}개 중 가장 적합한 {need}개를 선택하고 한국어 요약을 작성하세요.
- 선택하는 {need}개는 **서로 다른 삶의 영역·주제**여야 합니다 (예: 하나가 '노동'이면 나머지는 '관계'·'기술'·'몸' 등 다른 축). 비슷한 결의 글을 겹쳐 뽑지 마세요.
- 엽기적·충격적·극단적이거나 노골적으로 자극적인 항목, 일상과 동떨어진 난해한 학술 논쟁은 제외합니다. 적합한 항목이 {need}개에 못 미치면 억지로 채우지 말고 가능한 만큼만 선택하세요.
{philosopher_section}{avoid_section}

각 항목은 다음 구조로 작성합니다:
- title: 한국어 제목 (원제목을 번역하거나 핵심을 재구성, 30자 이내)
- summary: 한 줄 요약 (독자의 호기심을 자극, 40~60자)
- philosopher: 이 글이 **중심으로** 다루는 철학자(또는 사상가) 1명의 이름. 반드시 '한글이름 (원어 알파벳 표기)' 형식으로 라틴 알파벳 이름을 병기한다 (예: "니체 (Friedrich Nietzsche)", "한나 아렌트 (Hannah Arendt)"). 중심 철학자가 여럿이면 가장 핵심 1명만 적는다. 특정 철학자를 중심에 두지 않는 글이면 빈 문자열("")로 둔다.
- detail: 본문. 아래 순서로 세 단락을 작성:
    [현상/질문] "왜 우리는 ~하는가?" 형식으로 구체적 일상 장면·사회현상을 독자가 생생하게 떠올릴 수 있도록 5~7문장으로 묘사. 장면의 디테일, 감각, 감정까지 담아 독자를 그 상황 안으로 끌어들인다.
    [철학적 해석] 현상과 자연스럽게 연결되는 철학자·개념을 소개하고, 그 철학이 이 현상을 어떻게 다르게 보게 해주는지 5~7문장으로 서술. 개념 설명에 그치지 않고 독자가 "아, 그래서 이런 거였구나"라고 느낄 수 있도록 현상과의 연결을 충분히 풀어낸다.
    {context_instruction}
    총 1,500~2,000자 (단, '그 나라 맥락' 단락이 외국어인 경우 그 단락은 분량 제한 없이 A2 수준으로 짧게)

  ※ detail 형식 규칙(모든 요일 동일): 세 단락은 반드시 대괄호 라벨 `[현상/질문]`, `[철학적 해석]`, `[그 나라 맥락]` 로 시작한다. 라벨은 본문과 한 칸 띄어 같은 줄에 붙여 쓰고(예: "[현상/질문] 왜 우리는…"), 단락과 단락 사이는 빈 줄 하나(\\n\\n)로 구분한다. 별표(`**`)·전각 괄호(`【 】`)·머리글 줄바꿈 등 다른 표기는 절대 쓰지 않는다.
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
      "philosopher": "니체 (Friedrich Nietzsche)",
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


def curate_day(client: anthropic.Anthropic, day: str, items: list,
               recent_articles: list = None, need: int = PER_DAY,
               banned_names: list = None) -> list:
    """Claude API로 해당 요일 상위 need개 선택 + 한국어 요약 반환. JSON 파싱 실패 시 1회 재시도."""
    messages = [{"role": "user", "content": build_user_prompt(day, items, recent_articles, need, banned_names)}]

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
            "philosopher":  (sel.get("philosopher") or "").strip(),
            "detail":       sel["detail"],
            "tags":         sel.get("tags", []),
            "originalTitle": orig["title"],
        })

    return curated


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 중복 필터 (발행 직전 게이트)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEDUP_SYSTEM = """당신은 철학 큐레이션 사이트 '플라뇌르'의 중복 검수자입니다.
새로 큐레이션한 글이 과거에 발행한 글과 본질적으로 같거나 유사한 내용인지 엄격하게 판정합니다.

## 중복 판정 기준 (하나라도 겹치면 중복 — 제목·표현·소재가 달라도)
- 같은 사회현상·일상 장면을 다룬다 (예: 남성의 외모 관리, 디지털 환경 속 신체)
- 같은 핵심 질문·문제의식을 던진다 (예: 완벽주의/불완전함, 조직의 실수 은폐와 침묵)
- 같은 철학자·핵심개념이 글의 중심이다 (예: 클레르 마랭의 불완전함, 드 케르코브의 디지털 신체)
- 서로 다른 소재를 쓰더라도 **결국 같은 논지·결론·교훈**에 도달한다
  (예: '느리게 살자', '주의를 되찾자', '욕망은 채워지지 않는다', '자기 자신이 되라' 류의 익숙한 결론)

## 판정 태도
- 애매하면 중복 쪽으로 판정한다. 소스 풀이 넓어 대체 후보가 충분하므로, 조금이라도 겹치면 걸러내는 편이 낫다.
- 단, 삶의 영역만 넓게 겹치는 정도(둘 다 '몸'이나 '기술'을 언급)는 중복이 아니다.
  핵심 소재·질문·관점·논지 중 실질적으로 같은 축이 있을 때 중복으로 본다.

## 응답
반드시 JSON만 반환. 다른 텍스트 없이."""


def filter_duplicates(client: anthropic.Anthropic, candidates: list, past: list) -> list:
    """candidates 각각이 past(과거 발행 글 + 같은 주 이미 채택된 글)와 중복인지 판정.

    반환: candidates와 같은 길이의 verdict 리스트.
          [{"is_duplicate": bool, "matched": "과거 제목 또는 ''", "reason": "..."}]
    API 실패 시 모두 비중복으로 간주(게이트가 발행을 막지 않도록 — fail-open).
    """
    if not candidates:
        return []
    if not past:
        return [{"is_duplicate": False, "matched": "", "reason": ""} for _ in candidates]

    past_block = "\n".join(
        f"- {a['title']}" + (f" — {a['summary']}" if a.get('summary') else "")
        for a in past
    )
    cand_block = ""
    for i, c in enumerate(candidates):
        cand_block += (
            f"\n[{i+1}] 제목: {c['title']}\n"
            f"요약: {c.get('summary','')}\n"
            f"태그: {', '.join(c.get('tags', []))}\n---"
        )

    prompt = f"""## 과거에 이미 발행한 글
{past_block}

## 이번에 새로 큐레이션한 글 ({len(candidates)}개) — 각각 위 과거 글과 중복인지 판정
{cand_block}

## 응답 형식 (JSON만, verdicts 길이는 새 글 개수와 동일)
{{
  "verdicts": [
    {{"index": 1, "is_duplicate": true, "matched": "겹치는 과거 글 제목", "reason": "왜 같은지 한 줄"}},
    {{"index": 2, "is_duplicate": false, "matched": "", "reason": ""}}
  ]
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=DEDUP_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        result = extract_json(response.content[0].text)
    except Exception as e:
        print(f"    [중복필터 오류] {e} — 이번 판정은 건너뜀(비중복 처리)")
        return [{"is_duplicate": False, "matched": "", "reason": ""} for _ in candidates]

    verdicts = [{"is_duplicate": False, "matched": "", "reason": ""} for _ in candidates]
    for v in result.get("verdicts", []):
        try:
            i = int(v["index"]) - 1
        except (KeyError, ValueError, TypeError):
            continue
        if 0 <= i < len(candidates):
            verdicts[i] = {
                "is_duplicate": bool(v.get("is_duplicate")),
                "matched":      (v.get("matched") or "").strip(),
                "reason":       (v.get("reason") or "").strip(),
            }
    return verdicts


def curate_day_filtered(client: anthropic.Anthropic, day: str, day_items: list,
                        recent_articles: list, target: int = PER_DAY,
                        exclude_urls: set = None, banned_names: list = None) -> list:
    """해당 요일에서 과거 글과 중복되지 않는 글 target개를 확보해 반환.

    target은 '이번에 새로 더 채워야 할 편수'다(부분 보충 시 PER_DAY보다 작을 수 있다).
    exclude_urls에 든 URL(이미 이번 주에 채택한 항목)은 후보에서 제외한다.
    banned_names는 이번 주 이미 다룬 철학자 목록 → 프롬프트에서 재사용을 막는다.
    1차 큐레이션 → 중복 필터 게이트 → 중복은 버리고, 부족분은 1회 보충 큐레이션.
    같은 주 안의 중복도 막기 위해, 이미 채택한 글을 비교 대상(past)에 누적한다.
    """
    chosen = []
    used_urls = set(exclude_urls or ())
    candidates = list(day_items)
    # 이번 호출 안에서 채택한 철학자도 다음 라운드 프롬프트에서 배제
    round_banned = list(banned_names or [])

    for round_no in range(2):  # 최초 + 보충 1회
        need = target - len(chosen)
        if need <= 0:
            break
        pool = [c for c in candidates if c["url"] not in used_urls]
        if not pool:
            break

        picked = curate_day(client, day, pool, recent_articles, need=need,
                            banned_names=round_banned)
        if not picked:
            break
        for p in picked:
            used_urls.add(p["sourceUrl"])

        # 과거 글 + 이번 주 이미 채택한 글과 대조
        compare_against = recent_articles + [
            {"title": c["title"], "summary": c.get("summary", ""), "tags": c.get("tags", [])}
            for c in chosen
        ]
        verdicts = filter_duplicates(client, picked, compare_against)

        for p, v in zip(picked, verdicts):
            if v["is_duplicate"]:
                print(f"    [중복 제외] '{p['title']}' ↔ '{v['matched']}' ({v['reason']})")
            else:
                chosen.append(p)
                if p.get("philosopher"):
                    round_banned.append(p["philosopher"])

    if len(chosen) < target:
        print(f"    [알림] {DAY_LABELS[day]}: 중복 제외 후 {len(chosen)}개만 확보 "
              f"(이번 목표 {target}개) — 비중복 후보 부족")
    return chosen[:target]


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

    # 멱등성: 같은 주차가 이미 WEEKLY_TARGET(18)개 발행됐으면 건너뛴다.
    # (FORCE=1이면 전부 재생성. 18개 미만이면 부족분을 이어서 채운다.)
    existing_items = []
    force = bool(os.environ.get("FORCE"))
    if not force:
        try:
            with open(NEWS_PATH, encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("week") == week_id:
                existing_items = existing.get("items", [])
                if len(existing_items) >= WEEKLY_TARGET:
                    print(f"이미 {week_id} {len(existing_items)}개(목표 {WEEKLY_TARGET}) 발행됨 "
                          f"— 건너뜁니다. (재생성하려면 FORCE=1)")
                    return
                day_counts = Counter(it.get("day") for it in existing_items)
                shortfall = {DAY_LABELS[d]: day_counts.get(d, 0) for d in DAYS}
                print(f"이미 {week_id} {len(existing_items)}개 발행됨(요일별 {shortfall}). "
                      f"→ {WEEKLY_TARGET}개까지 이어서 채움\n")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    published_urls = load_published_urls()
    if published_urls:
        print(f"기존 발행 URL {len(published_urls)}개 제외\n")

    recent_articles = load_recent_articles(weeks=HISTORY_LOOKBACK)
    if recent_articles:
        print(f"최근 {HISTORY_LOOKBACK}주 발행 글 {len(recent_articles)}개 로드 (중복 필터용)\n")
    # 보충 모드: 이번 주 이미 발행된 다른 요일 글과도 겹치지 않도록 비교 대상에 포함
    if existing_items:
        recent_articles = recent_articles + [
            {"title": it.get("title", ""), "summary": it.get("summary", ""), "tags": it.get("tags", [])}
            for it in existing_items
        ]

    # 요일별 피드는 한 번만 로딩(1차·2차 보충에서 공유)
    day_feeds = {d: load_feeds_for_day(sources, d, published_urls) for d in DAYS}

    # 이번 실행에서 새로 뽑은 글(요일별). 이미 발행된 existing_items와 합쳐 최종 편수를 계산한다.
    from collections import defaultdict
    chosen_by_day    = defaultdict(list)
    existing_by_day  = Counter(it.get("day") for it in existing_items)
    existing_urls    = defaultdict(set)
    for it in existing_items:
        if it.get("sourceUrl"):
            existing_urls[it.get("day")].add(it["sourceUrl"])

    # 이번 주(월~토) 이미 사용된 철학자 — 한 주 안에서 같은 철학자를 두 번 이상 다루지 않는다.
    # keys=비교용 정규화 성(姓) 집합, names=프롬프트에 보여줄 원 표기 목록.
    used_phil_keys  = set()
    used_phil_names = []
    for it in existing_items:
        ph = (it.get("philosopher") or "").strip()
        if not ph:
            continue
        ks = philosopher_keys(ph)
        if ks and not (ks & used_phil_keys):
            used_phil_names.append(ph)
        used_phil_keys |= ks

    def day_count(d):
        return existing_by_day.get(d, 0) + len(chosen_by_day[d])

    def total_count():
        return len(existing_items) + sum(len(v) for v in chosen_by_day.values())

    def chosen_urls(d):
        return existing_urls[d] | {c["sourceUrl"] for c in chosen_by_day[d]}

    def take(day, n, phase):
        """해당 요일에서 비중복 글 n개를 확보해 chosen_by_day에 추가하고 실제 추가 편수 반환."""
        nonlocal recent_articles
        items = day_feeds.get(day, [])
        if not items or n <= 0:
            return 0
        try:
            picked = curate_day_filtered(client, day, items, recent_articles,
                                         target=n, exclude_urls=chosen_urls(day),
                                         banned_names=used_phil_names)
        except Exception as e:
            print(f"  → 큐레이션 실패: {e}")
            return 0
        added = _accept(day, picked, phase)
        return added

    def take_raw(day, n, phase="3차"):
        """최후 보루: 의미 중복 게이트를 건너뛰고 원문 후보에서 n개를 채운다.
        원문(실제 소스 글)은 완전 중복이 아니므로, 18개에 미달하느니 약간 겹치더라도 채운다.
        이미 채택한 URL·과거 발행 URL은 제외하므로 같은 글이 반복되지는 않는다.
        """
        nonlocal recent_articles
        used = chosen_urls(day)
        items = [it for it in day_feeds.get(day, []) if it["url"] not in used]
        if not items or n <= 0:
            return 0
        try:
            picked = curate_day(client, day, items, recent_articles, need=n,
                                banned_names=used_phil_names)
        except Exception as e:
            print(f"  → 최후 보충 실패: {e}")
            return 0
        return _accept(day, picked[:n], phase)

    def _accept(day, picked, phase):
        """picked를 chosen_by_day에 추가(URL·철학자 중복 방지)하고 실제 추가 편수 반환."""
        nonlocal recent_articles
        added = 0
        for c in picked:
            if c["sourceUrl"] in chosen_urls(day):
                continue
            # 이번 주 이미 다룬 철학자면 제외 (월~토 철학자 유일성 하드 게이트)
            keys = philosopher_keys(c.get("philosopher", ""))
            dup_keys = keys & used_phil_keys
            if dup_keys:
                print(f"    [철학자 중복 제외] '{c['title']}' — 이미 다룬 철학자"
                      f"({c.get('philosopher','')})")
                continue
            chosen_by_day[day].append(c)
            if keys:
                used_phil_keys.update(keys)
                used_phil_names.append(c.get("philosopher", ""))
            recent_articles = recent_articles + [
                {"title": c["title"], "summary": c.get("summary", ""), "tags": c.get("tags", [])}
            ]
            added += 1
        if added:
            titles = [c["title"] for c in chosen_by_day[day][-added:]]
            print(f"  [{phase}] {DAY_LABELS[day]} +{added}: {titles}")
        return added

    # ── 1차: 각 요일을 PER_DAY(3)까지 ──
    print("── 1차 큐레이션: 요일당 3개 목표 ──")
    for day in DAYS:
        need = PER_DAY - day_count(day)
        if need <= 0:
            continue
        if not day_feeds.get(day):
            print(f"  [1차] {DAY_LABELS[day]} 피드 없음, 건너뜀")
            continue
        take(day, need, "1차")

    # ── 2차: 주간 총 18개를 채울 때까지 후보가 남은 요일에서 보충(요일당 MAX_PER_DAY까지) ──
    if total_count() < WEEKLY_TARGET:
        print(f"\n── 2차 보충: 현재 {total_count()}개 → {WEEKLY_TARGET}개 채움 (요일당 최대 {MAX_PER_DAY}개) ──")
        stagnant_rounds = 0
        while total_count() < WEEKLY_TARGET and stagnant_rounds < 2:
            added_this_round = 0
            # 편수가 적은 요일부터 채워 균형을 유지
            for day in sorted(DAYS, key=day_count):
                if total_count() >= WEEKLY_TARGET:
                    break
                if day_count(day) >= MAX_PER_DAY or not day_feeds.get(day):
                    continue
                added_this_round += take(day, 1, "2차")
            stagnant_rounds = stagnant_rounds + 1 if added_this_round == 0 else 0

    # ── 3차(최후 보루): 그래도 18개 미만이면 중복 게이트를 완화해 반드시 채운다 ──
    if total_count() < WEEKLY_TARGET:
        print(f"\n── 3차 최후 보충: 현재 {total_count()}개 → {WEEKLY_TARGET}개 (중복 게이트 완화) ──")
        stagnant_rounds = 0
        while total_count() < WEEKLY_TARGET and stagnant_rounds < 2:
            added_this_round = 0
            for day in sorted(DAYS, key=day_count):
                if total_count() >= WEEKLY_TARGET:
                    break
                if day_count(day) >= MAX_PER_DAY or not day_feeds.get(day):
                    continue
                added_this_round += take_raw(day, 1)
            stagnant_rounds = stagnant_rounds + 1 if added_this_round == 0 else 0

    # 요일 순으로 id 부여 후 병합
    new_items = []
    for day in DAYS:
        start = existing_by_day.get(day, 0) + 1
        for i, item in enumerate(chosen_by_day[day], start=start):
            item["id"] = f"{DAY_PREFIX[day]}-{i:02d}"
            new_items.append(item)

    if not new_items:
        if existing_items:
            print(f"\n새로 추가된 항목 없음 — 기존 {len(existing_items)}개 유지.")
            return
        print("큐레이션된 항목이 없습니다. 기존 news.json을 유지합니다.")
        sys.exit(1)

    day_order = {d: i for i, d in enumerate(DAYS)}
    all_items = existing_items + new_items
    all_items.sort(key=lambda it: day_order.get(it.get("day"), 99))

    final_total = len(all_items)
    if final_total < WEEKLY_TARGET:
        print(f"\n[경고] 비중복 후보 고갈로 {final_total}개만 확보(목표 {WEEKLY_TARGET}). "
              f"다음 cron이 이어서 보충하며, 반복되면 소스를 늘려야 합니다.")

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
    save_history(week_id, all_items)
    print(f"완료: {len(all_items)}개 항목 → data/news.json 저장 / 발행 이력 갱신")


if __name__ == "__main__":
    main()
