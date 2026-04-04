/* =========================================
   플라뇌르 — 관리자 패널 스크립트
   ========================================= */

// ── 상태 ──
let sources   = [];
let newsData  = { week: '', weekLabel: '', theme: '', items: [] };
let activeSource = null;
let feedItems    = [];        // 현재 소스의 RSS 항목들
let editingItem  = null;      // 편집 중인 아이템 (null=신규)
let ytApiKey     = localStorage.getItem('flaneur_yt_api') || '';

// ── 초기화 ──
async function init() {
  await Promise.all([loadSources(), loadCurrentNews()]);
  renderSidebar();
  renderWeekItems();
  renderWeekMeta();
  bindEvents();
  updatePublishBar();
}

async function loadSources() {
  const res = await fetch('data/sources.json?v=' + Date.now());
  const d   = await res.json();
  sources   = d.sources;
}

async function loadCurrentNews() {
  try {
    const res = await fetch('data/news.json?v=' + Date.now());
    newsData  = await res.json();
  } catch {
    newsData = { week: '', weekLabel: '', theme: '', items: [] };
  }
}

// ── 사이드바 ──
function renderSidebar() {
  const sidebar = document.getElementById('source-list');
  sidebar.innerHTML = '';

  const days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'];
  const dayNames = { monday:'월요일', tuesday:'화요일', wednesday:'수요일', thursday:'목요일', friday:'금요일' };

  days.forEach(day => {
    const daySources = sources.filter(s => s.day === day);
    if (!daySources.length) return;

    const label = document.createElement('div');
    label.className = 'admin-sidebar__title';
    label.textContent = dayNames[day];
    sidebar.appendChild(label);

    daySources.forEach(src => {
      const btn = document.createElement('button');
      btn.className = 'source-btn' + (activeSource?.id === src.id ? ' active' : '');
      btn.innerHTML = `
        <span class="source-btn__flag">${src.flag}</span>
        <div class="source-btn__info">
          <div class="source-btn__name">${src.name}</div>
          <div class="source-btn__day">${src.countryLabel}</div>
        </div>
        <span class="source-btn__badge source-btn__badge--${src.type === 'youtube' ? 'yt' : 'rss'}">
          ${src.type === 'youtube' ? 'YT' : 'RSS'}
        </span>
      `;
      btn.addEventListener('click', () => selectSource(src));
      sidebar.appendChild(btn);
    });
  });
}

// ── 소스 선택 ──
async function selectSource(src) {
  activeSource = src;
  renderSidebar();

  const main = document.getElementById('feed-area');
  main.innerHTML = `
    <div class="admin-header">
      <h2>${src.flag} ${src.name}</h2>
      <p>${src.description}</p>
    </div>
    <div id="feed-status" class="feed-status feed-status--loading">피드를 불러오는 중…</div>
    <div id="feed-list" class="feed-list"></div>
  `;

  await loadFeed(src);
}

// ── RSS/YouTube 피드 로딩 ──
async function loadFeed(src) {
  const statusEl = document.getElementById('feed-status');
  const listEl   = document.getElementById('feed-list');

  try {
    // ① 캐시 우선 — GitHub Actions가 저장한 data/feeds/{id}.json 시도
    let items  = [];
    let source = 'cache';

    try {
      const cacheRes = await fetch(`data/feeds/${src.id}.json?v=${Date.now()}`);
      if (cacheRes.ok) {
        const cached   = await cacheRes.json();
        items          = cached.items || [];
        const fetchedAt = cached.fetchedAt ? new Date(cached.fetchedAt) : null;
        const ageHours  = fetchedAt ? (Date.now() - fetchedAt) / 3600000 : 999;

        if (items.length && ageHours < 25) {
          const timeStr = fetchedAt ? fetchedAt.toLocaleString('ko-KR') : '';
          statusEl.className   = 'feed-status feed-status--ok';
          statusEl.innerHTML   = `✓ ${items.length}개 캐시됨 <span style="color:var(--text-light)">(${timeStr} 수집)</span>`;
          feedItems = items;
          renderFeedList(items, src);
          return;
        }
        // 캐시가 25시간 이상 오래됐으면 라이브 재시도
        if (items.length) source = 'stale-cache';
      }
    } catch (_) { /* 캐시 없음 — 라이브로 폴백 */ }

    // ② 라이브 피드 — CORS 프록시 (폴백)
    statusEl.className = 'feed-status feed-status--loading';
    statusEl.textContent = source === 'stale-cache'
      ? '캐시가 오래됨. 최신 피드 재시도 중…'
      : '캐시 없음. 라이브 피드 시도 중…';

    items = await fetchLiveFeed(src);
    feedItems = items;

    if (!items.length) {
      statusEl.className = 'feed-status feed-status--error';
      statusEl.textContent = '피드 로드 실패. 직접 입력을 이용해 주세요.';
      showManualInput(src);
      return;
    }

    statusEl.className = 'feed-status feed-status--ok';
    statusEl.textContent = `✓ 라이브 ${items.length}개 로드됨`;
    renderFeedList(items, src);

  } catch (e) {
    statusEl.className = 'feed-status feed-status--error';
    statusEl.textContent = '피드 로드 실패. 직접 입력을 이용해 주세요.';
    showManualInput(src);
  }
}

