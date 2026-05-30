/* =========================================
   플라뇌르 — 메인 스크립트
   초기 화면 = 주간 뉴스 피드
   ========================================= */

const DAY_CONFIG = {
  monday:    { label: '월요일', flag: '🇫🇷', country: 'france',  countryLabel: '프랑스' },
  tuesday:   { label: '화요일', flag: '🇩🇪', country: 'germany', countryLabel: '독일'   },
  wednesday: { label: '수요일', flag: '🇮🇹', country: 'italy',   countryLabel: '이탈리아' },
  thursday:  { label: '목요일', flag: '🇬🇧', country: 'uk',      countryLabel: '영국'   },
  friday:    { label: '금요일', flag: '🇺🇸', country: 'usa',     countryLabel: '미국'   },
};
const DAY_ORDER = ['monday','tuesday','wednesday','thursday','friday'];

// ── 상태 ──
let newsData  = null;
let clipList  = JSON.parse(localStorage.getItem('flaneur_clips') || '[]');
let activeDay = 'all';
let openItem  = null;

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 주간 뉴스 피드
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function initFeed() {
  if (!newsData) await loadNews();
  renderHero();
  renderDayTabs();
  renderNewsGrid('all');
  updateClipBadge();
}

async function loadNews() {
  try {
    const res = await fetch('data/news.json?v=' + Date.now());
    newsData  = await res.json();
  } catch {
    newsData = { week: '', weekLabel: '', theme: '데이터를 불러올 수 없습니다.', items: [] };
  }
}

function renderHero() {
  document.getElementById('hero-week').textContent  = newsData.weekLabel || '';
  document.getElementById('hero-theme').textContent = newsData.theme     || '';
  document.getElementById('hero-count').innerHTML   =
    `이번 주 <strong>${newsData.items.length}</strong>개의 소식`;
}

function renderDayTabs() {
  const container = document.getElementById('day-tabs');
  container.innerHTML = '';

  const allBtn = createTab('all', '🌐', '전체', activeDay === 'all');
  container.appendChild(allBtn);

  DAY_ORDER.forEach(day => {
    const items = newsData.items.filter(i => i.day === day);
    if (!items.length) return;
    const cfg = DAY_CONFIG[day];
    container.appendChild(createTab(day, cfg.flag, cfg.label, activeDay === day));
  });
}

function createTab(day, flag, label, isActive) {
  const btn = document.createElement('button');
  btn.className = 'day-tab' + (isActive ? ' active' : '');
  btn.innerHTML = `<span class="day-tab__flag">${flag}</span>${label}`;
  btn.addEventListener('click', () => {
    activeDay = day;
    renderDayTabs();
    renderNewsGrid(day);
  });
  return btn;
}

function renderNewsGrid(day) {
  const grid  = document.getElementById('news-grid');
  const items = day === 'all'
    ? newsData.items
    : newsData.items.filter(i => i.day === day);

  grid.innerHTML = '';

  if (!items.length) {
    grid.innerHTML = `<div class="empty-state">
      <div class="empty-state__icon">📭</div>
      <div class="empty-state__text">이번 요일 소식이 없습니다.</div>
    </div>`;
    return;
  }

  items.forEach(item => {
    const card = buildCard(item);
    card.classList.add('animate-in');
    grid.appendChild(card);
  });
}

