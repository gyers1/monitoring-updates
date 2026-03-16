(function () {
  if (window.__selectorHelperInjected) return;
  window.__selectorHelperInjected = true;

  const PANEL_WIDTH = 360;
  const state = {
    mode: 'title',
    titleSelector: '',
    dateSelector: '',
    titleSamples: [],
    dateSamples: [],
    titleCount: 0,
    dateCount: 0,
    titleClicks: [],
    dateClicks: [],
  };
  const HELPER_TEMPLATE_HINTS = {
    gwanbo_daily: {
      name: '대한민국 관보',
      urlMatch: /gwanbo\.go\.kr\/user\/search\/searchDaily\.do/i,
      titleSelector: 'div#daily_contents_list ul.list li span a',
      dateSelector: 'input#datapicker_searchdate',
      dateFormat: '%Y-%m-%d',
    },
    assembly_agenda: {
      name: '국회 일정',
      urlMatch: /assembly\.go\.kr\/portal\/na\/agenda\/agendaSchl\.do/i,
      titleSelector: 'div#schl__list dl dd a span.title',
      dateSelector: 'div#schl__list dl dd span.meetingTime',
      dateFormat: '%Y-%m-%d',
    },
  };

  function detectTemplateByUrl(url) {
    const target = String(url || '').trim();
    if (!target) return '';
    for (const [key, value] of Object.entries(HELPER_TEMPLATE_HINTS)) {
      if (value.urlMatch && value.urlMatch.test(target)) {
        return key;
      }
    }
    return '';
  }

  function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '\\\\$&');
  }

  function buildSelector(el) {
    if (!el || el.nodeType !== 1) return '';
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body) {
      let part = node.tagName.toLowerCase();
      if (node.id) {
        part += `#${cssEscape(node.id)}`;
        parts.unshift(part);
        break;
      }
      const classes = Array.from(node.classList || []).filter(c => c && !c.startsWith('selector-helper'));
      if (classes.length) {
        part += `.${classes.map(cssEscape).join('.')}`;
      }
      parts.unshift(part);
      if (classes.length && parts.length >= 2) break;
      node = node.parentElement;
    }
    return simplifySelector(parts.join(' '));
  }

  function simplifySelector(selector) {
    if (!selector) return '';
    const parts = selector.split(' ');
    if (parts.length <= 1) return selector;
    for (let i = 0; i < parts.length; i++) {
      const candidate = parts.slice(i).join(' ');
      try {
        const count = document.querySelectorAll(candidate).length;
        if (count > 1) return candidate;
      } catch (e) {
        continue;
      }
    }
    return selector;
  }

  function getSamples(selector) {
    if (!selector) return { count: 0, samples: [] };
    let nodes = [];
    try {
      nodes = Array.from(document.querySelectorAll(selector));
    } catch (e) {
      return { count: 0, samples: [] };
    }
    const samples = nodes.slice(0, 6).map(n => {
      const text = (n.textContent || '').replace(/\\s+/g, ' ').trim();
      return text.slice(0, 120);
    }).filter(Boolean);
    return { count: nodes.length, samples };
  }

  function updatePanel() {
    const modeLabel = document.getElementById('selector-helper-mode');
    const stepEl = document.getElementById('selector-helper-step');
    const selectorEl = document.getElementById('selector-helper-selector');
    const countEl = document.getElementById('selector-helper-count');
    const samplesEl = document.getElementById('selector-helper-samples');
    const isTitle = state.mode === 'title';
    const clickCount = isTitle ? state.titleClicks.length : state.dateClicks.length;
    const selector = isTitle ? state.titleSelector : state.dateSelector;
    const count = isTitle ? state.titleCount : state.dateCount;
    const samples = isTitle ? state.titleSamples : state.dateSamples;

    if (modeLabel) modeLabel.textContent = isTitle ? '제목 선택 모드' : '날짜 선택 모드';
    if (stepEl) {
      const stepText = clickCount === 0 ? '1번째 항목 클릭' : clickCount === 1 ? '2번째 항목 클릭' : '선택 완료';
      stepEl.textContent = stepText;
    }
    if (selectorEl) selectorEl.textContent = selector || '-';
    if (countEl) countEl.textContent = `매칭 ${count || 0}개`;
    if (samplesEl) {
      samplesEl.innerHTML = samples.length
        ? samples.map(s => `<li>${escapeHtml(s)}</li>`).join('')
        : '<li>선택된 값이 표시됩니다.</li>';
    }
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function setMode(mode) {
    state.mode = mode === 'date' ? 'date' : 'title';
    state.titleClicks = state.titleClicks || [];
    state.dateClicks = state.dateClicks || [];
    document.querySelectorAll('.selector-helper-mode-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === state.mode);
    });
    updatePanel();
  }

  function deriveCommonSelector(el1, el2) {
    if (!el1 || !el2) return '';
    const path1 = buildPath(el1);
    const path2 = buildPath(el2);
    let best = '';
    let bestCount = Infinity;
    for (let i = 0; i < path1.length; i++) {
      const candidate = path1.slice(i).reverse().join(' ');
      if (!candidate) continue;
      try {
        const matches = document.querySelectorAll(candidate);
        const count = matches.length;
        if (count < 2) continue;
        if (!el1.matches(candidate) || !el2.matches(candidate)) continue;
        if (count < bestCount) {
          best = candidate;
          bestCount = count;
        }
      } catch (e) {
        continue;
      }
    }
    return best || buildSelector(el1);
  }

  function buildPath(el) {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body) {
      let part = node.tagName.toLowerCase();
      if (node.id) {
        part += `#${cssEscape(node.id)}`;
        parts.push(part);
        break;
      }
      const classes = Array.from(node.classList || []).filter(c => c && !c.startsWith('selector-helper'));
      if (classes.length) {
        part += `.${classes.map(cssEscape).join('.')}`;
      }
      parts.push(part);
      node = node.parentElement;
    }
    return parts;
  }

  function pickElement(el) {
    if (!el) return;
    const clicks = state.mode === 'date' ? state.dateClicks : state.titleClicks;
    if (clicks.length >= 2) {
      clicks.length = 0;
    }
    clicks.push(el);
    highlightPicked(el);
    if (clicks.length < 2) {
      updatePanel();
      return;
    }
    const selector = deriveCommonSelector(clicks[0], clicks[1]);
    const { count, samples } = getSamples(selector);
    if (state.mode === 'date') {
      state.dateSelector = selector;
      state.dateCount = count;
      state.dateSamples = samples;
    } else {
      state.titleSelector = selector;
      state.titleCount = count;
      state.titleSamples = samples;
    }
    updatePanel();
    sendPicked(state.mode, selector, count, samples);
  }

  function sendPicked(mode, selector, count, samples) {
    if (window.pywebview?.api?.selector_helper_picked) {
      window.pywebview.api.selector_helper_picked({ mode, selector, count, samples });
    }
  }

  function notify(text) {
    if (window.pywebview?.api?.selector_helper_picked) {
      window.pywebview.api.selector_helper_picked({
        mode: state.mode,
        selector: state.mode === 'date' ? state.dateSelector : state.titleSelector,
        count: state.mode === 'date' ? state.dateCount : state.titleCount,
        samples: state.mode === 'date' ? state.dateSamples : state.titleSamples,
        message: text,
      });
      return;
    }
    try {
      alert(text);
    } catch (e) {}
  }

  function applyDetectedTemplate() {
    const url = (document.getElementById('selector-helper-url')?.value || window.location.href || '').trim();
    const key = detectTemplateByUrl(url);
    if (!key) {
      notify('자동 템플릿이 없는 페이지입니다. 제목/날짜를 직접 선택해 주세요.');
      return;
    }
    const tpl = HELPER_TEMPLATE_HINTS[key];
    state.titleSelector = tpl.titleSelector || '';
    state.dateSelector = tpl.dateSelector || '';
    const titleSample = state.titleSelector ? getSamples(state.titleSelector) : { count: 0, samples: [] };
    const dateSample = state.dateSelector ? getSamples(state.dateSelector) : { count: 0, samples: [] };
    state.titleCount = titleSample.count || 0;
    state.dateCount = dateSample.count || 0;
    state.titleSamples = titleSample.samples || [];
    state.dateSamples = dateSample.samples || [];
    updatePanel();

    const payload = {
      titleSelector: state.titleSelector,
      dateSelector: state.dateSelector,
      dateFormat: tpl.dateFormat || '%Y-%m-%d',
      templateKey: key,
      templateName: tpl.name || key,
      titleSamples: state.titleSamples,
      dateSamples: state.dateSamples,
      message: `${tpl.name || '전용'} 추천값을 자동 입력했습니다.`,
    };
    if (window.pywebview?.api?.apply_selector_helper) {
      window.pywebview.api.apply_selector_helper(payload);
    }
    notify(payload.message);
  }

  let hoverEl = null;
  let pickedEl = null;

  function clearHover() {
    if (hoverEl) hoverEl.classList.remove('selector-helper-hover');
    hoverEl = null;
  }

  function highlightPicked(el) {
    if (pickedEl) pickedEl.classList.remove('selector-helper-picked');
    pickedEl = el;
    if (pickedEl) pickedEl.classList.add('selector-helper-picked');
  }

  document.addEventListener('mouseover', (event) => {
    if (panel.contains(event.target)) return;
    clearHover();
    hoverEl = event.target;
    hoverEl.classList.add('selector-helper-hover');
  });

  document.addEventListener('mouseout', (event) => {
    if (panel.contains(event.target)) return;
    if (hoverEl) hoverEl.classList.remove('selector-helper-hover');
  });

  document.addEventListener('click', (event) => {
    if (panel.contains(event.target)) return;
    if (!state.mode) return;
    event.preventDefault();
    event.stopPropagation();
    pickElement(event.target);
  }, true);

  function findByText(query) {
    const needle = (query || '').trim();
    if (!needle) return;
    const candidates = document.querySelectorAll('a, td, th, li, span, div, p');
    let best = null;
    let bestLen = Infinity;
    candidates.forEach(el => {
      if (panel.contains(el)) return;
      const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
      if (!text) return;
      if (text.includes(needle)) {
        if (text.length < bestLen) {
          best = el;
          bestLen = text.length;
        }
      }
    });
    if (best) pickElement(best);
  }

  const panel = document.createElement('div');
  panel.id = 'selector-helper-panel';
  panel.innerHTML = `
    <div class="selector-helper-header">선택자 도우미</div>
    <div class="selector-helper-section">
      <label>대상 URL</label>
      <div class="row">
        <input id="selector-helper-url" type="url" placeholder="https://..." />
        <button id="selector-helper-load" type="button">로드</button>
      </div>
      <div class="hint">목록 페이지에서 제목/날짜를 클릭하면 선택자가 자동 생성됩니다.</div>
    </div>
    <div class="selector-helper-section">
      <label>선택 모드</label>
      <div class="row">
        <button class="selector-helper-mode-btn active" data-mode="title" type="button">제목 선택</button>
        <button class="selector-helper-mode-btn" data-mode="date" type="button">날짜 선택</button>
      </div>
      <div class="hint">기간(예: 2026.01.01 ~ 2026.01.10)은 시작일을 클릭하세요.</div>
    </div>
    <div class="selector-helper-section">
      <label>텍스트로 찾기</label>
      <div class="row">
        <input id="selector-helper-query" type="text" placeholder="예: 탄소중립 강화 계획 발표" />
        <button id="selector-helper-find" type="button">찾기</button>
      </div>
      <div class="hint">클릭 대신 제목 일부로 자동 탐색합니다.</div>
    </div>
    <div class="selector-helper-section">
      <label>페이지 유형 자동 분석</label>
      <div class="row">
        <button id="selector-helper-template" type="button">분석 후 자동 입력</button>
      </div>
      <div class="hint">관보/국회처럼 JS·API 기반 사이트는 추천값을 자동 입력합니다.</div>
    </div>
    <div class="selector-helper-status">
      <strong id="selector-helper-mode">제목 선택 모드</strong>
      <div id="selector-helper-step">1번째 항목 클릭</div>
      <div>선택자</div>
      <code id="selector-helper-selector">-</code>
      <div id="selector-helper-count">매칭 0개</div>
    </div>
    <div class="selector-helper-section">
      <label>샘플 미리보기</label>
      <ul id="selector-helper-samples"><li>선택된 값이 표시됩니다.</li></ul>
    </div>
    <div class="selector-helper-actions">
      <button id="selector-helper-close" type="button">닫기</button>
      <button id="selector-helper-apply" type="button" class="primary">선택자 적용</button>
    </div>
  `;
  document.body.appendChild(panel);

  const style = document.createElement('style');
  style.textContent = `
    #selector-helper-panel {
      position: fixed;
      top: 0;
      left: 0;
      width: ${PANEL_WIDTH}px;
      height: 100vh;
      background: rgba(255,255,255,0.96);
      border-right: 1px solid rgba(0,0,0,0.1);
      padding: 18px 16px;
      box-sizing: border-box;
      z-index: 2147483647;
      font-family: 'Segoe UI', sans-serif;
      font-size: 13px;
      color: #1d1d1f;
      overflow: auto;
      backdrop-filter: blur(12px);
    }
    #selector-helper-panel label { font-weight: 600; display: block; margin-bottom: 6px; }
    #selector-helper-panel .selector-helper-header { font-size: 18px; font-weight: 700; margin-bottom: 14px; }
    #selector-helper-panel .selector-helper-section { margin-bottom: 14px; }
    #selector-helper-panel .row { display: flex; gap: 6px; }
    #selector-helper-panel input { flex: 1; padding: 6px 8px; border-radius: 8px; border: 1px solid rgba(0,0,0,0.15); }
    #selector-helper-panel button { padding: 6px 10px; border-radius: 8px; border: 1px solid rgba(0,0,0,0.15); background: #fff; cursor: pointer; }
    #selector-helper-panel button.primary { background: #1d1d1f; color: #fff; }
    #selector-helper-panel .hint { color: #666; margin-top: 6px; font-size: 12px; }
    #selector-helper-panel .selector-helper-mode-btn.active { background: #eef6f6; border-color: #3aa; }
    #selector-helper-panel .selector-helper-status { background: #f7f7f9; padding: 10px; border-radius: 10px; border: 1px solid rgba(0,0,0,0.06); margin-bottom: 12px; }
    #selector-helper-panel code { display: block; font-size: 11px; word-break: break-all; }
    #selector-helper-panel ul { list-style: none; margin: 0; padding: 0; }
    #selector-helper-panel li { padding: 6px 8px; border-radius: 8px; border: 1px solid rgba(0,0,0,0.08); margin-bottom: 6px; background: #fff; }
    #selector-helper-panel .selector-helper-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }
    .selector-helper-hover { outline: 2px solid rgba(90, 208, 194, 0.9) !important; outline-offset: 2px; }
    .selector-helper-picked { outline: 2px solid rgba(255, 140, 0, 0.9) !important; outline-offset: 2px; }
  `;
  document.head.appendChild(style);

  const urlInput = document.getElementById('selector-helper-url');
  if (urlInput) urlInput.value = window.location.href;

  document.getElementById('selector-helper-load')?.addEventListener('click', () => {
    const url = (urlInput?.value || '').trim();
    if (!url) return;
    if (window.pywebview?.api?.open_selector_helper) {
      window.pywebview.api.open_selector_helper(url);
    } else {
      window.location.href = url;
    }
  });

  document.querySelectorAll('.selector-helper-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => setMode(btn.dataset.mode));
  });

  document.getElementById('selector-helper-find')?.addEventListener('click', () => {
    const query = (document.getElementById('selector-helper-query')?.value || '').trim();
    findByText(query);
  });

  document.getElementById('selector-helper-template')?.addEventListener('click', () => {
    applyDetectedTemplate();
  });

  document.getElementById('selector-helper-apply')?.addEventListener('click', () => {
    const payload = {
      titleSelector: state.titleSelector,
      dateSelector: state.dateSelector,
      titleSamples: state.titleSamples,
      dateSamples: state.dateSamples,
    };
    if (window.pywebview?.api?.apply_selector_helper) {
      window.pywebview.api.apply_selector_helper(payload);
    }
  });

  document.getElementById('selector-helper-close')?.addEventListener('click', () => {
    if (window.pywebview?.api?.close_selector_helper) {
      window.pywebview.api.close_selector_helper();
    } else {
      window.close();
    }
  });

  updatePanel();
})();
