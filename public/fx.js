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
  const hint = t => /Network Error/.test(t) ? '\n// What to do: check your connection and try again.' : !/ERROR: Challenge resolution failed/.test(t) ? '' : /credit/i.test(t) ? '\n// What to do: top up credits or redeem a voucher.' : /time/i.test(t) ? '\n// What to do: switch to Pure CDP Stealth mode or add a proxy, then run again.' : '\n// What to do: check the URL, or try Pure CDP Stealth mode or a proxy. Failed runs are not charged.';
  const hl = s => s.replace(RE, (m, c, hc, tg, str, col, kw) => c || hc ? `<span class="tk-c">${m}</span>` : tg ? `<span class="tk-t">${m}</span>` : str ? `<span class="${col ? 'tk-k' : 'tk-s'}">${str}</span>${col || ''}` : kw ? `<span class="tk-b">${m}</span>` : `<span class="tk-n">${m}</span>`);
  if (out) new MutationObserver(() => { const c = out.firstElementChild; if (c && !c.dataset.hl) { c.dataset.hl = 1; c.innerHTML = hl(c.innerHTML + hint(c.textContent)); const sc = c.closest('.terminal-screen'); if (sc) sc.classList.toggle('fx-empty', /standby/i.test(c.textContent)); } }).observe(out, { childList: true });
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

  // Ctrl/Cmd+Enter runs the console
  ['#target-url', '#target-proxy'].forEach(s => { const el = $(s); if (el) el.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); if (btn && !btn.disabled) btn.click(); } }); });
  if (btn) btn.title = 'Run (Ctrl+Enter)';

  // command palette (Ctrl/Cmd+K)
  const acts = [['Open console', '/'], ['Read the docs', '/guide/'], ['View plans', '/plans/'], ['System status', '/status'], ['Sign in', '/login']];
  if (btn) acts.unshift(['Run bypass', () => btn.click()]); if ($('#btn-copy-key')) acts.push(['Copy API key', () => $('#btn-copy-key').click()]);
  const pal = document.createElement('div'); pal.className = 'fx-pal'; pal.hidden = true; pal.setAttribute('role', 'dialog'); pal.setAttribute('aria-modal', 'true'); pal.setAttribute('aria-label', 'Command palette');
  pal.innerHTML = '<div class="fx-pal-box"><input type="text" placeholder="Type a command or page" aria-label="Search commands"><ul></ul></div>'; document.body.append(pal);
  const pi = $('input', pal), pl = $('ul', pal); let sel = 0, shown = [];
  const render = () => { const q = pi.value.toLowerCase(); shown = acts.filter(a => a[0].toLowerCase().includes(q)); sel = Math.min(sel, Math.max(0, shown.length - 1));
    pl.innerHTML = shown.map((a, i) => `<li class="${i === sel ? 'on' : ''}" data-i="${i}">${a[0]}</li>`).join('') || '<li>No matches</li>'; };
  const close = () => { pal.hidden = true; }, go = i => { const a = shown[i]; if (!a) return; close(); typeof a[1] === 'function' ? a[1]() : location.href = a[1]; };
  addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); pal.hidden = false; pi.value = ''; sel = 0; render(); pi.focus(); }
    else if (!pal.hidden) { if (e.key === 'Escape') close(); else if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, shown.length - 1); render(); } else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); render(); } else if (e.key === 'Enter') { e.preventDefault(); go(sel); } } });
  pi.addEventListener('input', () => { sel = 0; render(); });
  pal.addEventListener('click', e => { const li = e.target.closest('li[data-i]'); if (li) go(+li.dataset.i); else if (e.target === pal) close(); });

  // toasts: dismiss button, click to close, max 4 stacked
  const tc = $('#toast-container');
  if (tc) { new MutationObserver(ms => { ms.forEach(r => r.addedNodes.forEach(n => { if (n.classList && n.classList.contains('toast')) { const x = document.createElement('button'); x.className = 'toast-x'; x.type = 'button'; x.setAttribute('aria-label', 'Dismiss'); x.textContent = '\u00d7'; n.append(x); } }));
    while (tc.children.length > 4) tc.firstElementChild.remove(); }).observe(tc, { childList: true });
    tc.addEventListener('click', e => { const t = e.target.closest('.toast'); if (t) t.remove(); }); }

  // skip link + mobile bottom tab bar
  const mn = $('main'); if (mn) { mn.id = mn.id || 'fx-main'; const s = document.createElement('a'); s.className = 'fx-skip'; s.href = '#' + mn.id; s.textContent = 'Skip to content'; document.body.prepend(s); }
  if (!/admin/.test(location.pathname) && $('.navbar')) { const T = [['Console', '/', 'M4 17l6-6-6-6M12 19h8'], ['Docs', '/guide/', 'M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z'], ['Plans', '/plans/', 'M13 2L3 14h9l-1 8 10-12h-9z'], ['Account', '/login', 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8z']];
    const nav = document.createElement('nav'); nav.className = 'fx-tabbar'; nav.setAttribute('aria-label', 'Primary');
    nav.innerHTML = T.map(t => `<a href="${t[1]}"${location.pathname.replace(/\/$/, '') === t[1].replace(/\/$/, '') ? ' aria-current="page"' : ''}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${t[2]}"/></svg>${t[0]}</a>`).join(''); document.body.append(nav); }

  // console result chips (size, cookies, headers)
  if (out && box) { const ch = document.createElement('div'); ch.className = 'fx-chips'; box.before(ch);
    new MutationObserver(() => { const d = typeof lastResponseData !== 'undefined' ? lastResponseData : null; if (!d || (btn && btn.disabled)) { ch.innerHTML = ''; return; }
      const c = [d.html ? d.html.length.toLocaleString() + ' chars HTML' : '', (d.cookies || []).length + ' cookies', Object.keys(d.headers || {}).length + ' headers']; ch.innerHTML = c.filter(Boolean).map(x => `<span>${x}</span>`).join(''); }).observe(out, { childList: true }); }

  // plans: FAQ (answers taken from the site's own plan rules)
  const mx = $('.matrix-card');
  if (mx) { const f = document.createElement('section'); f.className = 'fx-faq'; const Q = [
    ['When am I charged?', 'Only for successful solves. If a challenge is not cleared, 0 credits are debited.'],
    ['How does the Free tier reset?', 'Free includes 75 requests per day and 3 worker slots. It resets daily at UTC midnight with no rollover.'],
    ['What does concurrency mean?', 'It is the number of requests that can run at the same time: 3 on Free, 10 on Starter, 50 on Moderato and 150+ on Vince.'],
    ['Do credits expire?', 'Pay-as-you-go credits never expire.'],
    ['How do I pay?', 'Send USDT (SPL) on Solana using your deposit reference ID, then verify the transaction. You can also redeem a voucher code.']];
    f.innerHTML = '<h2>Billing questions</h2>' + Q.map(q => `<details><summary>${q[0]}</summary><p>${q[1]}</p></details>`).join(''); mx.after(f); }

  // credits: low-balance state
  const cr = $('#nav-credits');
  if (cr) new MutationObserver(() => { const v = parseFloat(cr.textContent), pill = cr.closest('.stat-pill'); if (!pill || isNaN(v)) return;
    pill.classList.toggle('fx-low', v < 10 && v >= 3); pill.classList.toggle('fx-crit', v < 3); pill.title = v < 10 ? 'Low balance. Top up on the Plans page.' : '';
    if (v < 3 && typeof currentUser !== 'undefined' && currentUser && !currentUser.is_guest && !sessionStorage.getItem('fx_low')) { try { sessionStorage.setItem('fx_low', 1); } catch (e) {} showToast('Credits are almost gone. Top up on the Plans page.', 'error'); } }).observe(cr, { childList: true, characterData: true, subtree: true });

  // confirm dialog for regenerating the API key
  const ask = (title, body, ok, fn) => { const d = document.createElement('div'); d.className = 'fx-pal'; d.setAttribute('role', 'alertdialog'); d.setAttribute('aria-modal', 'true'); d.setAttribute('aria-label', title);
    d.innerHTML = `<div class="fx-pal-box fx-ask"><h2>${title}</h2><p>${body}</p><div class="row"><button class="btn-secondary" data-c>Cancel</button><button class="btn-primary" data-o>${ok}</button></div></div>`; document.body.append(d);
    const k = e => { if (e.key === 'Escape') x(); }, x = () => { d.remove(); removeEventListener('keydown', k); }; addEventListener('keydown', k);
    d.onclick = e => { if (e.target === d || e.target.hasAttribute('data-c')) x(); else if (e.target.hasAttribute('data-o')) { x(); fn(); } }; $('[data-c]', d).focus(); };
  const rg = $('#btn-regen-key');
  if (rg && typeof regenerateApiKey === 'function') { rg.onclick = null; rg.addEventListener('click', () => ask('Generate a new API key?', 'Your current key stops working immediately. Update any scripts that use it.', 'Generate new key', () => regenerateApiKey())); }

  // onboarding checklist (console page)
  const side = $('.side-column');
  if (side && btn) { let st = {}; try { st = JSON.parse(localStorage.getItem('fx_ob') || '{}'); } catch (e) {}
    const save = () => { try { localStorage.setItem('fx_ob', JSON.stringify(st)); } catch (e) {} };
    if (!st.hide) { const p = document.createElement('div'); p.className = 'panel fx-ob'; side.prepend(p);
      const draw = () => { const u = typeof currentUser !== 'undefined' ? currentUser : null; const S = [['Create an account', u && !u.is_guest], ['Run your first request', st.run], ['Copy a code snippet', st.copy]]; const n = S.filter(s => s[1]).length;
        p.innerHTML = `<div class="panel-header"><h2>Get started</h2><button class="toast-x" style="position:static" aria-label="Hide checklist" data-x>\u00d7</button></div><div class="fx-ob-bar"><i style="width:${n / 3 * 100}%"></i></div><ul>${S.map(s => `<li class="${s[1] ? 'ok' : ''}">${s[0]}</li>`).join('')}</ul>`; };
      draw(); p.onclick = e => { if (e.target.hasAttribute('data-x')) { st.hide = 1; save(); p.remove(); } };
      const nu = $('#nav-username'); if (nu) new MutationObserver(draw).observe(nu, { childList: true, characterData: true, subtree: true });
      new MutationObserver(() => { if (!btn.disabled && typeof lastResponseData !== 'undefined' && lastResponseData && lastResponseData.success && !st.run) { st.run = 1; save(); draw(); } }).observe(btn, { attributes: true, attributeFilter: ['disabled'] });
      document.addEventListener('click', e => { if (e.target.closest('.code-copy-btn') && !st.copy) { st.copy = 1; save(); draw(); } }); } }

  // register: password strength
  const pw = $('#reg-password');
  if (pw) { const m = document.createElement('div'); m.className = 'fx-pw'; m.setAttribute('role', 'status'); m.innerHTML = '<i></i><i></i><i></i><i></i><span></span>'; pw.after(m);
    pw.addEventListener('input', () => { const v = pw.value; let s = 0; if (v.length >= 8) s++; if (v.length >= 12) s++; if (/[a-z]/.test(v) && /[A-Z]/.test(v) && /\d/.test(v)) s++; if (/[^A-Za-z0-9]/.test(v)) s++;
      const n = v ? Math.max(s, 1) : 0; $$('i', m).forEach((b, i) => { b.className = i < n ? 'on s' + n : ''; }); $('span', m).textContent = v ? ['Weak', 'Weak', 'Fair', 'Good', 'Strong'][s] + (v.length < 6 ? ' (minimum 6 characters)' : '') : ''; }); }

  // favicon moon phases
  { const lk = document.querySelector('link[rel~=icon]') || document.createElement('link'); lk.rel = 'icon'; lk.type = 'image/png'; document.head.append(lk);
    const c = document.createElement('canvas'); c.width = c.height = 32; const x = c.getContext('2d'), D = [40, 14, 8, 3, 0, -3, -8, -14]; let k = 0;
    const f = () => { x.clearRect(0, 0, 32, 32); x.save(); x.beginPath(); x.arc(16, 16, 13, 0, 7); x.clip(); x.fillStyle = '#fff4ec'; x.fillRect(0, 0, 32, 32); x.fillStyle = '#14152e'; x.beginPath(); x.arc(16 + D[k], 15, 13, 0, 7); x.fill(); x.restore(); lk.href = c.toDataURL(); };
    f(); if (!RM) setInterval(() => { k = (k + 1) % 8; f(); }, 1500); }

  // pixel page transition between internal pages
  if (!RM) { const v = document.createElement('div'); v.className = 'fx-veil'; document.body.append(v); addEventListener('pageshow', () => v.classList.remove('in'));
    document.addEventListener('click', e => { const a = e.target.closest('a[href]'); if (!a || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || a.target === '_blank' || a.hasAttribute('download')) return;
      const u = new URL(a.href, location); if (!/^https?:$/.test(u.protocol) || u.origin !== location.origin || (u.pathname === location.pathname && u.search === location.search)) return;
      e.preventDefault(); v.classList.add('in'); setTimeout(() => { location.href = u.href; }, 260); }); }

  // docs: "On this page"
  if (gcs.length > 1) { const hs = gcs.map(c => c.querySelector('h1,h2,h3,h4')).filter(Boolean);
    if (hs.length > 1) { const t = document.createElement('nav'); t.className = 'fx-toc'; t.setAttribute('aria-label', 'On this page');
      t.innerHTML = '<b>On this page</b>' + hs.map((h, i) => { h.id = h.id || 'sec-' + i; return `<a href="#${h.id}">${h.textContent.trim()}</a>`; }).join(''); document.body.append(t);
      const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) $$('a', t).forEach(a => a.classList.toggle('on', a.hash === '#' + e.target.id)); }), { rootMargin: '-20% 0px -70% 0px' }); hs.forEach(h => io.observe(h)); } }

  // top bar: show real fleet state and measured latency instead of static text
  const fc = $('#fleet-count'), st1 = $('#sys-status-text'), lat = $('#telemetry-latency');
  if (fc && st1) new MutationObserver(() => { const n = parseInt(fc.textContent, 10) || 0, dot = $('.system-bar .pulse-indicator');
    st1.textContent = n > 0 ? 'Operational' : 'No solvers online'; st1.style.color = n > 0 ? '' : '#ffe0a8';
    if (dot) { dot.style.background = n > 0 ? '' : '#ffe0a8'; dot.style.boxShadow = n > 0 ? '' : '0 0 6px #ffe0a8'; } }).observe(fc, { childList: true, characterData: true, subtree: true });
  if (lat) { const t0 = performance.now(); fetch('/api/workers/status', { cache: 'no-store' }).then(() => { lat.textContent = Math.round(performance.now() - t0) + ' ms'; const l = lat.previousElementSibling; if (l) l.textContent = 'API round trip:'; }).catch(() => {}); }

  // skeleton shimmer until real values arrive
  ['#nav-credits', '#reset-timer', '#snippet-code-display'].forEach(s => { const el = $(s); if (!el) return; el.classList.add('fx-skel');
    const mo = new MutationObserver(() => { el.classList.remove('fx-skel'); mo.disconnect(); }); mo.observe(el, { childList: true, characterData: true, subtree: true }); setTimeout(() => el.classList.remove('fx-skel'), 6000); });

  // saved targets (stored in this browser only)
  const cb = $('.command-bar'), ui = $('#target-url'), E = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  if (cb && ui) { let L = []; try { L = JSON.parse(localStorage.getItem('fx_targets') || '[]'); } catch (e) {}
    const row = document.createElement('div'); row.className = 'fx-presets'; cb.after(row); const sv = () => { try { localStorage.setItem('fx_targets', JSON.stringify(L)); } catch (e) {} };
    const rd = () => { row.innerHTML = '<button type="button" class="fx-save">Save this URL</button>' + L.map((u, i) => `<span class="fx-pre"><button type="button" data-u="${i}" title="${E(u)}">${E(u.replace(/^https?:\/\//, '').slice(0, 28))}</button><button type="button" data-d="${i}" aria-label="Remove saved URL">\u00d7</button></span>`).join(''); }; rd();
    row.addEventListener('click', e => { const t = e.target;
      if (t.classList.contains('fx-save')) { const u = ui.value.trim(); if (u && !L.includes(u)) { L.unshift(u); L = L.slice(0, 6); sv(); rd(); } }
      else if (t.dataset.u !== undefined) { ui.value = L[+t.dataset.u]; ui.dispatchEvent(new Event('input', { bubbles: true })); }
      else if (t.dataset.d !== undefined) { L.splice(+t.dataset.d, 1); sv(); rd(); } }); }

  // theme switch: dusk / night / dawn
  { const T = ['dusk', 'night', 'dawn']; let cur = 'dusk'; try { cur = localStorage.getItem('fx_theme') || 'dusk'; } catch (e) {} root.dataset.theme = cur;
    const host = $('.nav-controls') || $('.nav-container');
    if (host) { const b = document.createElement('button'); b.type = 'button'; b.className = 'fx-theme';
      const set = t => { cur = t; root.dataset.theme = t; try { localStorage.setItem('fx_theme', t); } catch (e) {} b.textContent = t[0].toUpperCase() + t.slice(1); b.setAttribute('aria-label', 'Theme: ' + t + '. Click to change'); };
      host.prepend(b); b.onclick = () => set(T[(T.indexOf(cur) + 1) % 3]); set(cur); } }

  // pricing: price roll on plan switch, billing flow, payment methods
  $$('.price-val').forEach(el => new MutationObserver(() => { el.classList.remove('fx-roll'); void el.offsetWidth; el.classList.add('fx-roll'); }).observe(el, { childList: true, characterData: true, subtree: true }));
  const gb = $('.guarantee-banner');
  if (gb) { const fl = document.createElement('div'); fl.className = 'fx-flow'; fl.innerHTML = '<span>Your request</span><b></b><span>Solver attempts clearance</span><b></b><span class="ok">Cleared: 1 credit debited</span><span class="no">Not cleared: 0 credits debited</span>'; gb.after(fl); }
  const fq = $('.fx-faq'); if (fq) fq.insertAdjacentHTML('beforeend', '<div class="fx-pay"><span>Solana USDT (SPL)</span><span>Voucher codes</span></div>');
})();

