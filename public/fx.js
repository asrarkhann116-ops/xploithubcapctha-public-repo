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
})();