// ── 라이브 피드 (CORS 프록시 폴백) ──
async function fetchLiveFeed(src) {
  const proxies = [
    url => `https://api.allorigins.win/get?url=${encodeURIComponent(url)}`,
    url => `https://corsproxy.io/?${encodeURIComponent(url)}`,
  ];

  for (const makeUrl of proxies) {
    try {
      const proxyUrl = makeUrl(src.rssUrl);
      const res      = await fetch(proxyUrl, { signal: AbortSignal.timeout(8000) });
      if (!res.ok) continue;

      let xmlText;
      const ct = res.headers.get('content-type') || '';
      if (ct.includes('json')) {
        const data = await res.json();
        xmlText = data.contents || data;
      } else {
        xmlText = await res.text();
      }

      const xml = new DOMParser().parseFromString(xmlText, 'text/xml');
      if (xml.querySelector('parsererror')) continue;

      // Atom (YouTube) vs RSS 2.0
      if (xml.querySelector('entry')) {
        return parseAtomEntries(xml);
      } else {
        return parseRssItems(xml);
      }
    } catch (_) { continue; }
  }
  return [];
}

function parseAtomEntries(xml) {
  return Array.from(xml.querySelectorAll('entry')).slice(0, 15).map(entry => ({
    title:       entry.querySelector('title')?.textContent || '',
    url:         entry.querySelector('link')?.getAttribute('href') || '',
    description: entry.querySelector('media\\:description, description')?.textContent?.slice(0, 500) || '',
    date:        entry.querySelector('published')?.textContent?.slice(0, 10) || '',
    thumbnail:   entry.querySelector('media\\:thumbnail')?.getAttribute('url') || '',
    videoId:     entry.querySelector('yt\\:videoId')?.textContent || '',
  })).map(scoreItem).sort((a, b) => b.priority - a.priority);
}

function parseRssItems(xml) {
  return Array.from(xml.querySelectorAll('item')).slice(0, 15).map(item => ({
    title:       item.querySelector('title')?.textContent || '',
    url:         item.querySelector('link')?.textContent || '',
    description: stripHtml(item.querySelector('description')?.textContent || '').slice(0, 500),
    date:        item.querySelector('pubDate')?.textContent?.slice(0, 16) || '',
    thumbnail:   '',
    videoId:     '',
  })).map(scoreItem).sort((a, b) => b.priority - a.priority);
}

function stripHtml(html) {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div.textContent || '';
}

// ── 우선순위 채점 (Python 스크립트와 동일 로직) ──
const SCORE_KEYWORDS = {
  daily: [
    'smartphone','téléphone','handy','telefono','social media','réseaux sociaux',
    'instagram','tiktok','algorithm','algorithme','notification',
    'addiction','dépendance','sucht','dipendenza','screen','écran','internet','digital',
    'travail','arbeit','lavoro','work','burnout','stress','productivity',
    'consommation','konsum','consumo','consumption','money','argent','geld','shopping',
    'solitude','einsamkeit','loneliness','famille','family','amour','liebe','amore','love',
    'anxiété','angst','ansia','anxiety','bonheur','glück','felicità','happiness',
    'dépression','depression','identité','identität','identity',
    'climat','klima','clima','climate','inégalité','inequality',
    'politique','politik','politics','quotidien','alltag','quotidiano','daily',
    'pourquoi','warum','perché','why','comment','wie','come','how',
  ],
  phil: [
    'philosophie','filosofia','philosophy','éthique','ethik','etica','ethics',
    'liberté','freiheit','libertà','freedom','vérité','wahrheit','verità','truth',
    'sens','sinn','senso','meaning','existence','existenz',
    'bonheur','glück','felicità','happiness','justice','gerechtigkeit','giustizia',
    'conscience','bewusstsein','coscienza','penser','denken','pensare',
    'question','frage','domanda','valeur','wert','valore','value',
  ],
  flaneur: [
    'observer','beobachten','osservare','observe','regarder','schauen',
    'promenade','spaziergang','passeggiata','walk','flâner','wandern',
    'quotidien','alltag','quotidiano','everyday','ordinaire','gewöhnlich',
    'détail','detail','dettaglio','small','petit','klein',
    'ville','stadt','città','city','rue','straße','strada','street','café',
    'réflexion','nachdenken','riflessione','reflection','lenteur','langsamkeit','slow',
    'silence','stille','silenzio','pause','découvrir','entdecken','scoprire',
    'étrange','seltsam','strano','strange','inattendu','unexpected',
  ],
  novelty: [
    'paradoxe','paradox','paradosso','contre-intuitif','kontraintuitiv',
    'contrairement','im gegenteil','contrary','actually','en réalité','eigentlich',
    'repenser','überdenken','ripensare','rethink','reconsider',
    'nouveau regard','neue sichtweise','new perspective','autrement','anders','differently',
    'méconnu','unbekannt','sconosciuto','overlooked','surprenant','überraschend','surprising',
    'vraiment','wirklich','davvero','really',
  ],
};

