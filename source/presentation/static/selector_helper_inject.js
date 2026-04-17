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

  const DATE_PATTERNS = [
    /\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\s*[~~-]\s*\d{4}[./-]\d{1,2}[./-]\d{1,2}\b/,
    /\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b/,
    /\b\d{4}년\s*\d{1,2}월\s*\d{1,2}일(?:\s*[~~-]\s*\d{4}년\s*\d{1,2}월\s*\d{1,2}일)?\b/,
  ];

  const HELPER_TEMPLATE_HINTS = {
    gwanbo_daily: {
      name: '전자관보',
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

  function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  }

  function detectTemplateByUrl(url) {
    const target = normalizeText(url);
    if (!target) return '';
    for (const [key, value] of Object.entries(HELPER_TEMPLATE_HINTS)) {
      if (value.urlMatch && value.urlMatch.test(target)) {
        return key;
      }
    }
    return '';
  }

  function extractDateValue(text) {
    const source = normalizeText(text);
    if (!source) return '';
    for (const pattern of DATE_PATTERNS) {
      const match = source.match(pattern);
      if (match) return match[0];
    }
    return '';
  }

  function getNodePreviewText(node, mode) {
    const raw = normalizeText(node && node.textContent);
    if (!raw) return '';
    if (mode === 'date') {
      return extractDateValue(raw);
    }
    return raw.slice(0, 120);
  }

  function getSamples(selector, mode) {
    if (!selector) return { count: 0, validCount: 0, samples: [] };
    let nodes = [];
    try {
      nodes = Array.from(document.querySelectorAll(selector));
    } catch (e) {
      return { count: 0, validCount: 0, samples: [] };
    }

    const texts = nodes.map(node => getNodePreviewText(node, mode)).filter(Boolean);
    return {
      count: nodes.length,
      validCount: texts.length,
      samples: texts.slice(0, 6),
    };
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

  function deriveCommonSelector(el1, el2) {
    if (!el1 || !el2) return '';
    const path = buildPath(el1);
    let best = '';
    let bestCount = Infinity;
    for (let i = 0; i < path.length; i++) {
      const candidate = path.slice(i).reverse().join(' ');
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

  function getElementIndex(el) {
    if (!el || !el.parentElement) return -1;
    return Array.from(el.parentElement.children).indexOf(el) + 1;
  }

  function getSelectionNode(el, mode) {
    if (!el) return null;
    const node = el.nodeType === 1 ? el : el.parentElement;
    if (!node || node === document.body) return null;
    const selector = mode === 'date'
      ? 'time, td, th, li, dd, dt, p, span, div'
      : 'a, td, th, li, dd, dt, h1, h2, h3, h4, h5, p, span, div';
    const found = node.closest(selector);
    return found && found !== document.body ? found : node;
  }

  function deriveIndexedSiblingSelector(el1, el2, mode) {
    const node1 = getSelectionNode(el1, mode);
    const node2 = getSelectionNode(el2, mode);
    if (!node1 || !node2) return '';
    if (node1.tagName !== node2.tagName) return '';
    const index1 = getElementIndex(node1);
    const index2 = getElementIndex(node2);
    if (index1 < 1 || index1 !== index2) return '';
    const parent1 = node1.parentElement;
    const parent2 = node2.parentElement;
    if (!parent1 || !parent2) return '';
    const parentSelector = deriveCommonSelector(parent1, parent2);
    if (!parentSelector) return '';
    return `${parentSelector} > ${node1.tagName.toLowerCase()}:nth-child(${index1})`;
  }

  function scoreCandidate(selector, el1, el2, mode) {
    if (!selector) return Number.NEGATIVE_INFINITY;
    let nodes = [];
    try {
      nodes = Array.from(document.querySelectorAll(selector));
    } catch (e) {
      return Number.NEGATIVE_INFINITY;
    }
    if (nodes.length < 2) return Number.NEGATIVE_INFINITY;
    if (!el1.matches(selector) || !el2.matches(selector)) return Number.NEGATIVE_INFINITY;

    const meta = getSamples(selector, mode);
    if (mode === 'date') {
      if (meta.validCount < 2) return Number.NEGATIVE_INFINITY;
      const ratio = meta.validCount / Math.max(nodes.length, 1);
      if (ratio < 0.6) return Number.NEGATIVE_INFINITY;
      return ratio * 1000 - nodes.length;
    }

    return 800 - nodes.length;
  }

  function chooseBestSelector(el1, el2, mode) {
    const node1 = getSelectionNode(el1, mode);
    const node2 = getSelectionNode(el2, mode);
    if (!node1 || !node2) return '';

    const candidates = new Set();
    if (mode === 'date') {
      candidates.add(deriveIndexedSiblingSelector(node1, node2, mode));
    }
    candidates.add(deriveCommonSelector(node1, node2));
    candidates.add(buildSelector(node1));

    let best = '';
    let bestScore = Number.NEGATIVE_INFINITY;
    candidates.forEach(candidate => {
      const score = scoreCandidate(candidate, node1, node2, mode);
      if (score > bestScore) {
        bestScore = score;
        best = candidate;
      }
    });
    return best;
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
    } catch (e) {
      console.warn(text);
    }
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
        ? samples.map(sample => `<li>${escapeHtml(sample)}</li>`).join('')
        : '<li>선택된 값이 표시됩니다.</li>';
    }
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

  function applyDetectedTemplate() {
    const url = normalizeText(document.getElementById('selector-helper-url')?.value || window.location.href || '');
    const key = detectTemplateByUrl(url);
    if (!key) {
      notify('자동 템플릿이 없는 페이지입니다. 제목과 날짜를 직접 선택해 주세요.');
      return;
    }
    const tpl = HELPER_TEMPLATE_HINTS[key];
    state.titleSelector = tpl.titleSelector || '';
    state.dateSelector = tpl.dateSelector || '';
    const titleMeta = state.titleSelector ? getSamples(state.titleSelector, 'title') : { count: 0, samples: [] };
    const dateMeta = state.dateSelector ? getSamples(state.dateSelector, 'date') : { count: 0, samples: [] };
    state.titleCount = titleMeta.count || 0;
    state.dateCount = dateMeta.count || 0;
    state.titleSamples = titleMeta.samples || [];
    state.dateSamples = dateMeta.samples || [];
    updatePanel();

    const payload = {
      titleSelector: state.titleSelector,
      dateSelector: state.dateSelector,
      dateFormat: tpl.dateFormat || '%Y-%m-%d',
      templateKey: key,
      templateName: tpl.name || key,
      titleSamples: state.titleSamples,
      dateSamples: state.dateSamples,
      keepRawSelectors: /:nth-(?:child|of-type)\(/i.test(state.titleSelector) || /:nth-(?:child|of-type)\(/i.test(state.dateSelector),
      message: `${tpl.name || '추천값'} 추천값을 자동 입력했습니다.`,
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

  function applyPickedResult(mode, selector) {
    const meta = getSamples(selector, mode);
    if (mode === 'date') {
      state.dateSelector = selector;
      state.dateCount = meta.count;
      state.dateSamples = meta.samples;
    } else {
      state.titleSelector = selector;
      state.titleCount = meta.count;
      state.titleSamples = meta.samples;
    }
    updatePanel();
    sendPicked(mode, selector, meta.count, meta.samples);
  }

  function pickElement(el) {
    const target = getSelectionNode(el, state.mode);
    if (!target) return;
    const clicks = state.mode === 'date' ? state.dateClicks : state.titleClicks;
    if (clicks.length >= 2) {
      clicks.length = 0;
    }
    clicks.push(target);
    highlightPicked(target);
    updatePanel();

    if (clicks.length < 2) {
      return;
    }

    const selector = chooseBestSelector(clicks[0], clicks[1], state.mode);
    if (!selector) {
      const message = state.mode === 'date'
        ? '날짜 선택자를 찾지 못했습니다. 같은 날짜 열 또는 같은 위치의 날짜를 다시 눌러 주세요.'
        : '제목 선택자를 찾지 못했습니다. 같은 목록의 제목 두 개를 다시 눌러 주세요.';
      clicks.length = 0;
      updatePanel();
      notify(message);
      return;
    }

    applyPickedResult(state.mode, selector);
  }

  function findByText(query) {
    const needle = normalizeText(query);
    if (!needle) return;
    const candidates = document.querySelectorAll('a, td, th, li, span, div, p');
    let best = null;
    let bestLength = Infinity;
    candidates.forEach(el => {
      if (panel.contains(el)) return;
      const text = normalizeText(el.textContent);
      if (!text || !text.includes(needle)) return;
      if (text.length < bestLength) {
        best = el;
        bestLength = text.length;
      }
    });
    if (best) {
      const selector = buildSelector(getSelectionNode(best, 'title'));
      if (selector) {
        applyPickedResult('title', selector);
      }
    }
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
      <div class="hint">목록 페이지에서 제목과 날짜를 클릭하면 선택자가 자동 생성됩니다.</div>
    </div>
    <div class="selector-helper-section">
      <label>선택 모드</label>
      <div class="row">
        <button class="selector-helper-mode-btn active" data-mode="title" type="button">제목 선택</button>
        <button class="selector-helper-mode-btn" data-mode="date" type="button">날짜 선택</button>
      </div>
      <div class="hint">기간형 날짜는 시작일을 클릭하세요.</div>
    </div>
    <div class="selector-helper-section">
      <label>텍스트로 찾기</label>
      <div class="row">
        <input id="selector-helper-query" type="text" placeholder="예: 주택 공급 대책 발표" />
        <button id="selector-helper-find" type="button">찾기</button>
      </div>
      <div class="hint">클릭 대신 제목 일부로 자동 탐색할 수 있습니다.</div>
    </div>
    <div class="selector-helper-section">
      <label>페이지 유형 자동 분석</label>
      <div class="row">
        <button id="selector-helper-template" type="button">분석 후 자동 입력</button>
      </div>
      <div class="hint">전자관보·국회처럼 전용 유형은 추천값을 자동 입력합니다.</div>
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
    const url = normalizeText(urlInput?.value);
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
    findByText(document.getElementById('selector-helper-query')?.value);
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
      keepRawSelectors: /:nth-(?:child|of-type)\(/i.test(state.titleSelector) || /:nth-(?:child|of-type)\(/i.test(state.dateSelector),
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

  updatePanel();
})();
