/**
 * app.js – BruteScope Dashboard
 * Groupe 20 – Master 1 Informatique, UNIKIN 2026
 *
 * Responsabilités :
 *  - Connexion SSE au backend Flask (/stream)
 *  - Appels API REST (/api/start, /api/stop, /api/stats, /api/wordlists)
 *  - Mise à jour du Live Feed, des statistiques et du graphique Chart.js
 *  - Gestion de l'état de l'interface
 */

'use strict';

// ═══════════════════════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════════════════════

const API_BASE = '';          // Vide : même origine (nginx proxy)
const CHART_MAX_POINTS = 60; // Garder 60 secondes dans le graphique
const FEED_MAX_ROWS    = 250; // Nombre max de lignes dans le live feed

/** Tailles approximatives des wordlists pour la barre de progression */
const WORDLIST_SIZES = {
  'common.txt':       50,
  'rockyou_mini.txt': 155,
};

// ═══════════════════════════════════════════════════════════════════════════════
// ÉTAT DE L'APPLICATION
// ═══════════════════════════════════════════════════════════════════════════════

const state = {
  running:      false,
  startTime:    null,
  total:        0,
  success:      0,
  failed:       0,
  feedCount:    0,
  lastTotal:    0,           // pour calculer le débit seconde par seconde
  evtSource:    null,        // instance EventSource SSE
  timerHandle:  null,        // setInterval pour le timer affiché
  chartHandle:  null,        // setInterval pour le graphique
  rateBuffer:   [],          // historique des débits
};

// ═══════════════════════════════════════════════════════════════════════════════
// RÉFÉRENCES DOM
// ═══════════════════════════════════════════════════════════════════════════════

const dom = {
  // Status bar
  dot:          document.getElementById('statusDot'),
  statusText:   document.getElementById('statusText'),
  apiStatus:    document.getElementById('apiStatus'),

  // Config
  targetIp:     document.getElementById('targetIp'),
  targetPort:   document.getElementById('targetPort'),
  loginUrl:     document.getElementById('loginUrl'),
  username:     document.getElementById('username'),
  wordlist:     document.getElementById('wordlist'),
  failString:   document.getElementById('failString'),
  threads:      document.getElementById('threads'),
  threadsVal:   document.getElementById('threadsVal'),

  // Buttons
  startBtn:     document.getElementById('startBtn'),
  stopBtn:      document.getElementById('stopBtn'),
  clearBtn:     document.getElementById('clearBtn'),

  // Alert
  alertBox:     document.getElementById('alertBox'),

  // Hydra cmd preview
  hydraCmd:     document.getElementById('hydraCmd'),

  // Stats
  sTotal:       document.getElementById('sTotal'),
  sSuccess:     document.getElementById('sSuccess'),
  sRate:        document.getElementById('sRate'),
  sElapsed:     document.getElementById('sElapsed'),
  statSuccess:  document.getElementById('statSuccess'),

  // Progress
  progressFill: document.getElementById('progressFill'),
  progressPct:  document.getElementById('progressPct'),
  progressLabel:document.getElementById('progressLabel'),

  // Chart
  rateChart:    document.getElementById('rateChart'),

  // Feed
  feedBody:     document.getElementById('feedBody'),
  feedCount:    document.getElementById('feedCount'),

  // Success panel
  successList:  document.getElementById('successList'),
};

// ═══════════════════════════════════════════════════════════════════════════════
// GRAPHIQUE CHART.JS
// ═══════════════════════════════════════════════════════════════════════════════