const QUESTION_RE = /\b(pourquoi|warum|perché|why|comment|wie|come|how|est-ce|should|can we)\b/i;

function scoreItem(item) {
  const text = `${item.title} ${item.description}`.toLowerCase();
  const count = (kws) => kws.filter(kw => text.includes(kw)).length;

  const isQuestion = QUESTION_RE.test(text);
  const scoreDaily   = Math.min(40, count(SCORE_KEYWORDS.daily)   * 5 + (isQuestion ? 10 : 0));
  const scorePhil    = Math.min(25, count(SCORE_KEYWORDS.phil)    * 5);
  const scoreFlaneur = Math.min(20, count(SCORE_KEYWORDS.flaneur) * 4);
  const scoreNovelty = Math.min(15, count(SCORE_KEYWORDS.novelty) * 5);
  const total = scoreDaily + scorePhil + scoreFlaneur + scoreNovelty;

  return {
    ...item,
    priority: total,
    scoreDetail: {
      daily: scoreDaily, phil: scorePhil,
      flaneur: scoreFlaneur, novelty: scoreNovelty, total,
    },
  };
}

// ── 피드 목록 렌더링 ──
function renderFeedList(items, src) {
  const listEl = document.getElementById('feed-list');
  listEl.innerHTML = '';

  // 직접 입력 버튼
  const addBtn = document.createElement('button');
  addBtn.className = 'btn btn--outline';
  addBtn.style.marginBottom = '16px';
  addBtn.innerHTML = '+ 직접 입력하기';
  addBtn.addEventListener('click', () => openEditForm(null, src));
  listEl.appendChild(addBtn);

  items.forEach(item => {
    const score  = item.scoreDetail || {};
    const total  = item.priority || 0;
    const scoreColor = total >= 50 ? 'var(--accent)' : total >= 25 ? 'var(--gold)' : 'var(--text-light)';
    const scoreBadge = total > 0 ? `
      <span title="일상${score.daily||0} + 철학${score.phil||0} + 플라뇌르${score.flaneur||0} + 새시각${score.novelty||0}"
        style="font-size:11px;font-weight:600;color:${scoreColor};white-space:nowrap">
        ★ ${total}점
      </span>` : '';

    const el = document.createElement('div');
    el.className = 'feed-item';
    el.innerHTML = `
      <div style="min-width:0;flex:1">
        <div class="feed-item__date" style="display:flex;align-items:center;gap:8px">
          <span>${item.date}</span>${scoreBadge}
        </div>
        <div class="feed-item__title">${item.title}</div>
        <div class="feed-item__desc">${item.description || '설명 없음'}</div>
      </div>
      <div class="feed-item__actions">
        <button class="feed-item__btn feed-item__btn--select">선택 →</button>
        <a href="${item.url}" target="_blank" rel="noopener" class="feed-item__btn feed-item__btn--link">원문</a>
      </div>
    `;
    el.querySelector('.feed-item__btn--select').addEventListener('click', () => {
      openEditForm(item, src);
    });
    listEl.appendChild(el);
  });
}

function showManualInput(src) {
  const listEl = document.getElementById('feed-list');
  const addBtn = document.createElement('button');
  addBtn.className = 'btn btn--primary';
  addBtn.style.marginTop = '16px';
  addBtn.innerHTML = '+ 직접 입력하기';
  addBtn.addEventListener('click', () => openEditForm(null, src));
  listEl.appendChild(addBtn);
}