/* ---- round 4: works-with, scroll hint, mini CTA, glitch, raw/pretty, line numbers, code theme, type scale, low-credit prompt, sounds ---- */
(() => {
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const store = { get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} } };
  const home = location.pathname === '/' || /index\.html$/.test(location.pathname);
  const nav = $('.nav-container');
  const mk = (tag, cls, html) => { const e = document.createElement(tag); e.className = cls; if (html) e.innerHTML = html; return e; };

  // #4 works-with strip, #5 scroll hint, #6 sticky mini-CTA, #7 one-time glitch
  const lead = home && $('.hero-lead');
  if (lead) lead.after(mk('div', 'fx-works', '<span>Works with</span><b>cURL</b><b>Python</b><b>Node.js</b><b>Playwright</b>'));
  const h1 = $('.hero-heading');
  if (home && h1 && !RM) setTimeout(() => { h1.classList.add('fx-glitch'); setTimeout(() => h1.classList.remove('fx-glitch'), 700); }, 1400);
  if (home) {
    const hint = mk('div', 'fx-scrollhint', 'Scroll'); hint.setAttribute('aria-hidden', 'true'); document.body.append(hint);
    const bar = mk('div', 'fx-mini', '<span>75 free solves every day. No card needed.</span><a class="btn-hero-primary" href="/register">Create account</a>'); document.body.append(bar);
    addEventListener('scroll', () => { const y = scrollY; hint.classList.toggle('gone', y > 80); bar.classList.toggle('on', y > 700); }, { passive: true });
  }

  // #34 console Raw / Pretty toggle
  const out = $('#console-output');
  if (out) {
    const btn = mk('button', 'fx-mini-btn', 'Pretty'); btn.type = 'button'; let busy = false, pretty = true;
    const fmt = () => { if (busy) return; const t = out.textContent.trim(); if (t[0] !== '{' && t[0] !== '[') return;
      try { const j = JSON.parse(t); busy = true; out.textContent = JSON.stringify(j, null, pretty ? 2 : 0); } catch (e) {} busy = false; };
    btn.onclick = () => { pretty = !pretty; btn.textContent = pretty ? 'Pretty' : 'Raw'; fmt(); };
    out.before(btn); new MutationObserver(fmt).observe(out, { childList: true, characterData: true, subtree: true });
  }

  // #41 line numbers on plain code blocks, #46 code theme switch
  if (/guide/.test(location.pathname)) $$('pre').filter(p => p.id !== 'console-output' && !p.children.length).forEach(p => {
    p.classList.add('fx-ln'); p.innerHTML = p.textContent.replace(/\n$/, '').split('\n').map(l => '<span class="ln"></span>' + l.replace(/[<&]/g, c => c === '<' ? '&lt;' : '&amp;')).join('\n'); });
  if (nav && $('pre')) {
    const C = ['dusk', 'mono', 'paper']; let c = C.includes(store.get('fx_code')) ? store.get('fx_code') : 'dusk';
    const b = mk('button', 'fx-theme', ''); b.type = 'button';
    const set = v => { c = v; document.documentElement.dataset.code = v; store.set('fx_code', v); b.textContent = 'Code: ' + v; b.setAttribute('aria-label', 'Code theme: ' + v + '. Click to change'); };
    b.onclick = () => set(C[(C.indexOf(c) + 1) % 3]); nav.prepend(b); set(c);
  }

  // #67 low-credit prompt
  const cr = $('#nav-credits');
  if (cr && !/plans/.test(location.pathname)) {
    const note = mk('div', 'fx-low', '<span>Credits are running low.</span><a href="/plans/">Top up</a><button type="button" aria-label="Dismiss">×</button>'); document.body.append(note);
    note.querySelector('button').onclick = () => { note.classList.remove('on'); sessionStorage.setItem('fx_low_x', '1'); };
    const chk = () => { const m = cr.textContent.replace(/,/g, '').match(/\d+(\.\d+)?/); let dismissed = false; try { dismissed = sessionStorage.getItem('fx_low_x'); } catch (e) {}
      note.classList.toggle('on', !!m && +m[0] <= 10 && !dismissed && !/guest/i.test(cr.textContent)); };
    new MutationObserver(chk).observe(cr, { childList: true, characterData: true, subtree: true }); chk();
  }

  // #59 optional UI sounds, off by default
  if (nav) {
    let on = store.get('fx_snd') === '1', ac = null; const b = mk('button', 'fx-theme', ''); b.type = 'button';
    const lab = () => { b.textContent = 'Sound: ' + (on ? 'on' : 'off'); b.setAttribute('aria-pressed', on); };
    const beep = f => { try { ac = ac || new (window.AudioContext || window.webkitAudioContext)(); const o = ac.createOscillator(), g = ac.createGain();
      o.type = 'square'; o.frequency.value = f; g.gain.value = .02; o.connect(g); g.connect(ac.destination); o.start(); g.gain.exponentialRampToValueAtTime(.0001, ac.currentTime + .08); o.stop(ac.currentTime + .09); } catch (e) {} };
    b.onclick = () => { on = !on; store.set('fx_snd', on ? '1' : '0'); lab(); if (on) beep(660); }; lab(); nav.prepend(b);
    document.addEventListener('click', e => { if (on && e.target.closest('button,a.btn-hero-primary,a.btn-hero-secondary')) beep(520); });
  }
})();

