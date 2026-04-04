/* =========================================
   플라뇌르 — 에세이 작성 스크립트
   ========================================= */

async function loadEssays() {
  try {
    const res  = await fetch('data/essays.json?v=' + Date.now());
    return await res.json();
  } catch {
    return { essays: [] };
  }
}

async function saveEssay(essayData) {
  // 로컬 스토리지 기반 임시 저장 (실제 배포 시 서버 API 연동)
  const drafts = JSON.parse(localStorage.getItem('flaneur_drafts') || '[]');
  const existing = drafts.findIndex(d => d.id === essayData.id);
  if (existing >= 0) {
    drafts[existing] = essayData;
  } else {
    drafts.push(essayData);
  }
  localStorage.setItem('flaneur_drafts', JSON.stringify(drafts));
  return essayData;
}

function generateId() {
  return 'essay-' + Date.now();
}

function getCurrentWeekLabel() {
  const now   = new Date();
  const year  = now.getFullYear();
  const month = now.getMonth() + 1;
  const week  = Math.ceil(now.getDate() / 7);
  return `${year}년 ${month}월 ${week}주`;
}

function formatDate(date) {
  return date.toISOString().split('T')[0];
}

function showToast(msg, type = 'info') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2400);
}

document.addEventListener('DOMContentLoaded', async () => {
  // 임시저장 불러오기
  const draftId = new URLSearchParams(location.search).get('draft');
  if (draftId) {
    const drafts = JSON.parse(localStorage.getItem('flaneur_drafts') || '[]');
    const draft  = drafts.find(d => d.id === draftId);
    if (draft) {
      document.getElementById('essay-title-input').value    = draft.title || '';
      document.getElementById('essay-subtitle-input').value = draft.subtitle || '';
      document.getElementById('essay-body-input').value     = draft.body || '';
      document.getElementById('essay-tags-input').value     = (draft.tags || []).join(', ');
      document.getElementById('draft-id').value             = draft.id;
      document.getElementById('page-title').textContent     = '에세이 수정';
    }
  }

  // 임시저장 목록 렌더링
  renderDraftList();

  // 글자수 카운터
  const bodyInput = document.getElementById('essay-body-input');
  const counter   = document.getElementById('char-counter');
  bodyInput.addEventListener('input', () => {
    const lines = bodyInput.value.split('\n').length;
    counter.textContent = `${lines}줄 / ${bodyInput.value.length}자`;
  });

  // 저장 버튼
  document.getElementById('save-btn').addEventListener('click', async () => {
    const title    = document.getElementById('essay-title-input').value.trim();
    const subtitle = document.getElementById('essay-subtitle-input').value.trim();
    const body     = document.getElementById('essay-body-input').value.trim();
    const tagsRaw  = document.getElementById('essay-tags-input').value;
    const tags     = tagsRaw.split(',').map(t => t.trim()).filter(Boolean);

    if (!title || !body) {
      showToast('제목과 본문을 입력해 주세요.');
      return;
    }

    const existingId = document.getElementById('draft-id').value;
    const id = existingId || generateId();

    const essayData = {
      id,
      date:      formatDate(new Date()),
      weekLabel: getCurrentWeekLabel(),
      title,
      subtitle,
      body,
      tags,
      readTime:  Math.ceil(body.length / 500),
    };

    await saveEssay(essayData);
    document.getElementById('draft-id').value = id;

    showToast('임시 저장되었습니다.');
    renderDraftList();
  });

  // 발행 버튼
  document.getElementById('publish-btn').addEventListener('click', async () => {
    const title = document.getElementById('essay-title-input').value.trim();
    const body  = document.getElementById('essay-body-input').value.trim();

    if (!title || !body) {
      showToast('제목과 본문을 입력해 주세요.');
      return;
    }

    if (!confirm('에세이를 발행하시겠습니까?\n발행 후에는 메인 페이지에 표시됩니다.')) return;

    const subtitle = document.getElementById('essay-subtitle-input').value.trim();
    const tagsRaw  = document.getElementById('essay-tags-input').value;
    const tags     = tagsRaw.split(',').map(t => t.trim()).filter(Boolean);
    const existingId = document.getElementById('draft-id').value;
    const id = existingId || generateId();

    const essayData = {
      id,
      date:      formatDate(new Date()),
      weekLabel: getCurrentWeekLabel(),
      title,
      subtitle,
      body,
      tags,
      readTime:  Math.ceil(body.length / 500),
    };

    // essays.json에 발행 (로컬에서는 localStorage에 저장)
    const published = JSON.parse(localStorage.getItem('flaneur_published_essays') || '[]');
    const existingIdx = published.findIndex(e => e.id === id);
    if (existingIdx >= 0) {
      published[existingIdx] = essayData;
    } else {
      published.push(essayData);
    }
    localStorage.setItem('flaneur_published_essays', JSON.stringify(published));

    showToast('발행되었습니다! 메인 페이지에서 확인하세요.');
    setTimeout(() => { window.location.href = `essay.html?id=${id}`; }, 1500);
  });

  // 초기화 버튼
  document.getElementById('clear-btn').addEventListener('click', () => {
    if (!confirm('내용을 모두 지우시겠습니까?')) return;
    document.getElementById('essay-title-input').value    = '';
    document.getElementById('essay-subtitle-input').value = '';
    document.getElementById('essay-body-input').value     = '';
    document.getElementById('essay-tags-input').value     = '';
    document.getElementById('draft-id').value             = '';
    counter.textContent = '0줄 / 0자';
  });
});

function renderDraftList() {
  const container = document.getElementById('draft-list');
  if (!container) return;

  const drafts = JSON.parse(localStorage.getItem('flaneur_drafts') || '[]').reverse();

  if (!drafts.length) {
    container.innerHTML = '<p style="color:var(--text-muted);font-size:13px;">저장된 초안이 없습니다.</p>';
    return;
  }

  container.innerHTML = drafts.map(d => `
    <div class="draft-item">
      <div class="draft-item__date">${d.date}</div>
      <div class="draft-item__title">${d.title || '(제목 없음)'}</div>
      <div class="draft-item__actions">
        <a href="write.html?draft=${d.id}" class="draft-item__btn">수정</a>
        <a href="essay.html?draft=${d.id}" class="draft-item__btn">미리보기</a>
        <button class="draft-item__btn draft-item__btn--delete" data-id="${d.id}">삭제</button>
      </div>
    </div>
  `).join('');

  container.querySelectorAll('.draft-item__btn--delete').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.id;
      const drafts = JSON.parse(localStorage.getItem('flaneur_drafts') || '[]');
      localStorage.setItem('flaneur_drafts', JSON.stringify(drafts.filter(d => d.id !== id)));
      renderDraftList();
    });
  });
}