// ── 편집 폼 ──
function openEditForm(feedItem, src) {
  editingItem = feedItem;
  const existing = document.getElementById('edit-panel');
  if (existing) existing.remove();

  const panel = document.createElement('div');
  panel.id = 'edit-panel';
  panel.className = 'edit-panel';

  const isNew = !feedItem;
  panel.innerHTML = `
    <div class="edit-panel__title">
      ${isNew ? '+ 새 소식 추가' : `"${feedItem.title.slice(0, 40)}…" 큐레이션`}
    </div>

    <input type="hidden" id="edit-source-url" value="${escapeAttr(feedItem?.url || '')}">
    <input type="hidden" id="edit-day"     value="${src.day}">
    <input type="hidden" id="edit-country" value="${src.country}">
    <input type="hidden" id="edit-source-id" value="${src.id}">

    <div class="form-group">
      <label class="form-label">제목 *</label>
      <input type="text" class="form-input" id="edit-title"
        value="${escapeAttr(feedItem?.title || '')}"
        placeholder="이 소식의 제목을 입력하세요">
    </div>

    <div class="form-group">
      <label class="form-label">한 줄 요약 * <span style="color:var(--text-light);font-weight:400">(카드에 표시, 100~150자)</span></label>
      <textarea class="form-textarea" id="edit-summary" style="min-height:80px"
        placeholder="독자가 클릭 전에 보는 요약입니다. 핵심 질문이나 흥미로운 지점을 담으세요.">${escapeAttr(feedItem?.description || '')}</textarea>
    </div>

    <div class="form-group">
      <label class="form-label">상세 설명 * <span style="color:var(--text-light);font-weight:400">(클릭 후 보이는 내용, 30~50줄)</span></label>
      <textarea class="form-textarea" id="edit-detail" style="min-height:360px"
        placeholder="철학적 맥락, 핵심 논증, 일상과의 연결, 이번 주 주제와의 관계를 풀어 쓰세요.&#10;&#10;단락 사이 줄바꿈으로 가독성을 높이면 좋습니다."></textarea>
      <div class="field-hint" id="edit-detail-counter">0줄</div>
    </div>

    <div class="form-row">
      <div class="form-group">
        <label class="form-label">원소스 URL *</label>
        <input type="url" class="form-input" id="edit-url"
          value="${escapeAttr(feedItem?.url || '')}"
          placeholder="https://...">
      </div>
      <div class="form-group">
        <label class="form-label">태그 <span style="color:var(--text-light);font-weight:400">(쉼표 구분)</span></label>
        <input type="text" class="form-input" id="edit-tags"
          placeholder="예: 니체, 욕망, 자기극복">
      </div>
    </div>

    <div style="display:flex;gap:12px;margin-top:8px">
      <button class="btn btn--primary" id="edit-add-btn">이번 주 소식에 추가</button>
      <button class="btn btn--ghost" id="edit-cancel-btn">취소</button>
    </div>
  `;

  document.getElementById('feed-list').after(panel);
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });

  // 줄 수 카운터
  const detailInput = panel.querySelector('#edit-detail');
  const counter = panel.querySelector('#edit-detail-counter');
  detailInput.addEventListener('input', () => {
    const lines = detailInput.value.split('\n').length;
    const chars = detailInput.value.length;
    counter.textContent = `${lines}줄 / ${chars}자`;
    counter.style.color = lines >= 30 ? 'var(--accent)' : 'var(--text-light)';
  });

  panel.querySelector('#edit-add-btn').addEventListener('click', () => addToWeek(src));
  panel.querySelector('#edit-cancel-btn').addEventListener('click', () => panel.remove());
}

// ── 이번 주 소식에 추가 ──
function addToWeek(src) {
  const title   = document.getElementById('edit-title').value.trim();
  const summary = document.getElementById('edit-summary').value.trim();
  const detail  = document.getElementById('edit-detail').value.trim();
  const url     = document.getElementById('edit-url').value.trim();
  const tagsRaw = document.getElementById('edit-tags').value;
  const tags    = tagsRaw.split(',').map(t => t.trim()).filter(Boolean);

  if (!title)   { alert('제목을 입력해 주세요.'); return; }
  if (!summary) { alert('한 줄 요약을 입력해 주세요.'); return; }
  if (!detail)  { alert('상세 설명을 입력해 주세요.'); return; }
  if (!url)     { alert('원소스 URL을 입력해 주세요.'); return; }

  const id = `${src.day.slice(0,3)}-${Date.now()}`;
  const item = {
    id,
    day:          src.day,
    dayLabel:     { monday:'월요일', tuesday:'화요일', wednesday:'수요일', thursday:'목요일', friday:'금요일' }[src.day],
    country:      src.country,
    countryLabel: src.countryLabel,
    source:       src.name,
    sourceUrl:    url,
    title,
    summary,
    detail,
    tags,
  };

  newsData.items.push(item);
  saveNewsToLocal();
  renderWeekItems();
  updatePublishBar();

  document.getElementById('edit-panel')?.remove();
  showToast(`"${title.slice(0, 20)}…" 추가됨`);
}