/* ---- round 5: live platform metrics from /api/analytics/metrics (hero + status page) ---- */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const num = v => { const n = typeof v === 'string' ? parseFloat(v) : v; return typeof n === 'number' && isFinite(n) ? n : null; };
  const read = j => { const m = (j && j.metrics) || {}, t = num(m.total_requests), s = num(m.successful_requests);
    let ok = num(m.success_rate_percent); if (ok === null && t > 0 && s !== null) ok = s / t * 100;
    return { ok: t > 0 ? ok : null, ms: t > 0 ? num(m.avg_latency_ms) : null, total: t, users: num(m.active_users_24h) }; };
  const fmtMs = ms => ms >= 1000 ? (ms / 1000).toFixed(1) + 's' : Math.round(ms) + ' ms';
  const fetchM = () => fetch('/api/analytics/metrics', { cache: 'no-store' }).then(r => { if (!r.ok) throw 0; return r.json(); }).then(read);

  // hero: measured values with honest labels and the sample size; "n/a" when there is no data
  const nums = document.querySelectorAll('.hero-metrics-bar .metric-num');
  if (nums.length >= 2) {
    const put = (el, txt, label) => { el.textContent = txt; const d = el.parentElement && el.parentElement.querySelector('.metric-desc'); if (d && label) d.textContent = label; };
    fetchM().then(m => { const n = m.total || 0, s = ' (' + n.toLocaleString() + ' request' + (n === 1 ? '' : 's') + ')';
      put(nums[0], m.ok === null ? 'n/a' : m.ok.toFixed(1) + '%', 'Overall solve rate' + s);
      put(nums[1], m.ms === null ? 'n/a' : fmtMs(m.ms), 'Average clearance latency' + s); })
    .catch(() => { put(nums[0], 'n/a'); put(nums[1], 'n/a'); });
  }

  // status page: live platform-metrics panel
  if ($('#overall') && $('.side-column')) {
    const p = document.createElement('div'); p.className = 'panel';
    p.innerHTML = '<div class="panel-header"><h2>Platform metrics</h2></div><p class="panel-caption" id="pm">Loading...</p>'; $('.side-column').prepend(p);
    const run = () => fetchM().then(m => { const b = [];
      if (m.ok !== null) b.push('Solve rate ' + m.ok.toFixed(1) + '%'); if (m.ms !== null) b.push('Average latency ' + fmtMs(m.ms));
      b.push((m.total || 0).toLocaleString() + ' requests handled'); if (m.users !== null) b.push(m.users + ' active user' + (m.users === 1 ? '' : 's') + ' in 24 hours');
      $('#pm').textContent = b.join(', ') + '.'; }).catch(() => { $('#pm').textContent = 'Metrics are unavailable right now.'; });
    run(); setInterval(run, 10000); }
})();

