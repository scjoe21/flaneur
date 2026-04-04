/* =========================================
   플라뇌르 — 에세이 페이지 스크립트
   ========================================= */

async function loadEssay() {
  const params = new URLSearchParams(location.search);
  const id     = params.get('id');

  try {
    const res  = await fetch('data/essays.json?v=' + Date.now());
    const data = await res.json();
    const essay = id
      ? data.essays.find(e => e.id === id)
      : data.essays[data.essays.length - 1];

    if (!essay) {
      showError();
      return;
    }

    document.title = `${essay.title} — 플라뇌르`;

    document.getElementById('essay-label').textContent    = `✍ ${essay.weekLabel}의 에세이`;
    document.getElementById('essay-title').textContent    = essay.title;
    document.getElementById('essay-subtitle').textContent = essay.subtitle || '';
    document.getElementById('essay-meta').textContent     = `${essay.date} · 읽는 시간 약 ${essay.readTime || 5}분`;
    document.getElementById('essay-body').textContent     = essay.body;

    const tagsEl = document.getElementById('essay-tags');
    if (essay.tags?.length) {
      tagsEl.innerHTML = essay.tags.map(t => `<span class="tag">#${t}</span>`).join('');
    }

    // 에세이 목록 렌더링
    renderEssayList(data.essays, essay.id);
  } catch (e) {
    console.error('에세이 로드 실패:', e);
    showError();
  }
}

function renderEssayList(essays, currentId) {
  const container = document.getElementById('essay-list');
  if (!container) return;

  const others = essays.filter(e => e.id !== currentId).reverse();
  if (!others.length) {
    container.innerHTML = '<p style="color:var(--text-muted);font-size:14px;">다른 에세이가 없습니다.</p>';
    return;
  }

  container.innerHTML = others.map(e => `
    <a href="essay.html?id=${e.id}" class="essay-list-item">
      <div class="essay-list-item__label">${e.weekLabel}</div>
      <div class="essay-list-item__title">${e.title}</div>
    </a>
  `).join('');
}

function showError() {
  document.getElementById('essay-title').textContent = '에세이를 찾을 수 없습니다.';
}

document.addEventListener('DOMContentLoaded', () => {
  loadEssay();

  document.getElementById('back-btn')?.addEventListener('click', () => {
    window.location.href = 'index.html';
  });
});