// ── 이번 주 목록 ──
function renderWeekItems() {
  const container = document.getElementById('week-items-list');
  if (!container) return;

  const countEl = document.getElementById('week-items-count');
  const count   = newsData.items.length;
  if (countEl) {
    countEl.textContent = `${count}개 / 목표 20개`;
    countEl.style.color = count >= 20 ? 'var(--accent)' : 'var(--gold)';
  }

  if (!count) {
    container.innerHTML = '<p style="color:var(--text-muted);font-size:14px;padding:20px 0">아직 추가된 소식이 없습니다.</p>';
    return;
  }

  container.innerHTML = '';
  const dayOrder = ['monday','tuesday','wednesday','thursday','friday'];
  const sorted   = [...newsData.items].sort(
    (a,b) => dayOrder.indexOf(a.day) - dayOrder.indexOf(b.day)
  );

  sorted.forEach(item => {
    const el = document.createElement('div');
    el.className = 'week-item';
    el.innerHTML = `
      <span class="week-item__drag">⠿</span>
      <div class="week-item__info">
        <div class="week-item__meta">${item.dayLabel} · ${item.source}</div>
        <div class="week-item__title">${item.title}</div>
      </div>
      <div class="week-item__actions">
        <button class="week-item__btn" data-id="${item.id}" data-action="edit">수정</button>
        <button class="week-item__btn week-item__btn--delete" data-id="${item.id}" data-action="delete">삭제</button>
      </div>
    `;
    el.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.action === 'delete') {
          if (!confirm('이 소식을 삭제하시겠습니까?')) return;
          newsData.items = newsData.items.filter(i => i.id !== item.id);
          saveNewsToLocal();
          renderWeekItems();
          updatePublishBar();
        } else if (btn.dataset.action === 'edit') {
          openEditExisting(item);
        }
      });
    });
    container.appendChild(el);
  });
}

// ── 기존 항목 수정 ──
function openEditExisting(item) {
  const src = sources.find(s => s.name === item.source);
  if (!src) return;

  // 탭을 피드 탭으로 전환
  switchTab('feed');
  if (activeSource?.id !== src.id) selectSource(src);

  setTimeout(() => {
    const panel = document.createElement('div');
    panel.id = 'edit-panel';
    panel.className = 'edit-panel';
    panel.innerHTML = `
      <div class="edit-panel__title">✏ 수정: ${item.title.slice(0, 40)}</div>
      <input type="hidden" id="edit-source-url" value="${escapeAttr(item.sourceUrl)}">
      <div class="form-group">
        <label class="form-label">제목</label>
        <input type="text" class="form-input" id="edit-title" value="${escapeAttr(item.title)}">
      </div>
      <div class="form-group">
        <label class="form-label">한 줄 요약</label>
        <textarea class="form-textarea" id="edit-summary" style="min-height:80px">${escapeAttr(item.summary)}</textarea>
      </div>
      <div class="form-group">
        <label class="form-label">상세 설명</label>
        <textarea class="form-textarea" id="edit-detail" style="min-height:360px">${escapeAttr(item.detail)}</textarea>
        <div class="field-hint" id="edit-detail-counter">${item.detail?.split('\n').length || 0}줄</div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">원소스 URL</label>
          <input type="url" class="form-input" id="edit-url" value="${escapeAttr(item.sourceUrl)}">
        </div>
        <div class="form-group">
          <label class="form-label">태그</label>
          <input type="text" class="form-input" id="edit-tags" value="${escapeAttr((item.tags||[]).join(', '))}">
        </div>
      </div>
      <div style="display:flex;gap:12px;margin-top:8px">
        <button class="btn btn--primary" id="edit-update-btn">저장</button>
        <button class="btn btn--ghost" id="edit-cancel-btn">취소</button>
      </div>
    `;

    const feedList = document.getElementById('feed-list');
    if (feedList) feedList.after(panel);
    panel.scrollIntoView({ behavior: 'smooth' });

    const detailInput = panel.querySelector('#edit-detail');
    const counter     = panel.querySelector('#edit-detail-counter');
    detailInput.addEventListener('input', () => {
      counter.textContent = `${detailInput.value.split('\n').length}줄`;
    });

    panel.querySelector('#edit-update-btn').addEventListener('click', () => {
      const idx = newsData.items.findIndex(i => i.id === item.id);
      if (idx < 0) return;
      newsData.items[idx] = {
        ...item,
        title:     document.getElementById('edit-title').value.trim(),
        summary:   document.getElementById('edit-summary').value.trim(),
        detail:    document.getElementById('edit-detail').value.trim(),
        sourceUrl: document.getElementById('edit-url').value.trim(),
        tags:      document.getElementById('edit-tags').value.split(',').map(t=>t.trim()).filter(Boolean),
      };
      saveNewsToLocal();
      renderWeekItems();
      panel.remove();
      showToast('수정 완료');
    });
    panel.querySelector('#edit-cancel-btn').addEventListener('click', () => panel.remove());
  }, 300);
}

