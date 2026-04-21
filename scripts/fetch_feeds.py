"""
플라뇌르 — 피드 수집 + 자동 우선순위 스크립트
GitHub Actions에서 실행되어 모든 소스의 최신 피드를 data/feeds/ 에 저장합니다.

우선순위 채점 기준 (높을수록 먼저 노출):
  1. 일상·사회현상 밀접도  (0~40점)
  2. 철학적 연결 자연스러움 (0~25점)
  3. 플라뇌르 정체성 부합   (0~20점)
  4. 새로운 시각·접근       (0~15점)
  합계 최대 100점
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "data", "sources.json")
FEEDS_DIR    = os.path.join(ROOT, "data", "feeds")

NS = {
    "atom":  "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "yt":    "http://www.youtube.com/xml/schemas/2015",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 우선순위 채점 엔진
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 1. 일상·사회현상 밀접도 키워드 (40점 만점)
DAILY_LIFE_KEYWORDS = [
    # 디지털·기술 일상
    "smartphone", "téléphone", "handy", "telefono", "social media", "réseaux sociaux",
    "instagram", "tiktok", "youtube", "algorithm", "algorithme", "algorithmus",
    "notification", "addiction", "dépendance", "sucht", "dipendenza",
    "screen", "écran", "bildschirm", "schermo", "internet", "digital",
    # 노동·직장
    "travail", "arbeit", "lavoro", "work", "burnout", "stress",
    "productivity", "productivité", "produktivität", "produttività",
    "télétravail", "homeoffice", "remote", "overtime", "surmenage",
    # 소비·돈
    "consommation", "konsum", "consumo", "consumption", "money", "argent",
    "geld", "soldi", "shopping", "achat", "kaufen", "acquisto",
    "prix", "preis", "prezzo", "price", "dette", "schulden", "debito",
    # 관계·사회
    "solitude", "einsamkeit", "solitudine", "loneliness",
    "famille", "family", "familie", "famiglia", "amour", "liebe", "amore", "love",
    "amitié", "freundschaft", "amicizia", "friendship",
    "mariage", "ehe", "matrimonio", "marriage", "divorce",
    # 감정·심리
    "anxiété", "angst", "ansia", "anxiety", "bonheur", "glück", "felicità", "happiness",
    "dépression", "depression", "depressione", "colère", "wut", "rabbia", "anger",
    "peur", "angst", "paura", "fear", "identité", "identität", "identità", "identity",
    # 환경·사회문제
    "climat", "klima", "clima", "climate", "environnement", "umwelt",
    "inégalité", "ungleichheit", "disuguaglianza", "inequality",
    "politique", "politik", "politica", "politics", "guerre", "krieg", "guerra", "war",
    # 일상 행위
    "manger", "essen", "mangiare", "eat", "dormir", "schlafen", "dormire", "sleep",
    "marcher", "gehen", "camminare", "walk", "quotidien", "alltag", "quotidiano", "daily",
    # 의문형 제목 (현상 제기)
    "pourquoi", "warum", "perché", "why", "comment", "wie", "come", "how",
    "est-ce que", "ist es", "è possibile", "should we", "can we",
]

# 2. 철학적 연결 키워드 (25점 만점)
PHILOSOPHY_KEYWORDS = [
    "philosophie", "philosophie", "filosofia", "philosophy",
    "éthique", "ethik", "etica", "ethics", "morale", "moral",
    "liberté", "freiheit", "libertà", "freedom", "liberty",
    "vérité", "wahrheit", "verità", "truth",
    "sens", "sinn", "senso", "meaning", "existence", "existenz",
    "bonheur", "glück", "felicità", "happiness", "bien", "gut", "bene", "good",
    "justice", "gerechtigkeit", "giustizia",
    "conscience", "bewusstsein", "coscienza", "consciousness",
    "société", "gesellschaft", "società", "society",
    "penser", "denken", "pensare", "think", "réfléchir", "nachdenken",
    "question", "frage", "domanda", "problème", "problem", "problema",
    "valeur", "wert", "valore", "value",
]

# 3. 플라뇌르 정체성 키워드 (20점 만점)
# 산책하듯 관찰하고 사유하는 시선, 일상의 디테일에서 의미 찾기
FLANEUR_KEYWORDS = [
    # 관찰·산책 시선
    "observer", "beobachten", "osservare", "observe", "regarder", "schauen", "guardare",
    "promenade", "spaziergang", "passeggiata", "walk", "flâner", "wandern",
    "quotidien", "alltag", "quotidiano", "everyday", "ordinaire", "gewöhnlich",
    "détail", "detail", "dettaglio", "small", "petit", "klein", "piccolo",
    # 도시·공간
    "ville", "stadt", "città", "city", "rue", "straße", "strada", "street",
    "café", "marché", "markt", "mercato", "market", "espace", "raum", "spazio",
    # 사유·성찰
    "réflexion", "nachdenken", "riflessione", "reflection",
    "méditation", "meditation", "meditazione",
    "lenteur", "langsamkeit", "lentezza", "slowness", "slow",
    "silence", "stille", "silenzio", "pause", "arrêt", "stopp",
    # 현상 발견
    "découvrir", "entdecken", "scoprire", "discover", "remarquer", "bemerken",
    "étrange", "seltsam", "strano", "strange", "bizarre", "merkwürdig",
    "inattendu", "unerwartet", "inaspettato", "unexpected",
]

# 4. 새로운 시각 키워드 (15점 만점)
NOVELTY_KEYWORDS = [
    # 역설·반전
    "paradoxe", "paradox", "paradosso", "contre-intuitif", "kontraintuitiv",
    "contrairement", "im gegenteil", "al contrario", "contrary", "actually",
    "en réalité", "eigentlich", "in realtà", "actually", "perhaps",
    # 재고·재해석
    "repenser", "überdenken", "ripensare", "rethink", "reconsider",
    "nouveau regard", "neue sichtweise", "nuovo sguardo", "new perspective",
    "autrement", "anders", "diversamente", "differently",
    "méconnu", "unbekannt", "sconosciuto", "overlooked", "forgotten",
    "surprenant", "überraschend", "sorprendente", "surprising",
    # 질문 뒤집기
    "vraiment", "wirklich", "davvero", "really", "vraie question",
    "il faut se demander", "man muss fragen", "bisogna chiedersi",
]


def _count_keywords(text: str, keywords: list) -> int:
    """소문자 변환 후 키워드 매칭 개수 반환"""
    t = text.lower()
    return sum(1 for kw in keywords if kw in t)


def score_item(item: dict) -> dict:
    """
    항목에 우선순위 점수를 부여하고 점수 세부 내역을 추가한다.
    반환값: item에 'priority', 'scoreDetail' 필드 추가된 dict
    """
    text = f"{item.get('title', '')} {item.get('description', '')}".lower()

    # ── 1. 일상·사회현상 밀접도 (40점) ──
    daily_hits = _count_keywords(text, DAILY_LIFE_KEYWORDS)
    # 의문형 제목인지 (현상을 질문으로 던지는 형태)
    is_question = bool(re.search(
        r'\b(pourquoi|warum|perché|why|comment|wie|come|how|est-ce|should|can we)\b',
        text
    ))
    score_daily = min(40, daily_hits * 5 + (10 if is_question else 0))

    # ── 2. 철학적 연결 (25점) ──
    phil_hits   = _count_keywords(text, PHILOSOPHY_KEYWORDS)
    score_phil  = min(25, phil_hits * 5)

    # ── 3. 플라뇌르 정체성 (20점) ──
    flan_hits   = _count_keywords(text, FLANEUR_KEYWORDS)
    score_flan  = min(20, flan_hits * 4)

    # ── 4. 새로운 시각 (15점) ──
    nov_hits    = _count_keywords(text, NOVELTY_KEYWORDS)
    score_nov   = min(15, nov_hits * 5)

    total = score_daily + score_phil + score_flan + score_nov

    item["priority"] = total
    item["scoreDetail"] = {
        "daily":    score_daily,   # 일상·사회현상 밀접도
        "phil":     score_phil,    # 철학적 연결
        "flaneur":  score_flan,    # 플라뇌르 정체성
        "novelty":  score_nov,     # 새로운 시각
        "total":    total,
    }
    return item


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HTML 스트리퍼
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HTTP 요청
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_url(url: str, timeout: int = 15, retries: int = 3) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; FlaneurBot/1.0; "
            "+https://github.com/flaneur)"
        ),
        "Accept": "application/rss+xml, application/atom+xml, text/xml, */*",
    }
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as e:
            # 4xx는 재시도해도 무의미
            if 400 <= e.code < 500:
                raise
            last_err = e
        except Exception as e:
            last_err = e
        if attempt < retries - 1:
            wait = 2 ** attempt  # 1s → 2s
            print(f"재시도 {attempt + 1}/{retries - 1} ({wait}s 대기)...", end=" ", flush=True)
            time.sleep(wait)
    raise last_err


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 피드 파싱
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def parse_youtube(xml_text: str) -> list:
    root  = ET.fromstring(xml_text)
    items = []
    for entry in root.findall("atom:entry", NS):
        title    = entry.findtext("atom:title",     default="", namespaces=NS)
        video_id = entry.findtext("yt:videoId",     default="", namespaces=NS)
        pub_date = entry.findtext("atom:published", default="", namespaces=NS)
        link_el  = entry.find("atom:link[@rel='alternate']", NS)
        url      = link_el.get("href", "") if link_el is not None else (
                   f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
        thumb_el = entry.find("media:group/media:thumbnail", NS)
        thumb    = thumb_el.get("url", "") if thumb_el is not None else ""
        desc_el  = entry.find("media:group/media:description", NS)
        desc     = strip_html(desc_el.text if desc_el is not None else "")[:500]

        items.append({
            "title":       title.strip(),
            "url":         url,
            "description": desc,
            "date":        pub_date[:10],
            "thumbnail":   thumb,
            "videoId":     video_id,
        })
    return items[:15]


def parse_rss(xml_text: str) -> list:
    root    = ET.fromstring(xml_text)
    channel = root.find("channel") or root
    items   = []

    for item in channel.findall("item")[:15]:
        title = item.findtext("title", default="").strip()
        url   = item.findtext("link",  default="").strip()
        desc  = strip_html(item.findtext("description", default=""))[:500]
        date  = item.findtext("pubDate", default="")[:16]

        thumb = ""
        mc = item.find("{http://search.yahoo.com/mrss/}content")
        if mc is not None:
            thumb = mc.get("url", "")
        enc = item.find("enclosure")
        if not thumb and enc is not None and enc.get("type", "").startswith("image"):
            thumb = enc.get("url", "")

        items.append({
            "title": title, "url": url, "description": desc,
            "date": date, "thumbnail": thumb, "videoId": "",
        })
    return items


def parse_feed(xml_text: str, source_type: str) -> list:
    if source_type == "youtube" or "<feed" in xml_text[:200]:
        return parse_youtube(xml_text)
    return parse_rss(xml_text)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    os.makedirs(FEEDS_DIR, exist_ok=True)

    with open(SOURCES_PATH, encoding="utf-8") as f:
        sources = json.load(f)["sources"]

    results = {"ok": [], "fail": []}

    for src in sources:
        sid      = src["id"]
        rss_url  = src.get("rssUrl", "")
        src_type = src.get("type", "rss")

        if not rss_url:
            print(f"[SKIP] {sid} — rssUrl 없음")
            results["fail"].append(sid)
            continue

        print(f"[FETCH] {sid} ← {rss_url}", end=" ... ", flush=True)
        try:
            xml_text = fetch_url(rss_url)
            items    = parse_feed(xml_text, src_type)

            # 각 항목에 우선순위 점수 부여 후 내림차순 정렬
            scored = sorted(
                [score_item(i) for i in items],
                key=lambda x: x["priority"],
                reverse=True,
            )

            payload = {
                "sourceId":   sid,
                "sourceName": src["name"],
                "fetchedAt":  datetime.now(timezone.utc).isoformat(),
                "items":      scored,
            }

            out_path = os.path.join(FEEDS_DIR, f"{sid}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            # 상위 3개 점수 출력
            top = scored[:3]
            print(f"OK ({len(items)}개, 상위점수: {[i['priority'] for i in top]})")
            results["ok"].append(sid)

        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}")
            results["fail"].append(sid)
        except Exception as e:
            print(f"ERR — {e}")
            results["fail"].append(sid)

    # 수집 요약
    summary = {
        "lastRun": datetime.now(timezone.utc).isoformat(),
        "ok":      results["ok"],
        "fail":    results["fail"],
        "total":   len(sources),
        "fetched": len(results["ok"]),
    }
    with open(os.path.join(FEEDS_DIR, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {len(results['ok'])}/{len(sources)} 성공")
    if results["fail"]:
        print(f"실패: {', '.join(results['fail'])}")

    if len(results["fail"]) > len(sources) / 2:
        sys.exit(1)


if __name__ == "__main__":
    main()