const chart = new Chart(dom.rateChart.getContext('2d'), {
  type: 'line',
  data: {
    labels: [],
    datasets: [
      {
        label: 'Tentatives/sec',
        data: [],
        borderColor: '#00b4d8',
        backgroundColor: 'rgba(0,180,216,0.07)',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.4,
        fill: true,
      },
      {
        label: 'Succès cumulés',
        data: [],
        borderColor: '#00f5a0',
        backgroundColor: 'rgba(0,245,160,0.04)',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.3,
        fill: true,
        yAxisID: 'yRight',
      },
    ],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 0 },
    interaction: { mode: 'index', intersect: false },
    scales: {
      x: { display: false },
      y: {
        min: 0,
        position: 'left',
        grid: { color: 'rgba(26,48,80,.5)' },
        ticks: { color: '#5a7a90', font: { size: 10, family: 'Share Tech Mono' } },
      },
      yRight: {
        min: 0,
        position: 'right',
        grid: { drawOnChartArea: false },
        ticks: { color: '#00f5a0', font: { size: 10, family: 'Share Tech Mono' } },
      },
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#0d1b2a',
        borderColor: '#1a3050',
        borderWidth: 1,
        titleFont: { family: 'Share Tech Mono', size: 11 },
        bodyFont:  { family: 'Share Tech Mono', size: 10 },
      },
    },
  },
});

// ═══════════════════════════════════════════════════════════════════════════════
// UTILITAIRES
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Affiche un message d'alerte stylé qui disparaît après un délai.
 * @param {string} msg   – Texte du message
 * @param {'success'|'error'|'warn'} type
 */
function showAlert(msg, type = 'warn') {
  dom.alertBox.textContent = msg;
  dom.alertBox.className   = `alert show alert-${type}`;
  clearTimeout(dom.alertBox._timeout);
  dom.alertBox._timeout = setTimeout(() => {
    dom.alertBox.className = 'alert';
  }, 5000);
}

/**
 * Met à jour la commande Hydra affichée en fonction des inputs.
 */
function refreshHydraCmd() {
  const ip      = dom.targetIp.value   || 'target';
  const port    = dom.targetPort.value || '8080';
  const url     = dom.loginUrl.value   || '/login';
  const user    = dom.username.value   || 'admin';
  const wl      = (dom.wordlist.value  || 'common.txt').split('/').pop();
  const fail    = dom.failString.value || 'Invalid credentials';
  const threads = dom.threads.value    || '4';

  dom.hydraCmd.textContent =
    `hydra -l ${user} -P ${wl} \\\n` +
    `      ${ip} -s ${port} \\\n` +
    `      http-post-form \\\n` +
    `      "${url}:username=^USER^&password=^PASS^:1=:F=${fail}" \\\n` +
    `      -V -t ${threads} -f`;
}

/**
 * Formate une durée en secondes sous la forme "1m 23s" ou "45s".
 */
