"""
플라뇌르 — 발행 이력 백필 스크립트 (일회성/재실행 가능)

git에 커밋된 모든 과거 data/news.json 버전에서 글 제목·요약·태그를 추출해
data/published_history.json 을 풍부한 형태로 재구성한다.

중복 필터(curate.py)가 과거 글과 대조할 수 있도록, 각 주차에
  { "week", "tags": [...], "articles": [{"title","summary","philosopher","philosophers","tags"}] }
구조로 저장한다. (기존 tags-only 항목과 하위 호환)

`philosopher` 필드는 2026-08-07 이후 발행분에만 들어 있으므로, 그 이전 글은
본문(detail)에서 철학자 이름을 사전 매칭으로 추출해 채운다. 이 목록이 curate.py의
크로스위크 철학자 배제(PHIL_LOOKBACK)에 쓰인다 — 장자·메를로퐁티 반복 방지.

실행: python scripts/backfill_history.py
"""

import json
import os
import re
import subprocess

ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_REL     = "data/news.json"
HISTORY_PATH = os.path.join(ROOT, "data", "published_history.json")
MAX_WEEKS    = 26


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 철학자 이름 사전 — '한글 (Latin)' 정규 표기 → 본문에서 찾을 한글 표기들
# curate.py의 philosopher_keys()가 괄호 안 라틴 성(姓)으로 키를 만들므로 표기를 맞춘다.
# 짧고 흔한 한글 이름(융·설·벡·쿤·센·프롬 등)은 오탐이 커서 성+이름 형태만 매칭한다.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PHILOSOPHERS = {
    # ── 고대·중세 ──
    "소크라테스 (Socrates)":            ["소크라테스"],
    "플라톤 (Plato)":                   ["플라톤"],
    "아리스토텔레스 (Aristotle)":        ["아리스토텔레스"],
    "에피쿠로스 (Epicurus)":            ["에피쿠로스"],
    "디오게네스 (Diogenes)":            ["디오게네스"],
    "세네카 (Seneca)":                  ["세네카"],
    "에픽테토스 (Epictetus)":           ["에픽테토스"],
    "마르쿠스 아우렐리우스 (Marcus Aurelius)": ["아우렐리우스"],
    "키케로 (Cicero)":                  ["키케로"],
    "아우구스티누스 (Augustine)":        ["아우구스티누스"],
    "토마스 아퀴나스 (Thomas Aquinas)":  ["아퀴나스"],
    # ── 근대 ──
    "몽테뉴 (Michel de Montaigne)":     ["몽테뉴"],
    "데카르트 (Rene Descartes)":        ["데카르트"],
    "파스칼 (Blaise Pascal)":           ["파스칼"],
    "스피노자 (Baruch Spinoza)":        ["스피노자"],
    "라이프니츠 (Leibniz)":             ["라이프니츠"],
    "홉스 (Thomas Hobbes)":             ["홉스"],
    "존 로크 (John Locke)":             ["로크"],
    "흄 (David Hume)":                  ["데이비드 흄", "흄은", "흄의", "흄이"],
    "루소 (Jean-Jacques Rousseau)":     ["루소"],
    "볼테르 (Voltaire)":                ["볼테르"],
    "칸트 (Immanuel Kant)":             ["칸트"],
    "헤겔 (Hegel)":                     ["헤겔"],
    "쇼펜하우어 (Schopenhauer)":        ["쇼펜하우어"],
    "키르케고르 (Kierkegaard)":         ["키르케고르", "키에르케고르"],
    "마르크스 (Karl Marx)":             ["마르크스"],
    "니체 (Friedrich Nietzsche)":       ["니체"],
    "소로 (Henry David Thoreau)":       ["소로"],
    "에머슨 (Ralph Waldo Emerson)":     ["에머슨"],
    "밀 (John Stuart Mill)":            ["존 스튜어트 밀"],
    "토크빌 (Tocqueville)":             ["토크빌"],
    # ── 20세기 대륙 ──
    "프로이트 (Sigmund Freud)":         ["프로이트"],
    "카를 융 (Carl Jung)":              ["카를 융", "칼 융"],
    "베르그송 (Henri Bergson)":         ["베르그송"],
    "후설 (Edmund Husserl)":            ["후설"],
    "하이데거 (Martin Heidegger)":      ["하이데거"],
    "야스퍼스 (Karl Jaspers)":          ["야스퍼스"],
    "가다머 (Gadamer)":                 ["가다머"],
    "사르트르 (Jean-Paul Sartre)":      ["사르트르"],
    "보부아르 (Simone de Beauvoir)":    ["보부아르"],
    "카뮈 (Albert Camus)":              ["카뮈"],
    "메를로퐁티 (Maurice Merleau-Ponty)": ["메를로퐁티", "메를로-퐁티"],
    "레비나스 (Emmanuel Levinas)":      ["레비나스"],
    "리쾨르 (Paul Ricoeur)":            ["리쾨르"],
    "시몬 베유 (Simone Weil)":          ["시몬 베유", "시몬 베이유"],
    "가브리엘 마르셀 (Gabriel Marcel)": ["가브리엘 마르셀"],
    "바슐라르 (Gaston Bachelard)":      ["바슐라르"],
    "캉길렘 (Georges Canguilhem)":      ["캉길렘"],
    "알튀세르 (Louis Althusser)":       ["알튀세르"],
    "푸코 (Michel Foucault)":           ["푸코"],
    "들뢰즈 (Gilles Deleuze)":          ["들뢰즈"],
    "가타리 (Felix Guattari)":          ["가타리"],
    "데리다 (Jacques Derrida)":         ["데리다"],
    "라캉 (Jacques Lacan)":             ["라캉"],
    "바르트 (Roland Barthes)":          ["롤랑 바르트"],
    "부르디외 (Pierre Bourdieu)":       ["부르디외"],
    "보드리야르 (Jean Baudrillard)":    ["보드리야르"],
    "리오타르 (Lyotard)":               ["리오타르"],
    "랑시에르 (Jacques Ranciere)":      ["랑시에르"],
    "바디우 (Alain Badiou)":            ["바디우"],
    "아감벤 (Giorgio Agamben)":         ["아감벤"],
    "네그리 (Antonio Negri)":           ["네그리"],
    "지젝 (Slavoj Zizek)":              ["지젝"],
    "르페브르 (Henri Lefebvre)":        ["르페브르"],
    "기 드보르 (Guy Debord)":           ["드보르"],
    "미셸 드 세르토 (Michel de Certeau)": ["드 세르토", "세르토"],
    "시몽동 (Gilbert Simondon)":        ["시몽동"],
    "스티글레르 (Bernard Stiegler)":    ["스티글레르"],
    "라투르 (Bruno Latour)":            ["라투르"],
    "미셸 세르 (Michel Serres)":        ["미셸 세르"],
    "카스토리아디스 (Castoriadis)":     ["카스토리아디스"],
    "앙드레 고르 (Andre Gorz)":         ["앙드레 고르"],
    "자크 엘륄 (Jacques Ellul)":        ["엘륄"],
    "이반 일리치 (Ivan Illich)":        ["일리치"],
    "클레르 마랭 (Claire Marin)":       ["클레르 마랭"],
    "이리가레 (Luce Irigaray)":         ["이리가레"],
    "크리스테바 (Julia Kristeva)":      ["크리스테바"],
    "파농 (Frantz Fanon)":              ["파농"],
    "에드워드 사이드 (Edward Said)":    ["에드워드 사이드"],
    # ── 프랑크푸르트학파·독일 ──
    "아도르노 (Theodor Adorno)":        ["아도르노"],
    "호르크하이머 (Horkheimer)":        ["호르크하이머"],
    "발터 벤야민 (Walter Benjamin)":    ["벤야민"],
    "마르쿠제 (Herbert Marcuse)":       ["마르쿠제"],
    "에리히 프롬 (Erich Fromm)":        ["에리히 프롬"],
    "한나 아렌트 (Hannah Arendt)":      ["아렌트"],
    "하버마스 (Jurgen Habermas)":       ["하버마스"],
    "악셀 호네트 (Axel Honneth)":       ["호네트"],
    "하르트무트 로자 (Hartmut Rosa)":   ["하르트무트 로자", "로자의 가속"],
    "슬로터다이크 (Peter Sloterdijk)":  ["슬로터다이크"],
    "마르쿠스 가브리엘 (Markus Gabriel)": ["마르쿠스 가브리엘"],
    "한병철 (Byung-Chul Han)":          ["한병철"],
    "블로흐 (Ernst Bloch)":             ["에른스트 블로흐"],
    "카를 슈미트 (Carl Schmitt)":       ["카를 슈미트", "칼 슈미트"],
    "귄터 안더스 (Gunther Anders)":     ["귄터 안더스"],
    # ── 사회학·인접 ──
    "막스 베버 (Max Weber)":            ["막스 베버"],
    "뒤르켐 (Emile Durkheim)":          ["뒤르켐"],
    "짐멜 (Georg Simmel)":              ["짐멜"],
    "노르베르트 엘리아스 (Norbert Elias)": ["노르베르트 엘리아스"],
    "고프먼 (Erving Goffman)":          ["고프먼"],
    "지그문트 바우만 (Zygmunt Bauman)": ["바우만"],
    "기든스 (Anthony Giddens)":         ["기든스"],
    "루만 (Niklas Luhmann)":            ["루만"],
    "울리히 벡 (Ulrich Beck)":          ["울리히 벡"],
    "리처드 세넷 (Richard Sennett)":    ["리처드 세넷", "세넷"],
    "매클루언 (Marshall McLuhan)":      ["매클루언", "맥루한"],
    "닐 포스트먼 (Neil Postman)":       ["포스트먼"],
    "셰리 터클 (Sherry Turkle)":        ["셰리 터클", "터클"],
    "조너선 하이트 (Jonathan Haidt)":   ["하이트"],
    "유발 하라리 (Yuval Harari)":       ["하라리"],
    # ── 영미 분석·정치철학 ──
    "비트겐슈타인 (Ludwig Wittgenstein)": ["비트겐슈타인"],
    "버트런드 러셀 (Bertrand Russell)": ["버트런드 러셀"],
    "화이트헤드 (Whitehead)":           ["화이트헤드"],
    "존 듀이 (John Dewey)":             ["존 듀이"],
    "윌리엄 제임스 (William James)":    ["윌리엄 제임스"],
    "퍼스 (Charles Peirce)":            ["찰스 퍼스", "퍼스의 기호"],
    "포퍼 (Karl Popper)":               ["포퍼"],
    "토머스 쿤 (Thomas Kuhn)":          ["토머스 쿤", "토마스 쿤"],
    "콰인 (Quine)":                     ["콰인"],
    "로티 (Richard Rorty)":             ["로티"],
    "존 롤스 (John Rawls)":             ["롤스"],
    "노직 (Robert Nozick)":             ["노직"],
    "마이클 샌델 (Michael Sandel)":     ["샌델"],
    "매킨타이어 (Alasdair MacIntyre)":  ["매킨타이어"],
    "찰스 테일러 (Charles Taylor)":     ["찰스 테일러"],
    "이사야 벌린 (Isaiah Berlin)":      ["이사야 벌린"],
    "누스바움 (Martha Nussbaum)":       ["누스바움"],
    "피터 싱어 (Peter Singer)":         ["피터 싱어"],
    "아마르티아 센 (Amartya Sen)":      ["아마르티아 센"],
    "주디스 버틀러 (Judith Butler)":    ["주디스 버틀러", "버틀러"],
    "도나 해러웨이 (Donna Haraway)":    ["해러웨이"],
    "벨 훅스 (bell hooks)":             ["벨 훅스"],
    "아이리스 머독 (Iris Murdoch)":     ["아이리스 머독"],
    "버나드 윌리엄스 (Bernard Williams)": ["버나드 윌리엄스"],
    "앤스컴 (Elizabeth Anscombe)":      ["앤스컴"],
    "데릭 파핏 (Derek Parfit)":         ["파핏"],
    "토머스 네이글 (Thomas Nagel)":     ["네이글"],
    "존 설 (John Searle)":              ["존 설"],
    "대니얼 데닛 (Daniel Dennett)":     ["데닛"],
    "차머스 (David Chalmers)":          ["차머스"],
    # ── 동아시아 ──
    "공자 (Confucius)":                 ["공자"],
    "맹자 (Mencius)":                   ["맹자"],
    "순자 (Xunzi)":                     ["순자"],
    "노자 (Laozi)":                     ["노자"],
    "장자 (Zhuangzi)":                  ["장자"],
    "묵자 (Mozi)":                      ["묵자"],
    "한비자 (Hanfeizi)":                ["한비자"],
    "붓다 (Buddha)":                    ["붓다", "석가모니"],
    "나가르주나 (Nagarjuna)":           ["나가르주나", "용수"],
    "도겐 (Dogen)":                     ["도겐"],
    "니시다 기타로 (Kitaro Nishida)":   ["니시다 기타로", "니시다"],
    "와쓰지 데쓰로 (Tetsuro Watsuji)":  ["와쓰지"],
    "스즈키 다이세쓰 (Daisetsu Suzuki)": ["스즈키 다이세쓰"],
    "가라타니 고진 (Kojin Karatani)":   ["가라타니"],
    "마루야마 마사오 (Masao Maruyama)": ["마루야마 마사오"],
    "원효 (Wonhyo)":                    ["원효"],
    "퇴계 이황 (Toegye)":               ["퇴계", "이황"],
    "정약용 (Jeong Yak-yong)":          ["정약용", "다산 정약용"],
}


