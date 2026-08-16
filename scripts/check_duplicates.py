"""
플라뇌르 — 발행 중복 검증 스크립트 (API 호출 없음)

curate.py의 로컬 중복 게이트(URL·원제·제목·요약 유사도)를 그대로 써서 두 가지를 검사한다.

  python scripts/check_duplicates.py              # 발행 검증: data/news.json vs 과거 이력
  python scripts/check_duplicates.py --selftest   # 게이트 회귀 검사: 이력 전체를 자기 대조

발행 검증은 GitHub Actions 마지막 단계에서 돌린다. 큐레이션 단계의 게이트가 뚫려도
여기서 드러나므로, 같은 글이 두 번 발행된 것을 사람이 몇 주 뒤에 발견하는 일이 없다.
(2026-W32 라디오프랑스 글이 W34에 같은 URL로 재발행된 사고 → 이 검사 도입)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from curate import (  # noqa: E402
    HISTORY_PATH, NEWS_PATH, dup_score, normalize_url,
)


def load_history_weeks() -> list:
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        return json.load(f).get("weeks", [])


def check_published() -> int:
    """news.json의 이번 주 발행분이 과거 이력(다른 주차)과 겹치는지 검사. 반환: 종료 코드."""
    if not os.path.exists(NEWS_PATH):
        print("data/news.json 없음 — 검사 생략")
        return 0
    with open(NEWS_PATH, encoding="utf-8") as f:
        news = json.load(f)
    week = news.get("week", "")
    items = news.get("items", [])

    past = []
    for entry in load_history_weeks():
        if entry.get("week") == week:
            continue                        # 이번 주 자신은 제외
        for art in entry.get("articles", []):
            past.append({**art, "week": entry.get("week", "")})

    print(f"발행 주차 {week}: 글 {len(items)}개 / 과거 이력 {len(past)}개와 대조")

    hits = []
    # (a) 과거 주차와의 중복
    for it in items:
        for p in past:
            reason, _, _, _ = dup_score(it, p)
            if reason:
                hits.append((it.get("title", ""), f"{p.get('week','')} {p.get('title','')}", reason))
                break
    # (b) 같은 주 안의 중복 (URL 중복 포함)
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            reason, _, _, _ = dup_score(a, b)
            if reason:
                hits.append((a.get("title", ""), f"{week}(같은 주) {b.get('title','')}", reason))

    missing_url = [it.get("title", "") for it in items if not normalize_url(it.get("sourceUrl", ""))]
    if missing_url:
        print("::warning::sourceUrl 없는 항목(URL 게이트 대상 제외): " + ", ".join(missing_url))

    if hits:
        for title, matched, reason in hits:
            print(f"::error::중복 발행 의심 — '{title}' ↔ '{matched}' ({reason})")
        print(f"::error::중복 {len(hits)}건 — 해당 글을 교체하고 curate.py 게이트를 점검하세요.")
        return 1

    print("✓ 과거 이력·같은 주 대조 결과 중복 없음")
    return 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 회귀 검사 고정 케이스
# 실제로 두 번 발행됐던 글(양성)과, 제목 틀만 닮은 남남 글(음성)을 값으로 박아 둔다.
# 이력(published_history.json)은 26주만 보관돼 사례가 밀려나므로 값으로 고정한다.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _a(title, summary, url="", original=""):
    return {"title": title, "summary": summary, "sourceUrl": url, "originalTitle": original}


# 반드시 '중복'으로 잡혀야 하는 쌍 (모두 실제 중복 발행 사례)
POSITIVES = [
    ("W32↔W34 나탈리 드세이 — 같은 URL",
     _a("기술을 넘어설 때 비로소 예술이 된다", "완벽한 기교를 버린 순간, 소프라노는 왜 더 깊이 울렸는가?",
        "https://www.radiofrance.fr/franceinter/podcasts/sous-le-soleil-de-platon/sous-le-soleil-de-platon-du-vendredi-31-juillet-2026-8945081",
        "Natalie Dessay : Comment s’affranchir de la technique pour laisser place à l’émotion ?"),
     _a("기교를 버릴 때 비로소 예술이 된다", "완벽한 기술을 내려놓은 순간, 소프라노는 왜 더 깊이 울렸는가?",
        "https://www.radiofrance.fr/franceinter/podcasts/sous-le-soleil-de-platon/sous-le-soleil-de-platon-du-vendredi-31-juillet-2026-8945081",
        "Natalie Dessay : Comment s’affranchir de la technique pour laisser place à l’émotion ?")),

    ("W32↔W34 나탈리 드세이 — URL·원제가 없어도 (텍스트만)",
     _a("기술을 넘어설 때 비로소 예술이 된다", "완벽한 기교를 버린 순간, 소프라노는 왜 더 깊이 울렸는가?"),
     _a("기교를 버릴 때 비로소 예술이 된다", "완벽한 기술을 내려놓은 순간, 소프라노는 왜 더 깊이 울렸는가?")),

    ("원제 동일 — URL과 제목을 모두 바꿔도",
     _a("기교 없는 노래가 우리를 흔든다", "무대 위의 한 순간에 관하여",
        "https://www.radiofrance.fr/franceinter/podcasts/sous-le-soleil-de-platon/nouvelle-adresse-99999",
        "Natalie Dessay : Comment s'affranchir de la technique pour laisser place à l'émotion ?"),
     _a("기술을 넘어설 때 비로소 예술이 된다", "완벽한 기교를 버린 순간, 소프라노는 왜 더 깊이 울렸는가?",
        "https://www.radiofrance.fr/franceinter/podcasts/sous-le-soleil-de-platon/sous-le-soleil-de-platon-du-vendredi-31-juillet-2026-8945081",
        "Natalie Dessay : Comment s’affranchir de la technique pour laisser place à l’émotion ?")),

    ("W18↔W20 매트릭스 빨간약 — 제목 유사",
     _a("빨간 약이냐 파란 약이냐, 그 선택의 철학", "매트릭스의 그 장면이 우리 일상 깊숙이 들어와 있다면?"),
     _a("빨간 약이냐 파란 약이냐: 선택의 환상", "매트릭스의 그 장면이 지금도 우리를 사로잡는 이유는 무엇인가?")),

    ("W17↔W20 카리스마 추종 — 제목 유사",
     _a("우리는 왜 잘못된 사람을 따르는가", "카리스마 앞에서 우리의 이성은 얼마나 쉽게 무너지는가?"),
     _a("우리는 왜 틀린 사람을 따르는가", "카리스마는 내용을 이긴다—그런데 그 승리는 어떻게 작동하는가?")),

    ("W19↔W21 클레르 마랭 불완전함 — 요약 유사",
     _a("불완전한 나를 떠나는 법: 거리두기의 철학", "가족, 역할, 몸에서 벗어나려는 충동은 도망인가, 생존인가?"),
     _a("불완전한 몸, 불완전한 역할: 탈출은 배신인가", "가족과 계급과 젠더에서 떠나는 것은 도망인가, 생존인가")),

    ("W28↔W33 장자 포정해우 — 제목+요약 유사",
     _a("소의 뼈를 가르는 칼—집중이란 무엇인가", "완전한 몰입의 순간, 우리는 어디에 있는가?"),
     _a("소의 뼈를 가르는 칼—완전한 몰입이란", "완전히 몰입한 순간, 나는 어디에 있고 칼은 어디에 있는가?")),

    ("추적 파라미터·www 차이만 있는 같은 URL",
     _a("예술이 인간을 만들었다", "그림이 먼저였다면, 인간이라는 개념은 언제 생겼는가?",
        "https://aeon.co/essays/how-art-invented-humanity"),
     _a("동굴 벽에 손을 얹은 사람들", "선사시대의 흔적은 우리에게 무엇을 묻는가",
        "http://www.aeon.co/essays/how-art-invented-humanity/?utm_source=rss")),
]

# 반드시 '중복이 아님'으로 통과해야 하는 쌍 (오탐 감시)
NEGATIVES = [
    ("제목 틀만 같은 남남 (놀이 vs 분노)",
     _a("우리는 왜 점점 더 많이 노는가", "놀이가 의무가 된 시대, 즐거움을 강요받는 역설을 철학은 어떻게 보는가?",
        "https://www.philomag.com/articles/pourquoi-jouons-nous-et-de-plus-en-plus"),
     _a("우리는 왜 점점 더 화가 나는가", "지하철에서, 도로 위에서, 댓글창에서—분노의 역치는 왜 이토록 낮아졌을까",
        "https://www.youtube.com/watch?v=LgEIam0yiy0")),

    ("'어디에 있는가' 틀만 같은 남남 (몸 vs 우울)",
     _a("몸은 어디에 있는가", "화면과 현실 사이를 오가는 몸, 우리는 지금 어디에 존재하는가?",
        "https://www.youtube.com/watch?v=sE-4Leh5HqM"),
     _a("우울할 때 '나'는 어디에 있는가", "기분이 나를 지배할 때, 나라는 존재는 과연 얼마나 단단한가?",
        "https://www.philomag.com/articles/en-cas-de-besoin-la-depression-la-bipolarite-et-la-nature-fictive-du-moi")),

    ("'어떻게 ~하는가' 틀만 같은 남남 (카페 vs 고정관념)",
     _a("카페는 어떻게 역사를 만드는가", "커피 한 잔 앞에서 싹튼 것들—모더니즘과 혁명, 그 갈림길의 철학",
        "https://aeon.co/essays/viennas-cafes-inspired-poets-belgrades-bred-dissent"),
     _a("우리는 어떻게 미래를 만나는가", "일반화는 편견인가, 생존의 도구인가—고정관념의 두 얼굴",
        "https://aeon.co/essays/when-is-stereotyping-a-handy-tool-and-when-is-it-a-sin")),

    ("채널 URL 공유 — 피드가 항목 URL을 주지 않은 서로 다른 글",
     _a("가난은 왜 눈에 보이지 않는가", "보이지 않는 가난에 대하여", "https://www.radiofrance.fr"),
     _a("두 번째 기회는 오지 않는다", "실패 이후의 삶에 대하여", "https://www.radiofrance.fr")),

    ("같은 소스의 다른 영상 (URL 뒷부분만 다름)",
     _a("요리는 어떻게 시가 되는가", "부엌의 반복 노동에서 무엇이 태어나는가",
        "https://www.youtube.com/watch?v=AAAAAAAAAAA"),
     _a("우리는 왜 술을 마시는가", "취기는 우리를 어디로 데려가는가",
        "https://www.youtube.com/watch?v=BBBBBBBBBBB")),

    ("아주 짧은 제목·요약 (짧은 문자열 보호 장치)",
     _a("몸의 기억", "짧은 글", "https://example.com/a"),
     _a("몸의 기록", "짧은 곳", "https://example.com/b")),

    ("URL·원제가 둘 다 비어 있는 글끼리 (빈 값 일치를 중복으로 보면 안 된다)",
     _a("정치 얘기는 왜 항상 허공에서 끝나는가", "대화가 평행선을 달릴 때 무엇이 어긋나 있는가"),
     _a("결혼식은 무엇을 위한 축제인가", "예식이라는 형식은 무엇을 지탱하는가")),
]


def selftest() -> int:
    """게이트 회귀 검사 — 고정 케이스 + 현재 이력 스캔(참고용)."""
    failed = 0

    print("── 반드시 중복으로 잡아야 하는 쌍 ──")
    for label, a, b in POSITIVES:
        reason, ts, ss, os_ = dup_score(a, b)
        ok = bool(reason)
        print(f"  {'✓' if ok else '✗'} {label}\n      → {reason or '통과됨(놓침)'} "
              f"(제목 {ts:.2f} / 요약 {ss:.2f} / 원제 {os_:.2f})")
        if not ok:
            failed += 1
            print(f"::error::중복을 놓쳤습니다 — {label}")

    print("\n── 반드시 통과시켜야 하는 쌍 (오탐 감시) ──")
    for label, a, b in NEGATIVES:
        reason, ts, ss, os_ = dup_score(a, b)
        ok = not reason
        print(f"  {'✓' if ok else '✗'} {label}\n      → {reason or '통과'} "
              f"(제목 {ts:.2f} / 요약 {ss:.2f} / 원제 {os_:.2f})")
        if not ok:
            failed += 1
            print(f"::error::중복이 아닌 글을 막았습니다 — {label}")

    # 참고: 현재 이력 안에 남아 있는 중복 (실패로 처리하지 않는다 — 이미 발행된 과거분)
    arts = []
    for entry in load_history_weeks():
        for art in entry.get("articles", []):
            arts.append({**art, "week": entry.get("week", "")})
    flagged = []
    pairs = 0
    for i, a in enumerate(arts):
        for b in arts[i + 1:]:
            pairs += 1
            reason, _, _, _ = dup_score(a, b)
            if reason:
                flagged.append((a["week"], a.get("title", ""), b["week"], b.get("title", ""), reason))

    print(f"\n── 참고: 보관 이력 {len(arts)}개({pairs}쌍) 자기 대조 → {len(flagged)}쌍 적발 "
          f"({len(flagged)/max(pairs,1)*100:.3f}%) ──")
    for wa, ta, wb, tb, reason in sorted(flagged):
        print(f"  [{reason}] {wa} {ta}  ↔  {wb} {tb}")

    if failed:
        print(f"\n::error::회귀 검사 {failed}건 실패 — curate.py의 임계값·게이트를 점검하세요.")
        return 1
    print(f"\n✓ 회귀 검사 통과 (양성 {len(POSITIVES)}건 적발 / 음성 {len(NEGATIVES)}건 통과)")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else check_published())