// ── 주간 메타 ──
function renderWeekMeta() {
  const theme = document.getElementById('meta-theme');
  const week  = document.getElementById('meta-week');
  if (theme) theme.value = newsData.theme || '';
  if (week)  week.value  = newsData.weekLabel || '';
}

// ── localStorage 저장 ──
function saveNewsToLocal() {
  localStorage.setItem('flaneur_news_draft', JSON.stringify(newsData));
}

// ── 발행 바 ──
function updatePublishBar() {
  const bar = document.getElementById('publish-info');
  if (bar) {
    const count   = newsData.items.length;
    const ghReady = !!(localStorage.getItem('flaneur_gh_token') && localStorage.getItem('flaneur_gh_repo'));
    const modeTag = ghReady
      ? `<span style="color:var(--accent);font-size:12px;margin-left:8px">● GitHub 직접 발행</span>`
      : `<span style="color:var(--gold);font-size:12px;margin-left:8px">● 다운로드 모드</span>`;
    bar.innerHTML = `이번 주 소식 <strong>${count}개</strong> 준비됨 ${count < 20 ? `(${20-count}개 더 추가 권장)` : '✓'} ${modeTag}`;
  }
}

// ── 발행 ──
async function publishWeek() {
  const theme = document.getElementById('meta-theme')?.value.trim();
  const week  = document.getElementById('meta-week')?.value.trim();
  if (!theme || !week) { alert('주간 주제와 날짜 범위를 입력해 주세요.'); return; }
  if (newsData.items.length < 1) { alert('소식이 없습니다. 먼저 소식을 추가해 주세요.'); return; }

  const payload = {
    week:      getWeekNumber(),
    weekLabel: week,
    theme:     theme,
    items:     newsData.items,
  };
  const content = JSON.stringify(payload, null, 2);

  // GitHub 설정이 있으면 직접 발행, 없으면 다운로드
  const ghToken = localStorage.getItem('flaneur_gh_token');
  const ghOwner = localStorage.getItem('flaneur_gh_owner');
  const ghRepo  = localStorage.getItem('flaneur_gh_repo');

  if (ghToken && ghOwner && ghRepo) {
    await publishToGitHub('data/news.json', content, `주간 소식 업데이트 — ${week}`);
  } else {
    downloadJson(content, 'news.json');
    showToast('news.json 다운로드 완료! data/ 폴더에 교체하세요.');
  }
}

// ── GitHub API 직접 발행 ──
async function publishToGitHub(filePath, content, commitMsg) {
  const token = localStorage.getItem('flaneur_gh_token');
  const owner = localStorage.getItem('flaneur_gh_owner');
  const repo  = localStorage.getItem('flaneur_gh_repo');

  const btn = document.getElementById('publish-btn');
  const origText = btn?.textContent;
  if (btn) { btn.disabled = true; btn.textContent = '발행 중…'; }

  try {
    const apiBase = `https://api.github.com/repos/${owner}/${repo}/contents/${filePath}`;

    // 현재 파일 SHA 가져오기 (업데이트에 필요)
    let sha = '';
    const getRes = await fetch(apiBase, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept': 'application/vnd.github+json',
      }
    });
    if (getRes.ok) {
      const current = await getRes.json();
      sha = current.sha;
    }

    // 파일 업데이트 또는 생성
    const body = {
      message: commitMsg || `Update ${filePath}`,
      content: btoa(unescape(encodeURIComponent(content))),
    };
    if (sha) body.sha = sha;

    const putRes = await fetch(apiBase, {
      method:  'PUT',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept':        'application/vnd.github+json',
        'Content-Type':  'application/json',
      },
      body: JSON.stringify(body),
    });

    if (putRes.ok) {
      showToast('✓ GitHub에 발행되었습니다! 잠시 후 사이트에 반영됩니다.');
      localStorage.removeItem('flaneur_news_draft');
    } else {
      const err = await putRes.json();
      throw new Error(err.message || 'GitHub API 오류');
    }
  } catch (e) {
    console.error(e);
    showToast('GitHub 발행 실패: ' + e.message + ' — 다운로드로 대체합니다.');
    downloadJson(content, filePath.split('/').pop());
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = origText; }
  }
}