def extract_philosophers(text: str) -> list:
    """본문에서 언급된 철학자를 등장 횟수 순으로 반환 ('한글 (Latin)' 정규 표기)."""
    if not text:
        return []
    counts = {}
    for canon, aliases in PHILOSOPHERS.items():
        n = sum(text.count(a) for a in aliases)
        if n:
            counts[canon] = n
    return [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])]


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
        articles = []
        for it in items:
            title = (it.get("title") or "").strip()
            if not title:
                continue
            # 본문 전체에서 언급된 철학자 (크로스위크 배제 목록용)
            body = " ".join([title, it.get("summary") or "", it.get("detail") or ""])
            mentioned = extract_philosophers(body)
            # 대표 철학자: 발행 당시 기록된 값 우선, 없으면 가장 많이 언급된 인물
            primary = (it.get("philosopher") or "").strip() or (mentioned[0] if mentioned else "")
            articles.append({
                "title":        title,
                "summary":      (it.get("summary") or "").strip(),
                "philosopher":  primary,
                "philosophers": mentioned,
                "tags":         it.get("tags", []),
            })
        flat_tags = list(dict.fromkeys(t for a in articles for t in a["tags"]))
        weeks[wk] = {"week": wk, "tags": flat_tags, "articles": articles}

    ordered = sorted(weeks.values(), key=lambda e: week_sort_key(e["week"]))
    ordered = ordered[-MAX_WEEKS:]

    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump({"weeks": ordered}, f, ensure_ascii=False, indent=2)

    total_articles = sum(len(e["articles"]) for e in ordered)
    no_phil = sum(1 for e in ordered for a in e["articles"] if not a["philosopher"])
    print(f"백필 완료: {len(ordered)}개 주차 / 글 {total_articles}개 → data/published_history.json")
    print(f"  철학자 식별: {total_articles - no_phil}개 / 미식별 {no_phil}개")
    for e in ordered:
        phs = [a["philosopher"] for a in e["articles"] if a["philosopher"]]
        print(f"  {e['week']}: 글 {len(e['articles'])}개, 태그 {len(e['tags'])}개, 철학자 {len(set(phs))}명")


if __name__ == "__main__":
    main()