function buildCard(item) {
  const cfg  = DAY_CONFIG[item.day] || {};
  const card = document.createElement('article');
  card.className = 'news-card';
  card.dataset.id = item.id;

  card.innerHTML = `
    <div class="card-header">
      <div class="card-source">
        <span class="card-source__flag">${cfg.flag || ''}</span>
        <span>${item.source}</span>
        <span class="card-source__dot"></span>
        <span class="card-country card-country--${item.country}">${item.countryLabel}</span>
      </div>
    </div>
    <h3 class="card-title">${item.title}</h3>
    <p class="card-summary">${item.summary}</p>
    <div class="card-tags">
      ${(item.tags || []).slice(0, 3).map(t => `<span class="tag">#${t}</span>`).join('')}
    </div>
    <div class="card-footer">
      <span class="read-more">자세히 보기
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 8h10M9 4l4 4-4 4"/>
        </svg>
      </span>
    </div>
  `;

  card.addEventListener('click', () => openModal(item));
  return card;
}

// ── 모달 ──
function openModal(item) {
  openItem = item;
  const overlay = document.getElementById('modal-overlay');
  const cfg     = DAY_CONFIG[item.day] || {};

  overlay.querySelector('.modal-day').textContent   = `${cfg.flag || ''} ${item.dayLabel} · ${item.countryLabel}`;
  overlay.querySelector('.modal-source').innerHTML  = `<strong>${item.source}</strong>`;
  overlay.querySelector('.modal-title').textContent = item.title;

  const body = overlay.querySelector('.modal-body');
  body.textContent = item.detail;
  body.onmouseup = null;
  body.ontouchend = () => setTimeout(() => showClipTooltip(item), 100);

  overlay.querySelector('#modal-source-btn').onclick =
    () => window.open(item.sourceUrl, '_blank', 'noopener');

  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
  document.body.style.overflow = '';
  document.getElementById('clip-tooltip').style.display = 'none';
  openItem = null;
}

// ── 구절 저장 ──
function showClipTooltip(item) {
  const sel     = window.getSelection();
  const tooltip = document.getElementById('clip-tooltip');
  if (!sel || sel.toString().trim().length < 5) {
    tooltip.style.display = 'none';
    return;
  }
  const range = sel.getRangeAt(0).getBoundingClientRect();
  tooltip.style.display = 'block';
  tooltip.style.top  = (range.top - 44) + 'px';
  tooltip.style.left = (range.left + range.width / 2) + 'px';
  document.getElementById('clip-save-btn').onclick = () => saveClip(sel.toString().trim(), item);
}

function getWeekKey(d = new Date()) {
  const date = new Date(d);
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() + 3 - (date.getDay() + 6) % 7);
  const w1 = new Date(date.getFullYear(), 0, 4);
  const weekNum = 1 + Math.round(((date - w1) / 86400000 - 3 + (w1.getDay() + 6) % 7) / 7);
  return `${date.getFullYear()}-W${String(weekNum).padStart(2, '0')}`;
}

function getMonthKey(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function saveClip(text, item) {
  const cfg = DAY_CONFIG[item.day] || {};
  const now = new Date();
  clipList.push({
    clipId:        'clip_' + Date.now() + '_' + Math.random().toString(36).slice(2, 5),
    articleId:     item.id,
    articleTitle:  item.title,
    source:        item.source,
    dayLabel:      item.dayLabel,
    flag:          cfg.flag || '',
    text,
    savedAt:       now.toISOString(),
    weekKey:       getWeekKey(now),
    monthKey:      getMonthKey(now)
  });
  localStorage.setItem('flaneur_clips', JSON.stringify(clipList));
  document.getElementById('clip-tooltip').style.display = 'none';
  updateClipBadge();
  showToast('구절을 저장했습니다.');
}

function updateClipBadge() {
  const badge = document.getElementById('saved-badge');
  if (!badge) return;
  badge.querySelector('.count').textContent = clipList.length;
  badge.style.display = clipList.length > 0 ? 'flex' : 'none';
}

// ── 저장함 패널 ──
function bindSavedPanel() {
  const panel  = document.getElementById('saved-panel');
  const badge  = document.getElementById('saved-badge');
  const navBtn = document.getElementById('nav-saved');
  const close  = document.getElementById('saved-panel-close');

  const open  = () => { refreshSavedPanel(); panel.classList.add('open'); document.body.style.overflow = 'hidden'; };
  const close_ = () => { panel.classList.remove('open'); document.body.style.overflow = ''; };

  badge?.addEventListener('click', open);
  navBtn?.addEventListener('click', open);
  close?.addEventListener('click', close_);
}

function refreshSavedPanel() {
  const body = document.getElementById('saved-panel-body');

  if (!clipList.length) {
    body.innerHTML = '<div class="saved-empty">텍스트를 드래그해 구절을 저장해 보세요.</div>';
    return;
  }

  body.innerHTML = '';
  [...clipList].reverse().forEach(clip => {
    const el = document.createElement('div');
    el.className = 'saved-item';
    el.innerHTML = `
      <div class="saved-item__source">${clip.flag} ${clip.source} · ${clip.dayLabel}</div>
      <blockquote class="saved-item__clip">${clip.text}</blockquote>
      <div class="saved-item__title">${clip.articleTitle}</div>
      <div class="saved-item__btns">
        <button class="saved-item__edit" title="편집">✎</button>
        <button class="saved-item__remove" title="삭제">✕</button>
      </div>
    `;

    el.querySelector('.saved-item__remove').addEventListener('click', e => {
      e.stopPropagation();
      clipList = clipList.filter(c => c.clipId !== clip.clipId);
      localStorage.setItem('flaneur_clips', JSON.stringify(clipList));
      el.remove();
      updateClipBadge();
    });

    el.querySelector('.saved-item__edit').addEventListener('click', e => {
      e.stopPropagation();
      if (!el.classList.contains('editing')) enterSavedItemEdit(clip, el);
    });

    el.addEventListener('click', e => {
      if (e.target.closest('.saved-item__btns')) return;
      if (e.target.closest('.saved-item__edit-actions')) return;
      if (el.classList.contains('editing')) return;
      enterSavedItemEdit(clip, el);
    });

    body.appendChild(el);
  });
}

function enterSavedItemEdit(clip, el) {
  el.classList.add('editing');

  const blockquote = el.querySelector('.saved-item__clip');
  const titleEl    = el.querySelector('.saved-item__title');
  const btnsEl     = el.querySelector('.saved-item__btns');

  const textarea = document.createElement('textarea');
  textarea.className = 'saved-item__textarea';
  textarea.value = clip.text;
  blockquote.replaceWith(textarea);
  textarea.focus();

  titleEl.style.display = 'none';
  btnsEl.style.display  = 'none';

  const actions = document.createElement('div');
  actions.className = 'saved-item__edit-actions';
  actions.innerHTML = `
    <button class="saved-item__cancel">취소</button>
    <button class="saved-item__save">저장</button>
  `;
  el.appendChild(actions);

  actions.querySelector('.saved-item__save').addEventListener('click', e => {
    e.stopPropagation();
    const newText = textarea.value.trim();
    if (!newText) return;
    const idx = clipList.findIndex(c => c.clipId === clip.clipId);
    if (idx >= 0) {
      clipList[idx] = { ...clipList[idx], text: newText };
      clip.text = newText;
      localStorage.setItem('flaneur_clips', JSON.stringify(clipList));
    }
    exitSavedItemEdit(clip, el);
    showToast('수정했습니다.');
  });

  actions.querySelector('.saved-item__cancel').addEventListener('click', e => {
    e.stopPropagation();
    exitSavedItemEdit(clip, el);
  });

  textarea.addEventListener('keydown', e => {
    if (e.key === 'Escape') exitSavedItemEdit(clip, el);
  });
}

function exitSavedItemEdit(clip, el) {
  el.classList.remove('editing');

  const textarea  = el.querySelector('.saved-item__textarea');
  const titleEl   = el.querySelector('.saved-item__title');
  const btnsEl    = el.querySelector('.saved-item__btns');
  const actionsEl = el.querySelector('.saved-item__edit-actions');

  const blockquote = document.createElement('blockquote');
  blockquote.className = 'saved-item__clip';
  blockquote.textContent = clip.text;
  textarea.replaceWith(blockquote);

  titleEl.style.display = '';
  btnsEl.style.display  = '';
  actionsEl?.remove();
}

// ── 토스트 ──
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2200);
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 이벤트 바인딩 & 초기화
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

document.addEventListener('DOMContentLoaded', () => {

  // 모달
  document.getElementById('modal-overlay')?.addEventListener('click', e => {
    if (e.target.id === 'modal-overlay') closeModal();
  });
  document.getElementById('modal-close')?.addEventListener('click', closeModal);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

  // 모달 외부 클릭 시 구절 툴팁 닫기
  document.addEventListener('click', e => {
    if (!e.target.closest('#clip-tooltip') && !e.target.closest('.modal-body')) {
      const tooltip = document.getElementById('clip-tooltip');
      if (tooltip) tooltip.style.display = 'none';
    }
  });

  // 저장함
  bindSavedPanel();
  updateClipBadge();

  // 주간 피드 렌더
  initFeed();
});