function formatElapsed(seconds) {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

// ═══════════════════════════════════════════════════════════════════════════════
// CONTRÔLE DE L'ATTAQUE
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Démarre une session d'attaque.
 * En production, appelle POST /api/start.
 * En mode démo (pas d'API), simule les résultats localement.
 */
async function startAttack() {
  const ip = dom.targetIp.value.trim();
  if (!ip) { showAlert('⚠️ IP cible requise.', 'error'); return; }
  if (state.running) return;

  // Réinitialiser l'état
  Object.assign(state, {
    running: true, startTime: Date.now(),
    total: 0, success: 0, failed: 0,
    feedCount: 0, lastTotal: 0, rateBuffer: [],
  });

  // UI → état "en cours"
  dom.startBtn.disabled = true;
  dom.stopBtn.disabled  = false;
  dom.dot.className     = 'dot active';
  dom.statusText.textContent = 'EN COURS';
  dom.feedBody.innerHTML = '';
  dom.successList.innerHTML  = '<span class="empty-msg">Recherche en cours…</span>';
  dom.statSuccess.classList.remove('success-glow');

  // Démarrer le timer et le graphique
  state.timerHandle = setInterval(tickTimer,  500);
  state.chartHandle = setInterval(tickChart, 1000);

  // ── Tentative d'appel API réel ────────────────────────────────────────────
  const config = {
    target_ip:   ip,
    port:        parseInt(dom.targetPort.value) || 8080,
    login_url:   dom.loginUrl.value  || '/login',
    username:    dom.username.value  || 'admin',
    wordlist:    dom.wordlist.value  || 'common.txt',
    fail_string: dom.failString.value || 'Invalid credentials',
    threads:     parseInt(dom.threads.value) || 4,
  };

  try {
    const resp = await fetch(`${API_BASE}/api/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
      signal: AbortSignal.timeout(3000),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    const started = await resp.json();
    if (started.config) {
      dom.targetIp.value = started.config.target_ip || dom.targetIp.value;
      dom.targetPort.value = started.config.port || dom.targetPort.value;
      refreshHydraCmd();
    }

    // Connexion SSE au vrai backend
    connectSSE();
    dom.apiStatus.textContent = 'CONNECTÉ';
    dom.apiStatus.style.color = 'var(--green)';
    showAlert('▶ Session démarrée – connecté au backend.', 'success');

  } catch (e) {
    // Mode démo : l'API n'est pas disponible, on simule localement
    console.warn('API indisponible – mode démo local :', e.message);
    dom.apiStatus.textContent = 'DÉMO';
    dom.apiStatus.style.color = 'var(--amber)';
    showAlert('▶ Mode démo – simulation locale (API non disponible).', 'warn');
    startLocalSimulation(config);
  }
}

/**
 * Arrête la session en cours.
 */
async function stopAttack(auto = false) {
  if (!state.running) return;
  state.running = false;

  clearInterval(state.timerHandle);
  clearInterval(state.chartHandle);

  if (state.evtSource) { state.evtSource.close(); state.evtSource = null; }
  clearInterval(state._simHandle);

  // Appel API stop (best-effort)
  fetch(`${API_BASE}/api/stop`, { method: 'POST' }).catch(() => {});

  dom.startBtn.disabled = false;
  dom.stopBtn.disabled  = true;
  dom.dot.className     = 'dot idle';
  dom.statusText.textContent = auto ? 'TERMINÉ' : 'ARRÊTÉ';

  if (!auto) showAlert('■ Session arrêtée.', 'warn');
}

/**
 * Réinitialise tout l'interface.
 */
function clearAll() {
  stopAttack();
  Object.assign(state, { total:0, success:0, failed:0, feedCount:0, rateBuffer:[] });

  dom.sTotal.textContent   = '0';
  dom.sSuccess.textContent = '0';
  dom.sRate.textContent    = '0.0';
  dom.sElapsed.textContent = '0s';
  dom.progressFill.style.width = '0%';
  dom.progressPct.textContent  = '0%';
  dom.feedBody.innerHTML       = '';
  dom.feedCount.textContent    = '0 entrées';
  dom.successList.innerHTML    = '<span class="empty-msg">Aucun succès pour le moment…</span>';
  dom.dot.className     = 'dot';
  dom.statusText.textContent = 'INACTIF';
  dom.statSuccess.classList.remove('success-glow');

  chart.data.labels = [];
  chart.data.datasets.forEach(d => (d.data = []));
  chart.update();
}

// ═══════════════════════════════════════════════════════════════════════════════
// SSE – CONNEXION AU BACKEND
// ═══════════════════════════════════════════════════════════════════════════════

function connectSSE() {
  if (state.evtSource) state.evtSource.close();

  state.evtSource = new EventSource(`${API_BASE}/stream`);

  state.evtSource.onmessage = (e) => {
    let data;
    try { data = JSON.parse(e.data); } catch { return; }
    if (data.ping) return;
    if (data.done) { stopAttack(true); return; }
    if (data.error) { showAlert('❌ ' + data.message, 'error'); return; }
    processResult(data);
  };

  state.evtSource.onerror = () => {
    console.warn('SSE : connexion perdue.');
    if (state.running) showAlert('⚠️ Connexion SSE interrompue.', 'warn');
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// SIMULATION LOCALE (DÉMO SANS BACKEND)
// ═══════════════════════════════════════════════════════════════════════════════

const DEMO_WORDLIST = [
  '123456','password','12345678','qwerty','123123','admin',
  'letmein','welcome','monkey','dragon','master','login',
  'abc123','pass1','sunshine','princess','michael','shadow',
  'superman','batman','iloveyou','trustno1','football','starwars',
  'hello','charlie','donald','soccer','ashley','1234567',
  '123456789','1234','12345','111111','000000','passw0rd',
  'admin123',   // ← mot de passe cible (position 36)
  'root','toor','test','guest',
];

function startLocalSimulation(config) {
  let idx = 0;
  const interval = Math.max(60, 400 / (config.threads || 4));
  const target = 'admin123';

  state._simHandle = setInterval(() => {
    if (!state.running || idx >= DEMO_WORDLIST.length) {
      clearInterval(state._simHandle);
      stopAttack(true);
      return;
    }

    // Simuler N tentatives selon les threads
    for (let t = 0; t < (config.threads || 4) && idx < DEMO_WORDLIST.length; t++, idx++) {
      const pw = DEMO_WORDLIST[idx];
      const ok = pw === target;
      processResult({
        timestamp: new Date().toISOString().replace('T', ' ').slice(0, 19),
        username:  config.username,
        password:  pw,
        success:   ok,
      });
      if (ok) {
        clearInterval(state._simHandle);
        setTimeout(() => stopAttack(true), 800);
        return;
      }
    }
  }, interval);
}

// ═══════════════════════════════════════════════════════════════════════════════
// TRAITEMENT DES RÉSULTATS
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Traite un résultat d'authentification et met à jour toute l'interface.
 * @param {{ timestamp, username, password, success }} data
 */
function processResult(data) {
  state.total++;
  if (data.success) {
    state.success++;
    dom.statSuccess.classList.add('success-glow');
    addSuccessEntry(data);
    showAlert(
      `🔑 MOT DE PASSE TROUVÉ !  login: ${data.username}  /  password: ${data.password}`,
      'success'
    );
  } else {
    state.failed++;
  }

  // Compteurs
  dom.sTotal.textContent   = state.total;
  dom.sSuccess.textContent = state.success;
  state.feedCount++;
  dom.feedCount.textContent = state.feedCount + ' entrées';

  // Ligne dans le feed
  addFeedRow(data);

  // Progression (basée sur la taille estimée de la wordlist)
  const wl   = (dom.wordlist.value || 'common.txt').split('/').pop();
  const size  = WORDLIST_SIZES[wl] || 1000;
  const pct   = Math.min(100, Math.round((state.total / size) * 100));
  dom.progressFill.style.width = pct + '%';
  dom.progressPct.textContent  = pct + '%';
}

// ─── Ajout d'une ligne dans le tableau Live Feed ─────────────────────────────
function addFeedRow(data) {
  const tr = document.createElement('tr');
  tr.className = data.success ? 'success-row' : 'failed-row';
  tr.innerHTML = `
    <td>${state.total}</td>
    <td>${data.timestamp}</td>
    <td>${escapeHtml(data.username)}</td>
    <td><span style="color:${data.success ? 'var(--green)' : 'var(--text)'}">${escapeHtml(data.password)}</span></td>
    <td>${data.success ? '✓ SUCCÈS !' : '✗ Échec'}</td>
  `;
  dom.feedBody.insertBefore(tr, dom.feedBody.firstChild);

  // Limiter la taille du tableau
  while (dom.feedBody.children.length > FEED_MAX_ROWS) {
    dom.feedBody.removeChild(dom.feedBody.lastChild);
  }
}

// ─── Ajout d'un credential trouvé ────────────────────────────────────────────
function addSuccessEntry(data) {
  // Supprimer le message vide
  const empty = dom.successList.querySelector('.empty-msg');
  if (empty) empty.remove();

  const div = document.createElement('div');
  div.className = 'cred-entry';
  div.innerHTML = `
    <span class="cred-ts">${data.timestamp}</span>
    <span class="cred-key">login</span> : <span class="cred-val">${escapeHtml(data.username)}</span>
    &nbsp;&nbsp;
    <span class="cred-key">password</span> : <span class="cred-val">${escapeHtml(data.password)}</span>
  `;
  dom.successList.prepend(div);
}

// ═══════════════════════════════════════════════════════════════════════════════
// TICKERS (Timer + Graphique)
// ═══════════════════════════════════════════════════════════════════════════════

function tickTimer() {
  if (!state.startTime) return;
  const elapsed = Math.round((Date.now() - state.startTime) / 1000);
  dom.sElapsed.textContent = formatElapsed(elapsed);
  const rate = elapsed > 0 ? (state.total / elapsed).toFixed(1) : '0.0';
  dom.sRate.textContent = rate;
}

function tickChart() {
  const delta = state.total - state.lastTotal;
  state.lastTotal = state.total;
  state.rateBuffer.push(delta);
  if (state.rateBuffer.length > CHART_MAX_POINTS) state.rateBuffer.shift();

  const labels = state.rateBuffer.map((_, i) => i.toString());
  chart.data.labels = labels;
  chart.data.datasets[0].data = [...state.rateBuffer];
  chart.data.datasets[1].data = labels.map(() => state.success || null);
  chart.update('none');
}

// ═══════════════════════════════════════════════════════════════════════════════
// INITIALISATION
// ═══════════════════════════════════════════════════════════════════════════════

/** Échappe le HTML pour éviter l'injection de balises dans le DOM. */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Vérifie si l'API est disponible au démarrage. */
async function checkApiStatus() {
  try {
    const r = await fetch(`${API_BASE}/api/status`, { signal: AbortSignal.timeout(2000) });
    if (r.ok) {
      const status = await r.json();
      if (status.default_target && !dom.targetIp.dataset.userEdited) {
        dom.targetIp.value = status.default_target;
      }
      if (status.default_port && !dom.targetPort.dataset.userEdited) {
        dom.targetPort.value = status.default_port;
      }
      refreshHydraCmd();
      dom.apiStatus.textContent  = 'EN LIGNE';
      dom.apiStatus.style.color  = 'var(--green)';
    }
  } catch {
    dom.apiStatus.textContent = 'HORS LIGNE (démo)';
    dom.apiStatus.style.color = 'var(--amber)';
  }
}

/** Charge les wordlists disponibles depuis l'API et remplit le <select>. */
async function loadWordlists() {
  try {
    const r = await fetch(`${API_BASE}/api/wordlists`, { signal: AbortSignal.timeout(2000) });
    if (!r.ok) return;
    const lists = await r.json();
    dom.wordlist.innerHTML = '';
    lists.forEach(({ name, entries }) => {
      const opt = document.createElement('option');
      opt.value       = name;
      opt.textContent = `${name} (${entries.toLocaleString()} entrées)`;
      dom.wordlist.appendChild(opt);
    });
  } catch {
    // Conserver les options statiques par défaut
  }
}

// ─── Écoute des inputs pour mettre à jour la commande Hydra ──────────────────
['targetIp','targetPort','loginUrl','username','wordlist','failString','threads'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('input', () => {
    el.dataset.userEdited = 'true';
    refreshHydraCmd();
  });
});

dom.threads.addEventListener('input', () => {
  dom.threadsVal.textContent = dom.threads.value;
});

// Exposer les fonctions au HTML (onclick="...")
window.startAttack = startAttack;
window.stopAttack  = () => stopAttack(false);
window.clearAll    = clearAll;

// ─── Boot ─────────────────────────────────────────────────────────────────────
(async () => {
  refreshHydraCmd();
  await checkApiStatus();
  await loadWordlists();
  console.info('BruteScope Dashboard initialisé – Groupe 20, UNIKIN 2026');
})();
