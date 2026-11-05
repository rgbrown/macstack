/**
 * macstack — STACK Authoring Workbench
 * Live-Reload Browser Workbench Application
 */

(function () {
  'use strict';

  // --- State ---
  const state = {
    root: '',
    questions: [],
    activePath: null,
    activeSeed: null,
    questionData: null,
    userAnswers: {},
    lastGradedResult: null,
    eventSource: null,
    theme: localStorage.getItem('macstack-theme') || 'light'
  };

  // --- MathJax Queued Typeset Helper ---
  let mathJaxQueue = Promise.resolve();
  function typeset(elements) {
    if (!window.MathJax || !window.MathJax.typesetPromise) {
      return Promise.resolve();
    }
    mathJaxQueue = mathJaxQueue.then(() => {
      const targets = elements ? (Array.isArray(elements) ? elements : [elements]) : undefined;
      return window.MathJax.typesetPromise(targets).catch((err) => {
        console.warn('[macstack] MathJax typeset warning:', err);
      });
    });
    return mathJaxQueue;
  }

  // --- DOM Elements ---
  const dom = {
    // Top Nav
    activeQuestionName: document.getElementById('active-question-name'),
    activeQuestionId: document.getElementById('active-question-id'),
    connectionStatus: document.getElementById('connection-status'),
    btnThemeToggle: document.getElementById('btn-theme-toggle'),

    // Sidebar
    workspaceRootName: document.getElementById('workspace-root-name'),
    questionSearch: document.getElementById('question-search'),
    questionList: document.getElementById('question-list'),

    // Toolbar
    seedSelect: document.getElementById('seed-select'),
    customSeedInput: document.getElementById('custom-seed-input'),
    btnApplySeed: document.getElementById('btn-apply-seed'),
    btnRollSeed: document.getElementById('btn-roll-seed'),
    btnDeploySeeds: document.getElementById('btn-deploy-seeds'),
    btnFillCorrect: document.getElementById('btn-fill-correct'),
    btnReset: document.getElementById('btn-reset'),
    btnCheckAnswer: document.getElementById('btn-check-answer'),

    // Moodle Preview Card
    qStatusText: document.getElementById('q-status-text'),
    qPointsText: document.getElementById('q-points-text'),
    qSeedVal: document.getElementById('q-seed-val'),
    questionText: document.getElementById('question-text'),
    btnCheckAnswerInline: document.getElementById('btn-check-answer-inline'),
    btnFillCorrectInline: document.getElementById('btn-fill-correct-inline'),

    // Grading & Feedback
    gradeSummaryBanner: document.getElementById('grade-summary-banner'),
    gradeBannerIcon: document.getElementById('grade-banner-icon'),
    gradeBannerHeadline: document.getElementById('grade-banner-headline'),
    gradeBannerScore: document.getElementById('grade-banner-score'),
    specificFeedbackContainer: document.getElementById('specific-feedback-container'),
    specificFeedbackBody: document.getElementById('specific-feedback-body'),

    // Collapsibles
    hintsAccordion: document.getElementById('hints-accordion'),
    btnToggleHints: document.getElementById('btn-toggle-hints'),
    hintsCount: document.getElementById('hints-count'),
    hintsContent: document.getElementById('hints-content'),
    generalFeedbackAccordion: document.getElementById('general-feedback-accordion'),
    btnToggleGeneralFeedback: document.getElementById('btn-toggle-general-feedback'),
    modelSolutionText: document.getElementById('model-solution-text'),
    generalQuestionNote: document.getElementById('general-question-note'),

    // Inspector Tabs
    inspectorTabs: document.querySelectorAll('.inspector-tab'),
    tabPanes: document.querySelectorAll('.tab-pane'),
    prtBadge: document.getElementById('prt-badge'),
    lintBadge: document.getElementById('lint-badge'),
    testsBadge: document.getElementById('tests-badge'),

    // Inspector Content
    varsTbody: document.getElementById('vars-tbody'),
    varsCountLabel: document.getElementById('vars-count-label'),
    inspectorQuestionNote: document.getElementById('inspector-question-note'),
    varsErrorsContainer: document.getElementById('vars-errors-container'),
    varsErrorsText: document.getElementById('vars-errors-text'),
    prtTraceList: document.getElementById('prt-trace-list'),
    prtStatusLabel: document.getElementById('prt-status-label'),
    lintList: document.getElementById('lint-list'),
    lintCountLabel: document.getElementById('lint-count-label'),
    btnRunTests: document.getElementById('btn-run-tests'),
    testsSummaryBanner: document.getElementById('tests-summary-banner'),
    testsSummaryStatus: document.getElementById('tests-summary-status'),
    testsResultsContainer: document.getElementById('tests-results-container'),

    // Toast
    toastContainer: document.getElementById('toast-container')
  };

  // --- Utilities ---
  function debounce(func, wait) {
    let timeout;
    return function (...args) {
      clearTimeout(timeout);
      timeout = setTimeout(() => func.apply(this, args), wait);
    };
  }

  function showToast(message, type = 'info', duration = 3000) {
    if (!dom.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    let icon = 'fa-info-circle';
    if (type === 'reload') icon = 'fa-rotate';
    else if (type === 'success') icon = 'fa-check';
    else if (type === 'error') icon = 'fa-triangle-exclamation';

    toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${escapeHtml(message)}</span>`;
    dom.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      setTimeout(() => toast.remove(), 250);
    }, duration);
  }

  function escapeHtml(str) {
    if (typeof str !== 'string') return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /**
   * Replaces asset keys (e.g. "stackplot-..." or filenames) with /plots/<mapped_filename>
   */
  function replaceAssetUrls(html, assets) {
    if (!html || !assets || typeof assets !== 'object') return html || '';
    let result = html;
    for (const [key, mapped] of Object.entries(assets)) {
      if (!key || !mapped) continue;
      const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(escapedKey, 'g');
      result = result.replace(regex, `/plots/${mapped}`);
    }
    return result;
  }

  // --- Theme Management ---
  function initTheme() {
    document.documentElement.setAttribute('data-theme', state.theme);
    updateThemeIcon();
    dom.btnThemeToggle.addEventListener('click', () => {
      state.theme = state.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', state.theme);
      localStorage.setItem('macstack-theme', state.theme);
      updateThemeIcon();
    });
  }

  function updateThemeIcon() {
    const icon = dom.btnThemeToggle.querySelector('i');
    if (!icon) return;
    if (state.theme === 'dark') {
      icon.className = 'fa-solid fa-sun';
    } else {
      icon.className = 'fa-solid fa-moon';
    }
  }

  // --- Accordion Controls ---
  function initAccordions() {
    dom.btnToggleHints.addEventListener('click', () => {
      dom.hintsAccordion.classList.toggle('open');
    });
    dom.btnToggleGeneralFeedback.addEventListener('click', () => {
      dom.generalFeedbackAccordion.classList.toggle('open');
    });
  }

  // --- Inspector Tabs ---
  function initInspectorTabs() {
    dom.inspectorTabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        const targetId = tab.getAttribute('data-tab');
        dom.inspectorTabs.forEach((t) => t.classList.remove('active'));
        dom.tabPanes.forEach((p) => p.classList.remove('active'));

        tab.classList.add('active');
        const targetPane = document.getElementById(targetId);
        if (targetPane) targetPane.classList.add('active');
      });
    });
  }

  // --- Fetch Questions List ---
  async function loadQuestions(preserveActive = true) {
    try {
      const res = await fetch('/api/questions');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      state.root = data.root || '';
      state.questions = data.questions || [];

      // Update workspace root label
      const rootParts = state.root.split('/').filter(Boolean);
      dom.workspaceRootName.textContent = rootParts[rootParts.length - 1] || 'Workspace';

      renderQuestionsList();

      if (!preserveActive || !state.activePath) {
        const defaultPath = data.active || (state.questions[0] ? state.questions[0].relpath : null);
        if (defaultPath) {
          selectQuestion(defaultPath);
        }
      }
    } catch (err) {
      console.error('[macstack] Failed to load questions:', err);
      dom.questionList.innerHTML = `<div class="sidebar-loading text-danger"><i class="fa-solid fa-triangle-exclamation"></i> Error loading questions</div>`;
    }
  }

  function renderQuestionsList() {
    const filter = (dom.questionSearch.value || '').trim().toLowerCase();
    const filtered = state.questions.filter((q) => {
      if (!filter) return true;
      return (
        (q.name && q.name.toLowerCase().includes(filter)) ||
        (q.idnumber && q.idnumber.toLowerCase().includes(filter)) ||
        (q.relpath && q.relpath.toLowerCase().includes(filter)) ||
        (q.category && q.category.toLowerCase().includes(filter))
      );
    });

    if (filtered.length === 0) {
      dom.questionList.innerHTML = `<div class="sidebar-loading">No questions match filter</div>`;
      return;
    }

    // Group by category
    const grouped = {};
    for (const q of filtered) {
      const cat = q.category || 'General';
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(q);
    }

    dom.questionList.innerHTML = '';
    for (const [category, items] of Object.entries(grouped)) {
      const groupEl = document.createElement('div');
      groupEl.className = 'category-group';

      const headerEl = document.createElement('div');
      headerEl.className = 'category-header';
      headerEl.innerHTML = `<span>${escapeHtml(category)}</span><span class="text-subtle font-mono">${items.length}</span>`;
      groupEl.appendChild(headerEl);

      for (const q of items) {
        const itemEl = document.createElement('div');
        itemEl.className = `question-item ${q.relpath === state.activePath ? 'active' : ''}`;
        itemEl.dataset.relpath = q.relpath;

        let badgesHtml = '';
        if (q.error_count > 0) {
          badgesHtml += `<span class="badge badge-error" title="${q.error_count} error(s)"><i class="fa-solid fa-circle-exclamation"></i> ${q.error_count}</span>`;
        }
        if (q.warning_count > 0) {
          badgesHtml += `<span class="badge badge-warning" title="${q.warning_count} warning(s)"><i class="fa-solid fa-triangle-exclamation"></i> ${q.warning_count}</span>`;
        }

        if (q.deployed_seeds_count > 0) {
          badgesHtml += `<span class="badge badge-seeds" title="${q.deployed_seeds_count} deployed seeds"><i class="fa-solid fa-seedling"></i> ${q.deployed_seeds_count}</span>`;
        } else {
          badgesHtml += `<span class="badge badge-seeds none" title="0 deployed seeds (randomized questions should deploy variants)"><i class="fa-solid fa-seedling"></i> 0</span>`;
        }

        if (q.qtest_count > 0) {
          badgesHtml += `<span class="badge badge-tests" title="${q.qtest_count} question test(s)"><i class="fa-solid fa-vial"></i> ${q.qtest_count}</span>`;
        }

        itemEl.innerHTML = `
          <div class="q-item-header">
            <span class="q-title">${escapeHtml(q.name || q.idnumber || q.relpath)}</span>
          </div>
          <div class="q-badges">
            <span class="badge font-mono" style="background:var(--bg-hover);color:var(--text-subtle);">${escapeHtml(q.idnumber || '')}</span>
            ${badgesHtml}
          </div>
        `;

        itemEl.addEventListener('click', () => {
          selectQuestion(q.relpath);
        });

        groupEl.appendChild(itemEl);
      }

      dom.questionList.appendChild(groupEl);
    }
  }

  // --- Select & Load Single Question ---
  async function selectQuestion(relpath, seed = null) {
    if (!relpath) return;
    state.activePath = relpath;
    if (seed !== null && seed !== undefined) {
      state.activeSeed = parseInt(seed, 10);
    }

    // Update active highlight in sidebar
    document.querySelectorAll('.question-item').forEach((el) => {
      el.classList.toggle('active', el.dataset.relpath === relpath);
    });

    try {
      let url = `/api/question?path=${encodeURIComponent(relpath)}`;
      if (state.activeSeed !== null && state.activeSeed !== undefined && !isNaN(state.activeSeed)) {
        url += `&seed=${state.activeSeed}`;
      }

      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      state.questionData = data;
      state.activeSeed = data.effective_seed;

      renderQuestion(data);
    } catch (err) {
      console.error('[macstack] Failed to load question:', err);
      dom.questionText.innerHTML = `<div class="error-banner">Failed to load question: ${escapeHtml(err.message)}</div>`;
    }
  }

  // --- Render Question into DOM ---
  function renderQuestion(data) {
    const summary = data.summary || {};
    const render = data.render || {};
    const vars = data.vars || {};
    const lint = data.lint || [];
    const hints = data.hints || [];

    // 1. Update Header & Meta
    dom.activeQuestionName.textContent = summary.name || summary.idnumber || summary.relpath;
    dom.activeQuestionId.textContent = summary.idnumber || summary.relpath;
    dom.qSeedVal.textContent = data.effective_seed;
    dom.customSeedInput.value = data.effective_seed;

    // Reset student status
    dom.qStatusText.textContent = 'Not yet answered';
    hideGradeBanner();
    hideSpecificFeedback();

    // 2. Populate Seed Dropdown
    populateSeedSelector(summary.deployed_seeds || [], data.effective_seed);

    // 3. Render Question Body
    renderQuestionFormulation(render, data.effective_seed);

    // 4. Render Hints Accordion
    renderHints(hints);

    // 5. Render General Feedback / Model Solution
    renderGeneralFeedback(render, summary);

    // 6. Update Inspector Tabs
    renderInspectorVars(vars);
    renderInspectorLint(lint);
    renderInspectorPRT(null); // Clear until submission
    renderInspectorTestsInitial(summary.qtest_count || 0);

    // Typeset entire container
    typeset([dom.questionText, dom.hintsContent, dom.generalFeedbackAccordion, dom.varsTbody]);
  }

  function populateSeedSelector(deployedSeeds, effectiveSeed) {
    dom.seedSelect.innerHTML = '<option value="">Deployed seeds...</option>';
    if (deployedSeeds && deployedSeeds.length > 0) {
      for (const s of deployedSeeds) {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = `Seed ${s}`;
        if (parseInt(s, 10) === parseInt(effectiveSeed, 10)) {
          opt.selected = true;
        }
        dom.seedSelect.appendChild(opt);
      }
    } else {
      const opt = document.createElement('option');
      opt.value = "";
      opt.textContent = "No deployed seeds";
      opt.disabled = true;
      dom.seedSelect.appendChild(opt);
    }
  }

  // --- Replace Tokens & Build Interactive Inputs ---
  function renderQuestionFormulation(render, currentSeed) {
    let rawHtml = render.questionrender || '<p>No question text rendered.</p>';
    const assets = render.questionassets || {};
    const inputsConfig = render.inputs || {};

    // Map asset URLs before injection
    rawHtml = replaceAssetUrls(rawHtml, assets);

    // Parse into temporary DOM node to replace [[input:NAME]] and [[validation:NAME]]
    const tempContainer = document.createElement('div');
    tempContainer.innerHTML = rawHtml;

    // First find all inputs defined
    const inputNames = Object.keys(inputsConfig);

    // Replace [[input:NAME]] and [[validation:NAME]] inside text nodes or HTML
    let currentHtml = tempContainer.innerHTML;

    for (const name of inputNames) {
      const inputDef = inputsConfig[name] || {};
      const widgetHtml = buildInputWidgetHtml(name, inputDef);
      const validationHtml = `<div class="stackinputfeedback" id="validation-${name}"></div>`;

      const inputRegex = new RegExp(`\\[\\[input:${name}\\]\\]`, 'g');
      const valRegex = new RegExp(`\\[\\[validation:${name}\\]\\]`, 'g');

      if (inputRegex.test(currentHtml)) {
        currentHtml = currentHtml.replace(inputRegex, widgetHtml);
      }

      if (valRegex.test(currentHtml)) {
        currentHtml = currentHtml.replace(valRegex, validationHtml);
      } else {
        // If no explicit [[validation:NAME]], append right after the input widget
        currentHtml = currentHtml.replace(widgetHtml, `${widgetHtml} ${validationHtml}`);
      }
    }

    dom.questionText.innerHTML = currentHtml;

    // Attach event listeners for inputs
    attachInputListeners(inputsConfig);

    // Restore any previously entered values
    restoreUserAnswers(inputsConfig);
  }

  function buildInputWidgetHtml(name, inputDef) {
    const config = inputDef.configuration || {};
    const type = (config.type || 'algebraic').toLowerCase();
    const boxWidth = config.boxWidth || 15;

    switch (type) {
      case 'textarea':
      case 'equiv': {
        const rows = config.height || 4;
        const cols = boxWidth || 40;
        return `
          <div class="stack-input-wrapper stack-input-textarea">
            <textarea class="form-control stack-input-area" id="input-${name}" name="${name}" rows="${rows}" cols="${cols}"></textarea>
          </div>
        `;
      }

      case 'dropdown': {
        const options = config.options || {};
        let optionsHtml = '<option value="">Choose an answer...</option>';
        if (Array.isArray(options)) {
          for (const opt of options) {
            const key = Array.isArray(opt) ? opt[0] : opt;
            const label = Array.isArray(opt) ? opt[1] : opt;
            optionsHtml += `<option value="${escapeHtml(String(key))}">${escapeHtml(String(label))}</option>`;
          }
        } else {
          for (const [key, label] of Object.entries(options)) {
            optionsHtml += `<option value="${escapeHtml(String(key))}">${escapeHtml(String(label))}</option>`;
          }
        }
        return `
          <div class="stack-input-wrapper stack-input-dropdown">
            <select class="form-select stack-input-select" id="input-${name}" name="${name}">
              ${optionsHtml}
            </select>
          </div>
        `;
      }

      case 'radio': {
        const options = config.options || {};
        let radiosHtml = '<div class="stack-radio-group">';
        const entries = Array.isArray(options) ? options.map(o => Array.isArray(o) ? o : [o, o]) : Object.entries(options);
        for (const [key, label] of entries) {
          radiosHtml += `
            <label class="stack-radio-label">
              <input type="radio" name="${name}" value="${escapeHtml(String(key))}">
              <span class="opt-text">${label}</span>
            </label>
          `;
        }
        radiosHtml += '</div>';
        return radiosHtml;
      }

      case 'checkbox': {
        const options = config.options || {};
        let checksHtml = '<div class="stack-checkbox-group">';
        const entries = Array.isArray(options) ? options.map(o => Array.isArray(o) ? o : [o, o]) : Object.entries(options);
        for (const [key, label] of entries) {
          checksHtml += `
            <label class="stack-checkbox-label">
              <input type="checkbox" name="${name}" data-key="${escapeHtml(String(key))}" value="${escapeHtml(String(key))}">
              <span class="opt-text">${label}</span>
            </label>
          `;
        }
        checksHtml += '</div>';
        return checksHtml;
      }

      case 'matrix': {
        const rows = parseInt(config.height || 2, 10);
        const cols = parseInt(config.width || 2, 10);
        const brackets = (config.matrixbrackets || 'matrixsquarebrackets').toLowerCase();
        let bracketClass = 'matrix-bracket-square';
        if (brackets.includes('round') || brackets.includes('parentheses')) {
          bracketClass = 'matrix-bracket-round';
        }

        // Detect 0-based vs 1-based indexing from samplesolution keys if available
        let rowStart = 0;
        let colStart = 0;
        const sampleKeys = Object.keys(inputDef.samplesolution || {});
        for (const k of sampleKeys) {
          const match = k.match(new RegExp(`^(?:${name})?_sub_(\\d+)_(\\d+)$`));
          if (match) {
            const r = parseInt(match[1], 10);
            const c = parseInt(match[2], 10);
            if (r === 1 || c === 1) {
              rowStart = 1;
              colStart = 1;
              break;
            }
          }
        }

        let cellsHtml = `<div class="stack-matrix-container ${bracketClass}">`;
        cellsHtml += `<div class="matrix-grid" style="grid-template-columns: repeat(${cols}, auto);">`;
        for (let r = 0; r < rows; r++) {
          for (let c = 0; c < cols; c++) {
            const rowIdx = rowStart + r;
            const colIdx = colStart + c;
            const cellKey = `${name}_sub_${rowIdx}_${colIdx}`;
            cellsHtml += `
              <input type="text"
                     class="matrix-cell"
                     id="input-${cellKey}"
                     name="${cellKey}"
                     data-input-name="${name}"
                     data-row="${rowIdx}"
                     data-col="${colIdx}"
                     autocomplete="off"
                     spellcheck="false">
            `;
          }
        }
        cellsHtml += `</div></div>`;
        return cellsHtml;
      }

      case 'algebraic':
      case 'numerical':
      case 'string':
      case 'units':
      case 'singlechar':
      default: {
        const minCh = Math.max(8, parseInt(boxWidth || 15, 10));
        const widthCh = `${minCh * 1.15}ch`;
        return `
          <div class="stack-input-wrapper stack-input-${type}">
            <input type="text"
                   class="form-control stack-input-text"
                   id="input-${name}"
                   name="${name}"
                   size="${boxWidth}"
                   style="width: ${widthCh}; max-width: 100%;"
                   autocomplete="off"
                   spellcheck="false">
          </div>
        `;
      }
    }
  }

  // --- Attach Event Listeners to Inputs ---
  function attachInputListeners(inputsConfig) {
    const debouncedValidate = debounce((name) => {
      validateSingleInput(name);
    }, 350);

    for (const name of Object.keys(inputsConfig)) {
      const inputDef = inputsConfig[name] || {};
      const config = inputDef.configuration || {};
      const type = (config.type || 'algebraic').toLowerCase();

      if (type === 'matrix') {
        const cells = dom.questionText.querySelectorAll(`[data-input-name="${name}"]`);
        cells.forEach((cell) => {
          cell.addEventListener('input', () => {
            collectUserAnswers();
            debouncedValidate(name);
          });
          cell.addEventListener('blur', () => {
            collectUserAnswers();
            validateSingleInput(name);
          });
        });
      } else if (type === 'radio') {
        const radios = dom.questionText.querySelectorAll(`input[name="${name}"][type="radio"]`);
        radios.forEach((r) => {
          r.addEventListener('change', () => {
            collectUserAnswers();
            validateSingleInput(name);
          });
        });
      } else if (type === 'checkbox') {
        const checks = dom.questionText.querySelectorAll(`input[name="${name}"][type="checkbox"]`);
        checks.forEach((c) => {
          c.addEventListener('change', () => {
            collectUserAnswers();
            validateSingleInput(name);
          });
        });
      } else if (type === 'dropdown') {
        const sel = dom.questionText.querySelector(`select[name="${name}"]`);
        if (sel) {
          sel.addEventListener('change', () => {
            collectUserAnswers();
            validateSingleInput(name);
          });
        }
      } else {
        const inp = dom.questionText.querySelector(`[name="${name}"]`);
        if (inp) {
          inp.addEventListener('input', () => {
            collectUserAnswers();
            debouncedValidate(name);
          });
          inp.addEventListener('blur', () => {
            collectUserAnswers();
            validateSingleInput(name);
          });
        }
      }
    }
  }

  // --- Collect Answers into STACK Map ---
  function collectUserAnswers() {
    const answers = {};
    if (!state.questionData || !state.questionData.render) return answers;
    const inputsConfig = state.questionData.render.inputs || {};

    for (const name of Object.keys(inputsConfig)) {
      const inputDef = inputsConfig[name] || {};
      const config = inputDef.configuration || {};
      const type = (config.type || 'algebraic').toLowerCase();

      if (type === 'matrix') {
        const cells = dom.questionText.querySelectorAll(`[data-input-name="${name}"]`);
        cells.forEach((cell) => {
          const key = cell.name;
          answers[key] = cell.value.trim();
        });
      } else if (type === 'radio') {
        const checked = dom.questionText.querySelector(`input[name="${name}"][type="radio"]:checked`);
        if (checked) {
          answers[name] = checked.value;
        }
      } else if (type === 'checkbox') {
        const checks = dom.questionText.querySelectorAll(`input[name="${name}"][type="checkbox"]`);
        // Check how samplesolution is formatted: subkeys like ans1_1 or single key
        const sampleKeys = Object.keys(inputDef.samplesolution || {});
        const hasSubKeys = sampleKeys.some((k) => k.startsWith(`${name}_`) || k.startsWith('_'));

        if (hasSubKeys) {
          checks.forEach((c) => {
            if (c.checked) {
              const key = `${name}_${c.dataset.key || c.value}`;
              answers[key] = c.dataset.key || c.value;
            }
          });
        } else {
          const selected = [];
          checks.forEach((c) => {
            if (c.checked) selected.push(c.value);
          });
          answers[name] = selected.join(',');
        }
      } else if (type === 'dropdown') {
        const sel = dom.questionText.querySelector(`select[name="${name}"]`);
        if (sel && sel.value) {
          answers[name] = sel.value;
        }
      } else {
        const el = dom.questionText.querySelector(`[name="${name}"]`);
        if (el) {
          answers[name] = el.value.trim();
        }
      }
    }

    state.userAnswers = answers;
    return answers;
  }

  function restoreUserAnswers(inputsConfig) {
    if (!state.userAnswers || Object.keys(state.userAnswers).length === 0) return;

    for (const [key, val] of Object.entries(state.userAnswers)) {
      if (val === undefined || val === null) continue;

      // Direct ID or name match (text, textarea, select, matrix cell)
      const el = dom.questionText.querySelector(`[name="${key}"]`);
      if (el) {
        if (el.tagName === 'SELECT') {
          el.value = val;
        } else if (el.type === 'radio') {
          const radio = dom.questionText.querySelector(`input[name="${key}"][value="${val}"]`);
          if (radio) radio.checked = true;
        } else if (el.type === 'checkbox') {
          el.checked = val === '1' || val === true || val === 'true';
        } else {
          el.value = val;
        }
      } else {
        // Handle checkbox subkeys
        const match = key.match(/^(.+?)_(.+)$/);
        if (match) {
          const baseName = match[1];
          const optKey = match[2];
          const cb = dom.questionText.querySelector(`input[name="${baseName}"][data-key="${optKey}"]`);
          if (cb) {
            cb.checked = val === '1' || val === true || val === 'true';
          }
        }
      }
    }
  }

  // --- Validate Single Input ---
  async function validateSingleInput(inputName) {
    if (!state.activePath) return;
    const answers = collectUserAnswers();
    const valContainer = document.getElementById(`validation-${inputName}`);
    if (!valContainer) return;

    try {
      const res = await fetch('/api/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: state.activePath,
          seed: state.activeSeed,
          inputName: inputName,
          answers: answers
        })
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const validationHtml = data.validation ?? data.Validation ?? '';
      valContainer.innerHTML = validationHtml;
      typeset(valContainer);
    } catch (err) {
      console.warn(`[macstack] Validation failed for ${inputName}:`, err);
    }
  }

  // --- Check & Grade Answers ---
  async function gradeCurrentAnswers() {
    if (!state.activePath) return;
    const answers = collectUserAnswers();

    dom.btnCheckAnswer.disabled = true;
    dom.btnCheckAnswerInline.disabled = true;
    dom.qStatusText.textContent = 'Submitting & Grading...';

    try {
      const res = await fetch('/api/grade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: state.activePath,
          seed: state.activeSeed,
          answers: answers
        })
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.lastGradedResult = data;

      renderGradedResult(data);
    } catch (err) {
      console.error('[macstack] Grading error:', err);
      showToast(`Grading error: ${err.message}`, 'error');
      dom.qStatusText.textContent = 'Grading Error';
    } finally {
      dom.btnCheckAnswer.disabled = false;
      dom.btnCheckAnswerInline.disabled = false;
    }
  }

  function renderGradedResult(data) {
    const score = typeof data.score === 'number' ? data.score : 0;
    const isFull = score >= 0.999;
    const isPartial = score > 0.001 && score < 0.999;
    const isZero = score <= 0.001;

    // 1. Grade Banner
    dom.gradeSummaryBanner.style.display = 'flex';
    dom.gradeSummaryBanner.className = 'grade-banner';

    if (isFull) {
      dom.gradeSummaryBanner.classList.add('correct');
      dom.gradeBannerIcon.innerHTML = '<i class="fa-solid fa-check text-success"></i>';
      dom.gradeBannerHeadline.textContent = 'Correct';
      dom.qStatusText.textContent = 'Finished (Correct)';
    } else if (isPartial) {
      dom.gradeSummaryBanner.classList.add('partiallycorrect');
      dom.gradeBannerIcon.innerHTML = '<i class="fa-solid fa-circle-half-stroke text-warning"></i>';
      dom.gradeBannerHeadline.textContent = 'Partially Correct';
      dom.qStatusText.textContent = 'Finished (Partially Correct)';
    } else {
      dom.gradeSummaryBanner.classList.add('incorrect');
      dom.gradeBannerIcon.innerHTML = '<i class="fa-solid fa-xmark text-danger"></i>';
      dom.gradeBannerHeadline.textContent = 'Incorrect';
      dom.qStatusText.textContent = 'Finished (Incorrect)';
    }

    dom.gradeBannerScore.textContent = `Mark ${score.toFixed(2)} out of 1.00`;
    dom.qPointsText.textContent = `Marked ${score.toFixed(2)} out of 1.00`;

    // 2. Specific Feedback
    let specificHtml = data.specificfeedback || '';
    const gradingAssets = data.gradingassets || {};
    specificHtml = replaceAssetUrls(specificHtml, gradingAssets);

    const prts = data.prts || {};
    const prtNames = Object.keys(prts);

    // Replace [[feedback:prtName]]
    for (const prtName of prtNames) {
      let prtHtml = prts[prtName] || '';
      prtHtml = replaceAssetUrls(prtHtml, gradingAssets);
      const prtRegex = new RegExp(`\\[\\[feedback:${prtName}\\]\\]`, 'g');

      if (prtRegex.test(specificHtml)) {
        specificHtml = specificHtml.replace(prtRegex, prtHtml);
      } else if (prtHtml.trim()) {
        // Append if not explicitly placed
        specificHtml += `<div class="prt-feedback-block prt-${prtName}">${prtHtml}</div>`;
      }
    }

    if (specificHtml.trim()) {
      dom.specificFeedbackContainer.style.display = 'block';
      dom.specificFeedbackBody.innerHTML = specificHtml;
      typeset(dom.specificFeedbackBody);
    } else {
      hideSpecificFeedback();
    }

    // 3. Update PRT Trace in Author Inspector
    renderInspectorPRT(data);

    typeset(dom.gradeSummaryBanner);
  }

  function hideGradeBanner() {
    dom.gradeSummaryBanner.style.display = 'none';
  }

  function hideSpecificFeedback() {
    dom.specificFeedbackContainer.style.display = 'none';
    dom.specificFeedbackBody.innerHTML = '';
  }

  // --- Hints Accordion ---
  function renderHints(hints) {
    if (hints && hints.length > 0) {
      dom.hintsAccordion.style.display = 'block';
      dom.hintsCount.textContent = hints.length;
      let html = '';
      hints.forEach((h, idx) => {
        html += `<div class="hint-item"><div class="hint-num font-mono text-muted">Hint ${idx + 1}:</div><div class="hint-body">${h}</div></div>`;
      });
      dom.hintsContent.innerHTML = html;
    } else {
      dom.hintsAccordion.style.display = 'none';
      dom.hintsContent.innerHTML = '';
    }
  }

  // --- General Feedback / Model Solution ---
  function renderGeneralFeedback(render, summary) {
    const solutionText = render.questionsamplesolutiontext || '';
    const noteText = render.questionnote || '';

    if (solutionText.trim() || noteText.trim()) {
      dom.generalFeedbackAccordion.style.display = 'block';
      dom.modelSolutionText.innerHTML = solutionText ? replaceAssetUrls(solutionText, render.questionassets) : '<em>No general feedback text</em>';
      dom.generalQuestionNote.innerHTML = noteText || '<em>No question note</em>';
    } else {
      dom.generalFeedbackAccordion.style.display = 'none';
    }
  }

  // --- Fill Model Answers ---
  function fillModelAnswers() {
    if (!state.questionData || !state.questionData.render) return;
    const inputsConfig = state.questionData.render.inputs || {};

    for (const [name, inputDef] of Object.entries(inputsConfig)) {
      const config = inputDef.configuration || {};
      const type = (config.type || 'algebraic').toLowerCase();
      const samples = inputDef.samplesolution || {};

      if (type === 'matrix') {
        for (const [cellKey, cellVal] of Object.entries(samples)) {
          let cellEl = dom.questionText.querySelector(`[name="${cellKey}"]`);
          if (!cellEl && cellKey.startsWith('_')) {
            cellEl = dom.questionText.querySelector(`[name="${name}${cellKey}"]`);
          }
          if (cellEl) cellEl.value = cellVal;
        }
      } else if (type === 'radio') {
        const val = samples[""] ?? samples[name];
        if (val !== undefined && val !== null) {
          const radio = dom.questionText.querySelector(`input[name="${name}"][value="${val}"]`);
          if (radio) radio.checked = true;
        }
      } else if (type === 'checkbox') {
        const sampleKeys = Object.keys(samples);
        const hasSubKeys = sampleKeys.some((k) => k.startsWith(`${name}_`) || k.startsWith('_'));
        if (hasSubKeys) {
          for (const [k, v] of Object.entries(samples)) {
            const optKey = k.startsWith(`${name}_`) ? k.slice(name.length + 1) : (k.startsWith('_') ? k.slice(1) : k);
            const cb = dom.questionText.querySelector(`input[name="${name}"][data-key="${optKey}"]`) || dom.questionText.querySelector(`input[name="${name}"][value="${optKey}"]`);
            if (cb) cb.checked = true;
          }
        } else {
          const val = samples[""] ?? samples[name] ?? '';
          const checkedValues = String(val).split(',').map((s) => s.trim());
          const checks = dom.questionText.querySelectorAll(`input[name="${name}"][type="checkbox"]`);
          checks.forEach((cb) => {
            cb.checked = checkedValues.includes(cb.value);
          });
        }
      } else if (type === 'dropdown') {
        const val = samples[""] ?? samples[name];
        const sel = dom.questionText.querySelector(`select[name="${name}"]`);
        if (sel && val !== undefined) sel.value = val;
      } else {
        const val = samples[""] ?? samples[name] ?? '';
        const el = dom.questionText.querySelector(`[name="${name}"]`);
        if (el) el.value = val;
      }

      // Trigger live validation
      validateSingleInput(name);
    }

    collectUserAnswers();
    showToast('Filled model answers (tans)', 'success');
  }

  // --- Reset Workbench ---
  function resetQuestionInputs() {
    state.userAnswers = {};
    state.lastGradedResult = null;
    hideGradeBanner();
    hideSpecificFeedback();
    dom.qStatusText.textContent = 'Not yet answered';
    dom.qPointsText.textContent = 'Marked out of 1.00';

    if (state.questionData) {
      renderQuestion(state.questionData);
    }
    showToast('Reset inputs', 'info');
  }

  // --- Deploy 50 Seeds ---
  async function deploy50Seeds() {
    if (!state.activePath) return;
    dom.btnDeploySeeds.disabled = true;

    try {
      showToast('Deploying 50 seeds...', 'info');
      const res = await fetch('/api/deploy-seeds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: state.activePath,
          count: 50
        })
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      showToast(`Successfully deployed ${data.count || 50} seeds to XML!`, 'success');

      // Refresh question list and current question
      await loadQuestions(true);
      if (data.seeds && data.seeds.length > 0) {
        await selectQuestion(state.activePath, data.seeds[0]);
      } else {
        await selectQuestion(state.activePath);
      }
    } catch (err) {
      console.error('[macstack] Deploy seeds error:', err);
      showToast(`Deploy seeds failed: ${err.message}`, 'error');
    } finally {
      dom.btnDeploySeeds.disabled = false;
    }
  }

  // --- Run Question Tests (<qtest>) ---
  async function runAllTests() {
    if (!state.activePath) return;
    dom.btnRunTests.disabled = true;
    dom.btnRunTests.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Running Tests...';

    try {
      const res = await fetch('/api/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: state.activePath })
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      renderTestResults(data);
    } catch (err) {
      console.error('[macstack] Test run error:', err);
      dom.testsResultsContainer.innerHTML = `<div class="error-banner">Test run failed: ${escapeHtml(err.message)}</div>`;
    } finally {
      dom.btnRunTests.disabled = false;
      dom.btnRunTests.innerHTML = '<i class="fa-solid fa-play"></i> Run All Tests';
    }
  }

  function renderTestResults(data) {
    const results = data.results || data || {};
    const seeds = Object.keys(results);

    let totalCases = 0;
    let passedCases = 0;
    let failedCases = 0;

    let html = '';

    for (const seed of seeds) {
      const seedResults = results[seed];
      if (!Array.isArray(seedResults)) continue;

      let seedHtml = `
        <div class="test-seed-block">
          <div class="test-seed-header">
            <span><i class="fa-solid fa-seedling"></i> Seed ${escapeHtml(seed)}</span>
            <span>${seedResults.length} test case(s)</span>
          </div>
      `;

      for (let i = 0; i < seedResults.length; i++) {
        const t = seedResults[i];
        totalCases++;
        const passed = t.passed === true || t.pass === true;
        if (passed) passedCases++;
        else failedCases++;

        const badgeClass = passed ? 'badge-seeds' : 'badge-error';
        const icon = passed ? 'fa-check text-success' : 'fa-xmark text-danger';

        seedHtml += `
          <div class="test-case-row">
            <div>
              <span class="font-mono font-bold">Case #${i + 1}</span>
              <span class="text-muted" style="margin-left: 8px;">Score: ${t.score !== undefined ? t.score : '—'}</span>
              ${t.answernotes ? `<span class="answernote-chip" style="margin-left:6px;">${escapeHtml(Array.isArray(t.answernotes) ? t.answernotes.join(', ') : t.answernotes)}</span>` : ''}
            </div>
            <div>
              <i class="fa-solid ${icon}"></i>
            </div>
          </div>
        `;
      }

      seedHtml += '</div>';
      html += seedHtml;
    }

    if (totalCases === 0) {
      dom.testsResultsContainer.innerHTML = `<div class="placeholder-empty">No tests returned for this question.</div>`;
      dom.testsSummaryBanner.style.display = 'none';
      return;
    }

    dom.testsSummaryBanner.style.display = 'flex';
    if (failedCases === 0) {
      dom.testsSummaryBanner.className = 'tests-summary passed';
      dom.testsSummaryStatus.innerHTML = `<i class="fa-solid fa-circle-check"></i> All ${totalCases} test cases PASSED across ${seeds.length} seed(s)`;
    } else {
      dom.testsSummaryBanner.className = 'tests-summary failed';
      dom.testsSummaryStatus.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> ${failedCases} of ${totalCases} test cases FAILED across ${seeds.length} seed(s)`;
    }

    dom.testsResultsContainer.innerHTML = html;
  }

  // --- Inspector Tabs Renderers ---
  function renderInspectorVars(vars) {
    const variables = vars.variables || [];
    dom.varsCountLabel.textContent = `${variables.length} variable${variables.length === 1 ? '' : 's'}`;

    if (variables.length === 0) {
      dom.varsTbody.innerHTML = `<tr><td colspan="3" class="table-empty">No variables evaluated</td></tr>`;
    } else {
      let rowsHtml = '';
      for (const v of variables) {
        rowsHtml += `
          <tr>
            <td><code class="font-bold">${escapeHtml(v.name)}</code></td>
            <td><code>${escapeHtml(String(v.value !== undefined ? v.value : v.expr || ''))}</code></td>
            <td>\\(${v.display || v.value || ''}\\)</td>
          </tr>
        `;
      }
      dom.varsTbody.innerHTML = rowsHtml;
    }

    // Question Note
    dom.inspectorQuestionNote.innerHTML = vars.questionnote || '<em>None</em>';

    // Errors
    if (vars.errors && vars.errors.trim()) {
      dom.varsErrorsContainer.style.display = 'block';
      dom.varsErrorsText.textContent = vars.errors;
    } else {
      dom.varsErrorsContainer.style.display = 'none';
      dom.varsErrorsText.textContent = '';
    }

    typeset([dom.varsTbody, dom.inspectorQuestionNote]);
  }

  function renderInspectorLint(lint) {
    dom.lintCountLabel.textContent = `${lint.length} issue${lint.length === 1 ? '' : 's'}`;
    if (lint.length > 0) {
      dom.lintBadge.style.display = 'inline-block';
      dom.lintBadge.textContent = lint.length;
    } else {
      dom.lintBadge.style.display = 'none';
    }

    if (lint.length === 0) {
      dom.lintList.innerHTML = `<div class="placeholder-empty"><i class="fa-solid fa-check text-success"></i> No lint issues found. Clean!</div>`;
      return;
    }

    let html = '';
    for (const item of lint) {
      const sev = (item.severity || 'info').toLowerCase();
      let icon = 'fa-info-circle';
      if (sev === 'error') icon = 'fa-circle-xmark';
      else if (sev === 'warning') icon = 'fa-triangle-exclamation';

      html += `
        <div class="diagnostic-item ${sev}">
          <div class="diag-header">
            <span class="diag-code"><i class="fa-solid ${icon}"></i> ${escapeHtml(item.code || sev)}</span>
            <span class="diag-field">${escapeHtml(item.field || '')}</span>
          </div>
          <div class="diag-message">${escapeHtml(item.message || '')}</div>
        </div>
      `;
    }

    dom.lintList.innerHTML = html;
  }

  function renderInspectorPRT(gradeData) {
    if (!gradeData || !gradeData.prtresults) {
      dom.prtStatusLabel.textContent = 'Awaiting submission';
      dom.prtBadge.style.display = 'none';
      dom.prtTraceList.innerHTML = `<div class="placeholder-empty">Submit an answer to view PRT grading trace and answer notes.</div>`;
      return;
    }

    const prtResults = gradeData.prtresults;
    const prtNames = Object.keys(prtResults);
    dom.prtBadge.style.display = 'inline-block';
    dom.prtBadge.textContent = prtNames.length;
    dom.prtStatusLabel.textContent = `${prtNames.length} PRT(s) evaluated`;

    let html = '';
    for (const name of prtNames) {
      const res = prtResults[name];
      const score = typeof res.score === 'number' ? res.score : (gradeData.scores ? gradeData.scores[name] : 0);
      const penalty = res.penalty || 0;
      const notes = res.answernotes || [];

      let chipsHtml = '';
      if (Array.isArray(notes)) {
        for (const n of notes) {
          const isTrue = n.endsWith('-T');
          const isFalse = n.endsWith('-F');
          const chipClass = isTrue ? 'true-branch' : isFalse ? 'false-branch' : '';
          chipsHtml += `<span class="answernote-chip ${chipClass}">${escapeHtml(n)}</span>`;
        }
      }

      html += `
        <div class="prt-card">
          <div class="prt-card-header">
            <span class="prt-name">${escapeHtml(name)}</span>
            <div class="prt-metrics">
              <span class="badge ${score >= 0.99 ? 'badge-seeds' : 'badge-error'}">Score: ${score}</span>
              <span class="badge badge-seeds">Penalty: ${penalty}</span>
            </div>
          </div>
          <div class="prt-answernotes">
            ${chipsHtml || '<span class="text-subtle font-mono text-xs">No answer notes recorded</span>'}
          </div>
          ${res.errors ? `<div class="error-banner mt-3 font-mono text-xs">${escapeHtml(res.errors)}</div>` : ''}
        </div>
      `;
    }

    dom.prtTraceList.innerHTML = html;
  }

  function renderInspectorTestsInitial(testCount) {
    if (testCount > 0) {
      dom.testsBadge.style.display = 'inline-block';
      dom.testsBadge.textContent = testCount;
      dom.testsResultsContainer.innerHTML = `
        <div class="placeholder-empty">
          <i class="fa-solid fa-vial"></i> Question defines ${testCount} authoring test case(s).<br>
          Click "Run All Tests" above to verify pass rates across variants.
        </div>
      `;
    } else {
      dom.testsBadge.style.display = 'none';
      dom.testsResultsContainer.innerHTML = `
        <div class="placeholder-empty">
          <i class="fa-solid fa-triangle-exclamation text-warning"></i> No &lt;qtest&gt; cases defined in XML yet.<br>
          Add test cases using <code>macstack add-test</code>.
        </div>
      `;
    }
  }

  // --- SSE Live-Reload Integration ---
  function initEventSource() {
    if (state.eventSource) {
      state.eventSource.close();
    }

    const es = new EventSource('/api/events');
    state.eventSource = es;

    es.onopen = () => {
      dom.connectionStatus.className = 'status-badge connected';
      dom.connectionStatus.querySelector('.status-text').textContent = 'Live Reload';
    };

    es.onerror = () => {
      dom.connectionStatus.className = 'status-badge reconnecting';
      dom.connectionStatus.querySelector('.status-text').textContent = 'Reconnecting...';
    };

    const handleReload = async (evt) => {
      console.log('[macstack] Live reload event received:', evt.data);
      showToast('Live Reloaded from disk', 'reload', 2500);

      // Save user inputs currently in DOM
      const preservedAnswers = collectUserAnswers();
      const wasGraded = state.lastGradedResult !== null;

      // Reload questions list (diagnostics/seeds may have changed)
      await loadQuestions(true);

      // Re-fetch current question
      if (state.activePath) {
        await selectQuestion(state.activePath, state.activeSeed);

        // Restore user answers
        state.userAnswers = preservedAnswers;
        restoreUserAnswers(state.questionData?.render?.inputs || {});

        // Re-validate filled inputs
        for (const inputName of Object.keys(state.questionData?.render?.inputs || {})) {
          validateSingleInput(inputName);
        }

        // If previously graded, re-grade automatically
        if (wasGraded && Object.keys(preservedAnswers).length > 0) {
          await gradeCurrentAnswers();
        }
      }
    };

    es.addEventListener('reload', handleReload);
    es.addEventListener('message', (evt) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.event === 'reload' || data.paths) {
          handleReload(evt);
        }
      } catch (e) {
        // Not JSON, ignore or trigger reload
      }
    });
  }

  // --- Initialize App & Event Listeners ---
  function init() {
    initTheme();
    initAccordions();
    initInspectorTabs();

    // Sidebar search filter
    dom.questionSearch.addEventListener('input', () => {
      renderQuestionsList();
    });

    // Toolbar buttons
    dom.btnRollSeed.addEventListener('click', () => {
      const randomSeed = Math.floor(Math.random() * 90000) + 10000;
      selectQuestion(state.activePath, randomSeed);
      showToast(`Rolled seed ${randomSeed}`, 'info');
    });

    dom.btnApplySeed.addEventListener('click', () => {
      const val = parseInt(dom.customSeedInput.value, 10);
      if (!isNaN(val)) {
        selectQuestion(state.activePath, val);
        showToast(`Set seed ${val}`, 'info');
      }
    });

    dom.customSeedInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const val = parseInt(dom.customSeedInput.value, 10);
        if (!isNaN(val)) {
          selectQuestion(state.activePath, val);
          showToast(`Set seed ${val}`, 'info');
        }
      }
    });

    dom.seedSelect.addEventListener('change', () => {
      const val = dom.seedSelect.value;
      if (val) {
        selectQuestion(state.activePath, parseInt(val, 10));
      }
    });

    dom.btnFillCorrect.addEventListener('click', fillModelAnswers);
    dom.btnFillCorrectInline.addEventListener('click', fillModelAnswers);

    dom.btnCheckAnswer.addEventListener('click', gradeCurrentAnswers);
    dom.btnCheckAnswerInline.addEventListener('click', gradeCurrentAnswers);

    dom.btnReset.addEventListener('click', resetQuestionInputs);

    dom.btnDeploySeeds.addEventListener('click', deploy50Seeds);
    dom.btnRunTests.addEventListener('click', runAllTests);

    // Initial data load
    loadQuestions(false);

    // Start SSE listener
    initEventSource();
  }

  // Bootstrap when DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