/* ---- round 6: 7-day usage graph, solver mode split, my recent requests, error hints ---- */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
  const MODE = m => /cdp|stealth|browser/i.test(m) ? 'Hardware CDP' : /fast|tls/i.test(m) ? 'Fast TLS' : String(m).replace(/_/g, ' ');

  // status page: usage graph (#1) and mode split (#2) from /api/analytics/metrics
  const side = $('#overall') && $('.side-column');
  if (side) {
    const pg = el('div', 'panel'), pm = el('div', 'panel');
    pg.innerHTML = '<div class="panel-header"><h2>Last 7 days</h2></div><p class="panel-caption" id="fx-gcap">Loading...</p><div class="fx-bars" id="fx-bars" role="img" aria-label="Requests per day for the last 7 days"></div>';
    pm.innerHTML = '<div class="panel-header"><h2>Solver modes</h2></div><p class="panel-caption" id="fx-mcap">Loading...</p><div class="fx-split" id="fx-split"></div><div class="fx-legend" id="fx-leg"></div>';
    side.append(pg, pm);
    const draw = () => fetch('/api/analytics/metrics', { cache: 'no-store' }).then(r => r.json()).then(j => {
      const m = j.metrics || {}, by = {}; (m.daily_trends || []).forEach(d => by[d.date] = d);
      const days = Array.from({ length: 7 }, (_, i) => { const dt = new Date(Date.now() - (6 - i) * 864e5), k = dt.toISOString().slice(0, 10); return { k, d: by[k] || null, w: dt.toLocaleDateString('en-US', { weekday: 'short', timeZone: 'UTC' }) }; });
      const max = Math.max(1, ...days.map(x => x.d ? x.d.total : 0)), tot = days.reduce((a, x) => a + (x.d ? x.d.total : 0), 0);
      $('#fx-gcap').textContent = tot ? tot.toLocaleString() + ' requests in the last 7 days (UTC days).' : 'No requests in the last 7 days.';
      const bars = $('#fx-bars'); bars.replaceChildren(...days.map(x => { const c = el('div', 'fx-col'), b = el('i'); const n = x.d ? x.d.total : 0;
        b.style.height = Math.max(n ? 8 : 2, n / max * 100) + '%'; if (x.d && x.d.success_rate < 90) b.className = 'warn';
        c.title = x.k + ': ' + n + ' requests' + (x.d ? ', ' + x.d.success_rate.toFixed(1) + '% solved' : ''); c.append(b, el('span', '', x.w)); return c; }));
      const md = m.mode_distribution || {}, ent = Object.entries(md), sum = ent.reduce((a, e) => a + e[1], 0);
      $('#fx-mcap').textContent = sum ? 'How requests were solved.' : 'No solved requests yet.';
      $('#fx-split').replaceChildren(...ent.map(([k, v], i) => { const s = el('i'); s.style.flex = v; s.dataset.i = i % 4; s.title = MODE(k) + ': ' + v; return s; }));
      $('#fx-leg').replaceChildren(...ent.map(([k, v], i) => { const s = el('span', '', MODE(k) + ' ' + Math.round(v / sum * 100) + '% (' + v + ')'); s.dataset.i = i % 4; return s; }));
    }).catch(() => { $('#fx-gcap').textContent = 'Usage data is unavailable right now.'; $('#fx-mcap').textContent = 'Unavailable right now.'; });
    draw(); setInterval(draw, 30000);
  }

  // console: my recent requests (#3, saved in this browser only) and error hints (#4)
  const term = $('#console-output');
  if (term) {
    const box = term.closest('.terminal-screen'), host = box && box.parentElement; if (!host) return;
    let L = []; try { L = JSON.parse(localStorage.getItem('fx_hist') || '[]'); } catch (e) {}
    const hint = el('div', 'fx-hint'); hint.hidden = true; host.after(hint);
    const panel = el('div', 'panel fx-hist'); panel.innerHTML = '<div class="panel-header"><h2>My recent requests</h2><button type="button" class="fx-mini-btn" id="fx-clr">Clear</button></div><p class="panel-caption">Saved in this browser only. Your account history lives on the server.</p><div id="fx-rows"></div>'; hint.after(panel);
    const rows = $('#fx-rows', panel), ago = t => { const s = (Date.now() - t) / 1000; return s < 60 ? 'just now' : s < 3600 ? Math.floor(s / 60) + ' min ago' : s < 86400 ? Math.floor(s / 3600) + ' h ago' : new Date(t).toLocaleDateString(); };
    const render = () => { rows.replaceChildren(...(L.length ? L.map(r => { const d = el('div', 'fx-row' + (r.ok ? '' : ' bad')); d.append(el('b', '', r.ok ? 'Solved' : 'Failed'), el('span', 'u', r.u), el('span', '', r.ms + ' ms'), el('span', '', ago(r.t))); return d; }) : [el('p', 'panel-caption', 'No requests yet. Run your first one above.')])); };
    $('#fx-clr', panel).onclick = () => { L = []; try { localStorage.removeItem('fx_hist'); } catch (e) {} render(); }; render();
    const H = { 400: 'The target refused or timed out. No credit was charged. Check the URL and try again.', 401: 'Your API key is missing or invalid. Send it in the X-API-Key header.', 402: 'Not enough credits. Top up or claim your free daily requests.', 403: 'This account is restricted by a cooldown. Wait for it to end, then retry.', 429: 'Too many requests. Wait a moment before retrying.' };
    const show = c => { const t = H[c]; hint.hidden = !t; if (!t) return; hint.textContent = c + ': ' + t + ' '; if (c === 402) { const a = el('a', '', 'Top up'); a.href = '/plans/'; hint.append(a); } else if (c === 401 || c === 400) { const a = el('a', '', 'Read the docs'); a.href = '/guide/'; hint.append(a); } };
    const f0 = window.fetch;
    window.fetch = function (u, o) { const isRun = typeof u === 'string' && /\/v1\/unlock$/.test(u) && o && /post/i.test(o.method || ''); if (!isRun) return f0.apply(this, arguments);
      let tgt = ''; try { const b = JSON.parse(o.body), x = new URL(b.url || b.target_url || b.target); tgt = x.host + (x.pathname === '/' ? '' : x.pathname); } catch (e) {}
      const t0 = Date.now(); return f0.apply(this, arguments).then(res => { res.clone().json().then(d => { const ok = !!(d && d.success);
        L.unshift({ u: tgt || 'unknown target', ok, ms: Math.round((d && d.duration_ms) || Date.now() - t0), t: Date.now() }); L = L.slice(0, 10);
        try { localStorage.setItem('fx_hist', JSON.stringify(L)); } catch (e) {} render(); show(ok ? 0 : (res.status === 200 ? 400 : res.status)); }).catch(() => show(res.status)); return res; }); };
  }
})();
