(() => {
  const RM = matchMedia('(prefers-reduced-motion: reduce)').matches, FINE = matchMedia('(pointer: fine)').matches;
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement; let px = 0, py = 0;

  // stagger index for the load sequence
  ['.side-column .panel', '.pricing-card', '.guide-card', '.admin-stat-card'].forEach(s => $$(s).forEach((e, i) => e.style.setProperty('--i', i)));

  // aurora blobs + twinkling pixel sky with shooting stars
  ['a', 'b'].forEach(k => { const d = document.createElement('div'); d.className = 'fx-blob ' + k; document.body.append(d); });
  const cv = document.createElement('canvas'); cv.id = 'fx-sky'; document.body.append(cv);
  const g = cv.getContext('2d'); let W, H, stars = [], sh = null, t = 0;
  const size = () => { W = cv.width = innerWidth; H = cv.height = innerHeight;
    stars = Array.from({ length: Math.round(W * H / 16000) }, () => ({ x: Math.random() * W | 0, y: Math.random() * H * .7 | 0, s: Math.random() < .2 ? 3 : 2, p: Math.random() * 6.3, v: .5 + Math.random() * 1.5 })); };
  const draw = () => { t += .016; g.clearRect(0, 0, W, H);
    for (const s of stars) { g.fillStyle = `rgba(255,244,236,${RM ? .7 : .3 + .7 * Math.abs(Math.sin(t * s.v + s.p))})`; g.fillRect((s.x + px * 8 * s.s / 2) | 0, (s.y + py * 5 * s.s / 2) | 0, s.s, s.s); }
    if (!sh && Math.random() < .003) sh = { x: Math.random() * W * .8, y: Math.random() * H * .3, l: 0 };
    if (sh) { sh.x += 9; sh.y += 4; sh.l++; for (let i = 0; i < 14; i++) { g.fillStyle = `rgba(255,224,168,${1 - i / 14})`; g.fillRect((sh.x - i * 9) / 3 * 3 | 0, (sh.y - i * 4) / 3 * 3 | 0, 3, 3); } if (sh.l > 60) sh = null; }
    if (!RM) requestAnimationFrame(draw); };
  addEventListener('resize', size); size(); draw();

  // mouse parallax
  if (!RM) addEventListener('pointermove', e => { px = e.clientX / innerWidth * 2 - 1; py = e.clientY / innerHeight * 2 - 1;
    root.style.setProperty('--px', px.toFixed(3)); root.style.setProperty('--py', py.toFixed(3)); }, { passive: true });

  // pixel cursor trail (native cursor stays visible)
  if (FINE && !RM) { let mx = -99, my = -99;
    const dots = Array.from({ length: 8 }, (_, i) => { const d = document.createElement('i'); d.className = 'fx-trail'; d.style.setProperty('--i', i); document.body.append(d); return { d, x: 0, y: 0 }; });
    addEventListener('pointermove', e => { mx = e.clientX; my = e.clientY; }, { passive: true });
    (function l() { let x = mx, y = my; dots.forEach((o, i) => { o.x += (x - o.x) * (.5 - i * .04); o.y += (y - o.y) * (.5 - i * .04);
      o.d.style.transform = `translate(${Math.round(o.x / 4) * 4}px,${Math.round(o.y / 4) * 4}px)`; x = o.x; y = o.y; }); requestAnimationFrame(l); })(); }

  // 3D tilt on pricing cards, magnetic buttons
  if (FINE && !RM) {
    $$('.pricing-card').forEach(c => { c.classList.add('fx-tilt');
      c.addEventListener('pointermove', e => { const r = c.getBoundingClientRect(); c.style.setProperty('--ry', ((e.clientX - r.left) / r.width - .5) * 8 + 'deg'); c.style.setProperty('--rx', -((e.clientY - r.top) / r.height - .5) * 8 + 'deg'); });
      c.addEventListener('pointerleave', () => { c.style.setProperty('--rx', '0deg'); c.style.setProperty('--ry', '0deg'); }); });
    $$('.btn-hero-primary,.btn-hero-secondary,.btn-primary,.auth-submit-btn,.card-btn').forEach(b => {
      b.addEventListener('pointermove', e => { const r = b.getBoundingClientRect(); b.style.translate = `${(e.clientX - r.left - r.width / 2) * .12}px ${(e.clientY - r.top - r.height / 2) * .18}px`; });
      b.addEventListener('pointerleave', () => { b.style.translate = ''; }); });
  }

  // ring borders, moon logo, hamburger
  try { $$('.auth-card,.pricing-card:has(.featured-ribbon),.panel-playground').forEach(c => { const i = document.createElement('i'); i.className = 'fx-ring'; c.append(i); if (getComputedStyle(c).position === 'static') c.style.position = 'relative'; }); } catch (e) {}
  $$('.brand-name').forEach(n => { const m = document.createElement('i'); m.className = 'fx-moon'; n.append(m); });
  const nc = $('.nav-controls'), nb = $('.nav-container');
  if (nc && nb) { const b = document.createElement('button'); b.className = 'fx-burger'; b.setAttribute('aria-label', 'Menu'); b.setAttribute('aria-expanded', 'false'); b.innerHTML = '<i></i><i></i><i></i>'; nb.insertBefore(b, nc);
    b.onclick = () => { const o = nc.classList.toggle('fx-open'); b.setAttribute('aria-expanded', o); b.classList.toggle('on', o); }; }

  // count-up hero metrics
  if (!RM) $$('.metric-num').forEach(el => { const m = el.textContent.match(/(\d+(?:\.\d+)?)/); if (!m || m[1] === '0') return;
    const end = parseFloat(m[1]), dp = (m[1].split('.')[1] || '').length, tpl = el.textContent; let f = 0;
    const run = () => { f++; el.textContent = tpl.replace(m[1], (end * Math.min(1, f / 24)).toFixed(dp)); if (f < 24) setTimeout(run, 45); }; setTimeout(run, 1100); });

  // console: syntax colors + loading state
  const out = $('#console-output'), btn = $('#btn-run'), box = $('.terminal-container'), pg = $('.panel-playground');
  const RE = /((?<![^\n])[ \t]*\/\/[^\n]*)|(&lt;!--[\s\S]*?--&gt;)|(&lt;\/?[a-zA-Z][\w:-]*)|("(?:[^"\\\n]|\\.)*")(\s*:)?|\b(true|false|null)\b|(-?\b\d+(?:\.\d+)?\b)/g;
  const hl = s => s.replace(RE, (m, c, hc, tg, str, col, kw) => c || hc ? `<span class="tk-c">${m}</span>` : tg ? `<span class="tk-t">${m}</span>` : str ? `<span class="${col ? 'tk-k' : 'tk-s'}">${str}</span>${col || ''}` : kw ? `<span class="tk-b">${m}</span>` : `<span class="tk-n">${m}</span>`);
  if (out) new MutationObserver(() => { const c = out.firstElementChild; if (c && !c.dataset.hl) { c.dataset.hl = 1; c.innerHTML = hl(c.innerHTML); } }).observe(out, { childList: true });
  if (btn && box) { const bar = Object.assign(document.createElement('div'), { className: 'run-bar' }), pill = Object.assign(document.createElement('div'), { className: 'run-steps' });
    box.append(bar, pill); const steps = ['Dispatching to solver cluster', 'Matching TLS fingerprint', 'Replaying cursor path', 'Waiting for clearance cookie', 'Collecting response']; let timer, was = false;
    new MutationObserver(() => { const on = btn.disabled; box.classList.toggle('is-running', on); pg && pg.classList.toggle('is-running', on); clearInterval(timer);
      if (on) { let i = 0; pill.textContent = steps[0]; timer = setInterval(() => { pill.textContent = steps[Math.min(++i, steps.length - 1)]; }, 1100); }
      else if (was) { box.classList.add('fx-done'); setTimeout(() => box.classList.remove('fx-done'), 900); } was = on; }).observe(btn, { attributes: true, attributeFilter: ['disabled'] }); }

  // plans: monthly cost estimator (monthly prices as listed on the page)
  const grid = $('.cards-grid-main');
  if (grid) { const P = [['Free (75/day)', 0, 2250, '.card-free'], ['Starter', 9, 5000, '.card-starter'], ['Moderato', 29, 30000, '.card-moderato'], ['Vince', 99, 150000, '.card-vince']];
    const box = document.createElement('section'); box.className = 'fx-calc';
    box.innerHTML = '<h2>Estimate your monthly cost</h2><div class="fx-calc-row"><input id="fx-vol" type="range" min="0" max="100" value="45" aria-label="Solves per month"><output id="fx-out"></output></div><div class="fx-calc-res" id="fx-res"></div>';
    grid.after(box); const vol = $('#fx-vol'), o = $('#fx-out'), res = $('#fx-res');
    const upd = () => { let n = Math.pow(10, 2 + vol.value / 100 * 3.4); const st = n > 10000 ? 1000 : n > 1000 ? 100 : 10; n = Math.round(n / st) * st; o.textContent = n.toLocaleString() + ' solves / month';
      const opts = P.filter(p => n <= p[2]).map(p => ({ name: p[0], cost: p[1], sel: p[3] })); opts.push({ name: 'Pay-as-you-go', cost: n * .002, sel: null });
      const b = opts.reduce((a, c) => c.cost < a.cost ? c : a); const per = b.cost ? '$' + (b.cost / n * 1000).toFixed(2) + ' per 1k solves' : 'no charge';
      res.innerHTML = `<div><span>Best fit</span><strong>${b.name}</strong></div><div><span>Estimated cost</span><strong>$${b.cost.toFixed(b.cost % 1 ? 2 : 0)}/mo</strong></div><div><span>Effective rate</span><strong>${per}</strong></div>` + (b.sel ? `<button class="btn-secondary" id="fx-go">See ${b.name}</button>` : '') + (n > 150000 ? '<p>Above 150k a month? Ask about Enterprise.</p>' : '');
      const go = $('#fx-go'); if (go) go.onclick = () => $(b.sel).scrollIntoView({ behavior: 'smooth', block: 'center' }); };
    vol.addEventListener('input', upd); upd(); }

  // docs: instant search, "/" to focus
  const gcs = $$('.guide-card');
  if (gcs.length) { const i = document.createElement('input'); i.className = 'fx-search'; i.type = 'search'; i.placeholder = 'Search the docs   ( / )'; (($('.guide-header') || gcs[0])).after(i);
    i.addEventListener('input', () => { const q = i.value.toLowerCase(); gcs.forEach(c => { c.hidden = !!q && !c.textContent.toLowerCase().includes(q); }); });
    addEventListener('keydown', e => { if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); i.focus(); } }); }
})();
