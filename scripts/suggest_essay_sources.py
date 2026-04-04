"""
플라뇌르 — 에세이 소스 제안 스크립트

매년 1월과 7월에 GitHub Actions가 실행합니다.
국제 철학 에세이 사이트에서 최신 글을 수집해
data/essay-suggestions.json 에 저장합니다.

에세이는 자동 생성하지 않습니다.
운영자가 이 목록을 참고해 직접 에세이를 작성합니다.
"""

import json
import os
import re
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH     = os.path.join(ROOT, "data", "essay-suggestions.json")

# ── 에세이 소스 목록 ──────────────────────────────────────────
# 분기별로 참고할 수 있는 고품질 철학·인문 에세이 사이트
ESSAY_SOURCES = [
    {
        "id":       "aeon",
        "name":     "Aeon Essays",
        "url":      "https://aeon.co",
        "rss":      "https://aeon.co/feed.rss",
        "lang":     "en",
        "note":     "일상·과학·철학 교차 장편 에세이. 플라뇌르 정체성과 가장 잘 맞는 소스.",
    },
    {
        "id":       "iai",
        "name":     "IAI News (Institute of Art and Ideas)",
        "url":      "https://iai.tv",
        "rss":      "https://iai.tv/rss",
        "lang":     "en",
        "note":     "철학자·과학자 인터뷰 및 에세이. 현대 쟁점을 철학으로 해석.",
    },
    {
        "id":       "the-conversation-phil",
        "name":     "The Conversation — Philosophy",
        "url":      "https://theconversation.com/us/philosophy",
        "rss":      "https://theconversation.com/us/philosophy/articles.atom",
        "lang":     "en",
        "note":     "학자들이 대중에게 쓰는 철학 에세이. 시의성 높은 주제 多.",
    },
    {
        "id":       "psyche",
        "name":     "Psyche (Aeon 자매지)",
        "url":      "https://psyche.co",
        "rss":      "https://psyche.co/feed",
        "lang":     "en",
        "note":     "심리·철학·삶의 방식. '어떻게 살 것인가' 질문에 집중.",
    },
    {
        "id":       "philosophy-bites",
        "name":     "Philosophy Bites",
        "url":      "https://philosophybites.com",
        "rss":      "https://philosophybites.libsyn.com/rss",
        "lang":     "en",
        "note":     "철학자 인터뷰 팟캐스트. 짧고 밀도 있는 개념 해설.",
    },
    {
        "id":       "cairn-philo",
        "name":     "Cairn — Philosophie (프랑스)",
        "url":      "https://www.cairn.info/revues-de-philosophie.htm",
        "rss":      "https://www.cairn.info/rss/philosophie.xml",
        "lang":     "fr",
        "note":     "프랑스 철학 저널 아카이브. 대륙철학·현상학 중심.",
    },
    {
        "id":       "internazionale",
        "name":     "Internazionale — Filosofia (이탈리아)",
        "url":      "https://www.internazionale.it/tag/filosofia",
        "rss":      "https://www.internazionale.it/tag/filosofia/rss",
        "lang":     "it",
        "note":     "이탈리아 주간지의 철학 섹션. 시사와 철학 연결.",
    },
]

# ── 계절별 추천 테마 (1월·7월 각각) ──────────────────────────
SEASONAL_THEMES = {
    1: {
        "season":  "겨울·새해",
        "themes":  ["시작과 끝", "습관과 결심", "시간의 철학", "변화와 동일성",
                    "목표 설정의 역설", "망각과 기억", "정체성의 지속"],
        "hint":    "1월은 시간·변화·반복에 관한 에세이가 독자에게 가장 잘 닿는 시기입니다.",
    },
    7: {
        "season":  "여름·휴가",
        "themes":  ["느림과 여유", "여행과 낯섦", "일상 탈출의 의미", "자연과 몸",
                    "피로사회", "축제와 공동체", "무위(無爲)의 철학"],
        "hint":    "7월은 속도·노동·휴식에 관한 에세이가 시의성을 갖습니다.",
    },
}


# ── HTML 스트리퍼 ─────────────────────────────────────────────
class HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.fed = []
    def handle_data(self, d):
        self.fed.append(d)
    def get_data(self):
        return " ".join(self.fed)

def strip_html(html: str) -> str:
    s = HTMLStripper()
    s.feed(html or "")
    return s.get_data().strip()


# ── HTTP 요청 ─────────────────────────────────────────────────
def fetch_url(url: str, timeout: int = 15) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FlaneurEssayBot/1.0)",
        "Accept": "application/rss+xml, application/atom+xml, text/xml, */*",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


