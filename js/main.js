/* =========================================
   플라뇌르 — 메인 스크립트
   공개 화면(에세이) / 운영자 화면(뉴스피드) 분리
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
// 운영자 모드 관리
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const OWNER_SESSION_KEY = 'flaneur_owner';
const DEFAULT_PIN       = '1215';

function isOwner() {
  return sessionStorage.getItem(OWNER_SESSION_KEY) === 'true';
}

function enterOwnerMode() {
  sessionStorage.setItem(OWNER_SESSION_KEY, 'true');
  applyView();
}

function exitOwnerMode() {
  sessionStorage.removeItem(OWNER_SESSION_KEY);
  applyView();
}

// 화면 전환
function applyView() {
  const owner = isOwner();

  document.getElementById('public-view').style.display  = owner ? 'none' : '';
  document.getElementById('owner-view').style.display   = owner ? ''     : 'none';
  document.getElementById('nav-public').style.display   = owner ? 'none' : '';
  document.getElementById('nav-owner').style.display    = owner ? ''     : 'none';

  if (owner) {
    initOwnerView();
  } else {
    initPublicView();
  }
}

// ── PIN 관련 ──
let logoClickCount = 0;
let logoClickTimer = null;

function handleLogoClick() {
  logoClickCount++;
  clearTimeout(logoClickTimer);
  logoClickTimer = setTimeout(() => { logoClickCount = 0; }, 900);

  if (logoClickCount >= 3) {
    logoClickCount = 0;
    if (isOwner()) {
      if (confirm('운영자 모드를 종료하시겠습니까?')) exitOwnerMode();
    } else {
      openPinModal();
    }
  }
}

function openPinModal() {
  document.getElementById('pin-overlay').classList.add('open');
  document.getElementById('pin-input').value = '';
  document.getElementById('pin-error').textContent = '';
  setTimeout(() => document.getElementById('pin-input').focus(), 150);
}

function closePinModal() {
  document.getElementById('pin-overlay').classList.remove('open');
}

function submitPin() {
  const input      = document.getElementById('pin-input').value.trim();
  const storedPin  = DEFAULT_PIN;
  const errorEl    = document.getElementById('pin-error');

  if (!input) { errorEl.textContent = 'PIN을 입력해 주세요.'; return; }

  if (input === storedPin) {
    closePinModal();
    enterOwnerMode();
  } else {
    errorEl.textContent = '틀렸습니다. 다시 입력해 주세요.';
    document.getElementById('pin-input').value = '';
    document.getElementById('pin-input').focus();
  }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 공개 화면 — 에세이
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function initPublicView() {
  try {
    const res  = await fetch('data/essays.json?v=' + Date.now());
    const data = await res.json();
    const essays = data.essays || [];

    renderLatestEssay(essays);
    renderEssayArchive(essays);
  } catch (e) {
    console.warn('에세이 로드 실패:', e);
  }
}

function renderLatestEssay(essays) {
  const card = document.getElementById('latest-essay-card');
  if (!card) return;

  const latest = essays[essays.length - 1];
  if (!latest) {
    card.innerHTML = '<p style="color:var(--text-muted);font-size:14px">아직 에세이가 없습니다.</p>';
    return;
  }

  const firstPara = (latest.body || '').split('\n').find(l => l.trim()) || '';

  card.innerHTML = `
    <div class="latest-essay__label">${latest.weekLabel || ''}</div>
    <h2 class="latest-essay__title">${latest.title}</h2>
    ${latest.subtitle ? `<p class="latest-essay__subtitle">${latest.subtitle}</p>` : ''}
    <p class="latest-essay__excerpt">${firstPara}</p>
    <div class="latest-essay__footer">
      <span class="latest-essay__meta">${latest.date || ''} · 약 ${latest.readTime || 5}분</span>
      <a href="essay.html?id=${latest.id}" class="btn btn--primary latest-essay__btn">읽기 →</a>
    </div>
  `;
}

function renderEssayArchive(essays) {
  const container = document.getElementById('essay-archive-list');
  if (!container) return;

  const sorted = [...essays].reverse();

  if (!sorted.length) {
    container.innerHTML = '<p style="color:var(--text-muted);font-size:14px">아직 에세이가 없습니다.</p>';
    return;
  }

  container.innerHTML = sorted.map((e, i) => `
    <a href="essay.html?id=${e.id}" class="archive-item ${i === 0 ? 'archive-item--latest' : ''}">
      <div class="archive-item__date">${e.date || ''}</div>
      <div class="archive-item__title">${e.title}</div>
      ${e.subtitle ? `<div class="archive-item__subtitle">${e.subtitle}</div>` : ''}
      <span class="archive-item__arrow">→</span>
    </a>
  `).join('');
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 운영자 화면 — 뉴스 피드
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function initOwnerView() {
  if (!newsData) await loadNews();
  renderHero();
  renderDayTabs();
  renderNewsGrid('all');
  renderEssayPreview();
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

  items.forEach((item, idx) => {
    const card = buildCard(item);
    card.style.animationDelay = `${idx * 40}ms`;
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
      <button class="saved-item__remove" data-id="${clip.clipId}">✕</button>
    `;
    el.querySelector('.saved-item__remove').addEventListener('click', e => {
      e.stopPropagation();
      clipList = clipList.filter(c => c.clipId !== clip.clipId);
      localStorage.setItem('flaneur_clips', JSON.stringify(clipList));
      el.remove();
      updateClipBadge();
    });
    body.appendChild(el);
  });
}

// ── 에세이 미리보기 ──
async function renderEssayPreview() {
  try {
    const res  = await fetch('data/essays.json?v=' + Date.now());
    const data = await res.json();
    const latest = data.essays?.[data.essays.length - 1];
    if (!latest) return;

    const card = document.getElementById('essay-card');
    if (!card) return;

    card.querySelector('.essay-card__label').textContent    = `✍ ${latest.weekLabel}의 에세이`;
    card.querySelector('.essay-card__title').textContent    = latest.title;
    card.querySelector('.essay-card__subtitle').textContent = latest.subtitle || '';
    card.querySelector('.essay-card__excerpt').textContent  = latest.body?.split('\n')[0] || '';
    card.querySelector('.essay-card__meta').textContent     = `읽는 시간 약 ${latest.readTime || 5}분`;
    card.addEventListener('click', () => window.location.href = `essay.html?id=${latest.id}`);
  } catch {}
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

  // 로고 3번 클릭
  document.getElementById('logo-btn')?.addEventListener('click', handleLogoClick);

  // PIN 모달
  document.getElementById('pin-submit')?.addEventListener('click', submitPin);
  document.getElementById('pin-close')?.addEventListener('click', closePinModal);
  document.getElementById('pin-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') submitPin();
    if (e.key === 'Escape') closePinModal();
  });
  document.getElementById('pin-overlay')?.addEventListener('click', e => {
    if (e.target.id === 'pin-overlay') closePinModal();
  });

  // 운영자 모드 나가기
  document.getElementById('exit-owner-btn')?.addEventListener('click', () => {
    if (confirm('운영자 모드를 종료하시겠습니까?')) exitOwnerMode();
  });

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

  // 초기 화면 결정
  applyView();
});