// ── JSON 다운로드 (폴백) ──
function downloadJson(content, filename) {
  const blob = new Blob([content], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = filename;
  a.click(); URL.revokeObjectURL(url);
}

// ── 피드 상태 대시보드 ──
async function loadFeedSummary() {
  const panel = document.getElementById('feed-summary-panel');
  if (!panel) return;

  try {
    const res  = await fetch(`data/feeds/_summary.json?v=${Date.now()}`);
    if (!res.ok) {
      panel.innerHTML = `<p style="font-size:13px;color:var(--text-muted)">
        아직 수집된 데이터가 없습니다.<br>
        GitHub에 배포 후 Actions가 자동 실행되거나, 수동으로 실행해 주세요.
      </p>`;
      return;
    }

    const summary = await res.json();
    const lastRun = summary.lastRun ? new Date(summary.lastRun).toLocaleString('ko-KR') : '알 수 없음';

    // 각 소스 상태 카드
    const rows = sources.map(src => {
      const isOk = summary.ok?.includes(src.id);
      const dot  = isOk
        ? `<span style="color:var(--accent);font-weight:600">● 정상</span>`
        : `<span style="color:#dc2626;font-weight:600">● 실패</span>`;
      return `<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;
                background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);font-size:13px">
        <span style="font-size:16px">${src.flag}</span>
        <span style="font-weight:500;min-width:140px">${src.name}</span>
        ${dot}
      </div>`;
    }).join('');

    panel.innerHTML = `
      <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px">
        마지막 수집: <strong style="color:var(--text)">${lastRun}</strong>
        &nbsp;·&nbsp; 성공 <strong style="color:var(--accent)">${summary.fetched}</strong> /
        전체 <strong>${summary.total}</strong>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:6px">
        ${rows}
      </div>
    `;
  } catch {
    panel.innerHTML = `<p style="font-size:13px;color:var(--text-muted)">피드 상태를 불러올 수 없습니다.</p>`;
  }
}

// ── PIN 변경 ──
function changeOwnerPin() {
  const statusEl = document.getElementById('pin-change-status');
  const current  = document.getElementById('pin-current')?.value;
  const next     = document.getElementById('pin-new')?.value.trim();
  const confirm  = document.getElementById('pin-confirm')?.value.trim();
  const stored   = localStorage.getItem('flaneur_owner_pin') || '0000';

  const err = (msg) => { statusEl.textContent = msg; statusEl.style.color = '#dc2626'; };
  const ok  = (msg) => { statusEl.textContent = msg; statusEl.style.color = 'var(--accent)'; };

  if (current !== stored) return err('현재 PIN이 맞지 않습니다.');
  if (!next)              return err('새 PIN을 입력하세요.');
  if (next !== confirm)   return err('새 PIN이 일치하지 않습니다.');
  if (next.length < 4)    return err('PIN은 4자리 이상이어야 합니다.');

  localStorage.setItem('flaneur_owner_pin', next);
  document.getElementById('pin-current').value = '';
  document.getElementById('pin-new').value = '';
  document.getElementById('pin-confirm').value = '';
  ok('PIN이 변경되었습니다.');
  setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000);
}

// ── GitHub 설정 저장 ──
function saveGitHubSettings() {
  const token = document.getElementById('gh-token')?.value.trim();
  const owner = document.getElementById('gh-owner')?.value.trim();
  const repo  = document.getElementById('gh-repo')?.value.trim();

  if (token) localStorage.setItem('flaneur_gh_token', token);
  else       localStorage.removeItem('flaneur_gh_token');
  if (owner) localStorage.setItem('flaneur_gh_owner', owner);
  if (repo)  localStorage.setItem('flaneur_gh_repo',  repo);

  updatePublishBar();
  showToast(token ? 'GitHub 설정 저장됨 — 이제 직접 발행됩니다.' : 'GitHub 설정 삭제됨');
}

// ── GitHub 연결 테스트 ──
async function testGitHubConnection() {
  const token = localStorage.getItem('flaneur_gh_token');
  const owner = localStorage.getItem('flaneur_gh_owner');
  const repo  = localStorage.getItem('flaneur_gh_repo');

  if (!token || !owner || !repo) {
    showToast('먼저 설정을 저장해 주세요.');
    return;
  }

  const btn = document.getElementById('gh-test-btn');
  if (btn) { btn.disabled = true; btn.textContent = '테스트 중…'; }

  try {
    const res = await fetch(`https://api.github.com/repos/${owner}/${repo}`, {
      headers: { 'Authorization': `Bearer ${token}`, 'Accept': 'application/vnd.github+json' }
    });
    if (res.ok) {
      const d = await res.json();
      showToast(`✓ 연결 성공! 저장소: ${d.full_name}`);
      document.getElementById('gh-status').textContent = `✓ ${d.full_name} 연결됨`;
      document.getElementById('gh-status').style.color = 'var(--accent)';
    } else {
      throw new Error(`${res.status} ${res.statusText}`);
    }
  } catch (e) {
    showToast('연결 실패: ' + e.message);
    document.getElementById('gh-status').textContent = '✗ 연결 실패';
    document.getElementById('gh-status').style.color = '#dc2626';
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '연결 테스트'; }
  }
}