# ── 피드 파싱 ─────────────────────────────────────────────────
NS = {
    "atom":  "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
}

def parse_feed(xml_text: str) -> list:
    root = ET.fromstring(xml_text)
    items = []

    # Atom
    entries = root.findall("atom:entry", NS) or root.findall("entry")
    if entries:
        for entry in entries[:12]:
            title    = (entry.findtext("atom:title", namespaces=NS)
                        or entry.findtext("title") or "").strip()
            link_el  = entry.find("atom:link[@rel='alternate']", NS) or entry.find("link")
            url      = (link_el.get("href", "") if link_el is not None else
                        entry.findtext("atom:id", namespaces=NS) or "")
            pub      = (entry.findtext("atom:published", namespaces=NS)
                        or entry.findtext("atom:updated", namespaces=NS)
                        or entry.findtext("published") or "")[:10]
            desc_el  = (entry.find("atom:summary", NS) or entry.find("atom:content", NS)
                        or entry.find("summary") or entry.find("content"))
            desc     = strip_html(desc_el.text if desc_el is not None else "")[:600]
            items.append({"title": title, "url": url, "description": desc, "date": pub})
        return items

    # RSS 2.0
    for item in (root.find("channel") or root).findall("item")[:12]:
        title = item.findtext("title", "").strip()
        url   = item.findtext("link", "").strip()
        desc  = strip_html(item.findtext("description", ""))[:600]
        date  = item.findtext("pubDate", "")[:16]
        items.append({"title": title, "url": url, "description": desc, "date": date})
    return items


# ── 관련성 채점 ───────────────────────────────────────────────
ESSAY_KEYWORDS = [
    # 일상·삶
    "life", "daily", "everyday", "work", "love", "death", "time", "habit",
    "solitude", "loneliness", "city", "body", "sleep", "eating", "walking",
    # 철학
    "philosophy", "ethics", "meaning", "freedom", "justice", "truth",
    "consciousness", "identity", "existence", "value", "moral", "question",
    # 에세이 형식
    "essay", "reflection", "thought", "why", "how", "what is",
    "we", "our", "I", "human", "society",
    # 플라뇌르
    "observation", "slow", "wander", "flâneur", "urban", "street",
    "ordinary", "small", "detail", "notice",
]

def score_essay(item: dict) -> int:
    text = f"{item['title']} {item['description']}".lower()
    return sum(1 for kw in ESSAY_KEYWORDS if kw in text)


# ── 메인 ─────────────────────────────────────────────────────
def main():
    now   = datetime.now(timezone.utc)
    month = now.month

    if month not in (1, 7):
        print(f"[INFO] 현재 {month}월 — 에세이 소스 제안은 1월·7월에만 실행합니다.")
        print("[INFO] 강제 실행하려면 환경변수 FORCE=1 을 설정하세요.")
        if not os.environ.get("FORCE"):
            # 기존 파일 유지, 정상 종료
            return

    season_info = SEASONAL_THEMES.get(month, SEASONAL_THEMES[1])
    print(f"\n[시즌] {season_info['season']} — 추천 테마: {', '.join(season_info['themes'][:3])}…\n")

    collected = []

    for src in ESSAY_SOURCES:
        print(f"[FETCH] {src['name']} ← {src['rss']}", end=" ... ", flush=True)
        try:
            xml_text = fetch_url(src["rss"])
            items    = parse_feed(xml_text)

            # 관련성 점수 부여 + 정렬
            scored = sorted(items, key=score_essay, reverse=True)[:5]

            print(f"OK ({len(items)}개 수집, 상위 {len(scored)}개 선택)")
            collected.append({
                "source": {
                    "id":   src["id"],
                    "name": src["name"],
                    "url":  src["url"],
                    "lang": src["lang"],
                    "note": src["note"],
                },
                "items": scored,
            })

        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code} — 건너뜀")
        except Exception as e:
            print(f"ERR — {e} — 건너뜀")

    result = {
        "generatedAt": now.isoformat(),
        "season":      season_info["season"],
        "hint":        season_info["hint"],
        "themes":      season_info["themes"],
        "note":        (
            "이 목록은 에세이 작성의 참고용 소스 제안입니다. "
            "에세이는 운영자가 직접 작성합니다. "
            "다음 갱신은 " + ("7월" if month == 1 else "내년 1월") + "입니다."
        ),
        "sources": collected,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total_items = sum(len(s["items"]) for s in collected)
    print(f"\n완료: {len(collected)}개 소스, {total_items}개 항목 → {OUT_PATH}")


if __name__ == "__main__":
    main()