function getWeekNumber() {
  const now  = new Date();
  const jan1 = new Date(now.getFullYear(), 0, 1);
  const week = Math.ceil(((now - jan1) / 86400000 + jan1.getDay() + 1) / 7);
  return `${now.getFullYear()}-W${String(week).padStart(2, '0')}`;
}

// ── 초기화 ──
function resetWeek() {
  if (!confirm('이번 주 소식을 모두 초기화하시겠습니까?\n저장하지 않은 내용은 사라집니다.')) return;
  newsData.items = [];
  saveNewsToLocal();
  renderWeekItems();
  updatePublishBar();
  showToast('초기화되었습니다.');
}

// ── 탭 전환 ──
function switchTab(tab) {
  document.querySelectorAll('.admin-tab').forEach(el => {
    el.classList.toggle('active', el.dataset.tab === tab);
  });
  document.querySelectorAll('[data-panel]').forEach(el => {
    el.style.display = el.dataset.panel === tab ? '' : 'none';
  });
}

// ── YouTube API 키 설정 ──
function saveApiKey() {
  const key = document.getElementById('yt-api-key').value.trim();
  ytApiKey  = key;
  localStorage.setItem('flaneur_yt_api', key);
  showToast(key ? 'API 키 저장됨' : 'API 키 삭제됨');
}

// ── 이벤트 바인딩 ──
function bindEvents() {
  document.querySelectorAll('.admin-tab').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  document.getElementById('publish-btn')?.addEventListener('click', publishWeek);
  document.getElementById('reset-btn')?.addEventListener('click', resetWeek);
  document.getElementById('save-api-btn')?.addEventListener('click', saveApiKey);
  document.getElementById('save-gh-btn')?.addEventListener('click', saveGitHubSettings);
  document.getElementById('gh-test-btn')?.addEventListener('click', testGitHubConnection);
  document.getElementById('refresh-feeds-btn')?.addEventListener('click', loadFeedSummary);
  document.getElementById('save-pin-btn')?.addEventListener('click', changeOwnerPin);

  document.getElementById('meta-theme')?.addEventListener('input', e => {
    newsData.theme = e.target.value;
    saveNewsToLocal();
  });
  document.getElementById('meta-week')?.addEventListener('input', e => {
    newsData.weekLabel = e.target.value;
    saveNewsToLocal();
  });

  // 저장된 초안 불러오기
  const draft = localStorage.getItem('flaneur_news_draft');
  if (draft) {
    try {
      const parsed = JSON.parse(draft);
      if (parsed.items?.length && confirm(`저장된 초안이 있습니다 (${parsed.items.length}개 소식). 불러오시겠습니까?`)) {
        newsData = parsed;
        renderWeekItems();
        renderWeekMeta();
        updatePublishBar();
      }
    } catch {}
  }

  // YouTube API 키 복원
  if (ytApiKey) {
    const keyInput = document.getElementById('yt-api-key');
    if (keyInput) keyInput.value = ytApiKey;
  }

  // GitHub 설정 복원
  const ghToken = localStorage.getItem('flaneur_gh_token');
  const ghOwner = localStorage.getItem('flaneur_gh_owner');
  const ghRepo  = localStorage.getItem('flaneur_gh_repo');
  if (ghToken && document.getElementById('gh-token')) {
    document.getElementById('gh-token').value = '••••••••••••••••';
  }
  if (ghOwner && document.getElementById('gh-owner')) document.getElementById('gh-owner').value = ghOwner;
  if (ghRepo  && document.getElementById('gh-repo'))  document.getElementById('gh-repo').value  = ghRepo;
  if (ghToken && ghOwner && ghRepo) {
    const statusEl = document.getElementById('gh-status');
    if (statusEl) { statusEl.textContent = `${ghOwner}/${ghRepo} 설정됨`; statusEl.style.color = 'var(--accent)'; }
    // Actions 링크 업데이트
    const actionsLink = document.getElementById('gh-actions-link');
    if (actionsLink) actionsLink.href = `https://github.com/${ghOwner}/${ghRepo}/actions`;
  }

  // 설정 탭이 열릴 때 피드 상태 로드
  document.querySelectorAll('.admin-tab').forEach(tab => {
    if (tab.dataset.tab === 'settings') {
      tab.addEventListener('click', loadFeedSummary);
    }
  });
}

// ── 유틸 ──
function escapeAttr(str) {
  return (str || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function showToast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2400);
}

document.addEventListener('DOMContentLoaded', init);
