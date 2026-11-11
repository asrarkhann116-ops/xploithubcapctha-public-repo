





function handleSolanaDepositVerify() {
    if (!currentUser || currentUser.is_guest || !currentUser.id) {
        showToast('⚠️ Guest Account: Please sign in or register before verifying Solana deposits.', 'error');
        setTimeout(() => {
            window.location.href = '/login';
        }, 800);
        return;
    }
    verifyDeposit();
}
// ══════════════════════════════════════════════════════════
//  XPLOIT UNBLOCKER — DEVELOPER CONSOLE CLIENT CONTROLLER
//  Aesthetic: Human Developer Standards (Zero Emojis, Pure SVGs)
// ══════════════════════════════════════════════════════════

let currentUser = null;
let currentMode = 'auto';
let currentTab = 'html';
let currentSnippetLang = 'curl';
let lastResponseData = null;

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    loadUserProfile();
    pollFleetStatus();
    setInterval(pollFleetStatus, 10000); // Poll worker nodes every 10s
});

// Toast System (Clean, non-intrusive notification replacing alert)
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    let iconSvg = '';
    if (type === 'success') {
        iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#f6b8c8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
    } else if (type === 'error') {
        iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#ff8a8a" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`;
    } else {
        iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9fd8ff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`;
    }

    toast.innerHTML = iconSvg;
    const msgSpan = document.createElement('span');
    msgSpan.textContent = message;
    toast.appendChild(msgSpan);
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.2s';
        setTimeout(() => toast.remove(), 250);
    }, 3500);
}

/**
 * Map plan key to dynamic debit telemetry string with effective rate clarity.
 * Prevents users from confusing 1 solve credit with $1.00 USD.
 */
function getPlanDebitText(planKey) {
    const key = String(planKey || '').toLowerCase();
    switch (key) {
        case 'moderato':
            return '1 Solve (≈ $0.0012 on Moderato)';
        case 'starter':
            return '1 Solve (≈ $0.0025 on Starter)';
        case 'vince':
            return '1 Solve (≈ $0.0008 on Vince)';
        case 'enterprise':
            return '1 Solve (≈ $0.0005 on Enterprise)';
        case 'pay_as_you_go':
        case 'payg':
            return '1 Solve (≈ $0.002 on Pay-As-You-Go)';
        case 'guest':
        case 'free':
        default:
            return '1 Free Solve (0 on fail)';
    }
}

// Load User Profile & State
async function loadUserProfile() {
    try {
        const res = await fetch('/api/user/me');
        const data = await res.json();
        currentUser = data;

        // Navbar & Profile Info
        const usernameEl = document.getElementById('nav-username');
        if (usernameEl) {
            usernameEl.innerText = data.is_guest
                ? (data.username + ' (Guest Tester)')
                : data.username;
        }

        const creditsEl = document.getElementById('nav-credits');
        if (creditsEl) {
            const numCredits = Number(data.credits || 0);
            creditsEl.innerText = numCredits.toLocaleString(undefined, {
                minimumFractionDigits: 0,
                maximumFractionDigits: (numCredits % 1 === 0) ? 0 : 2
            });
            creditsEl.dataset.rawCredits = String(data.credits || 0);
        }

        const apiKeyEl = document.getElementById('api-key-val');
        const apiKeyActions = document.getElementById('api-key-actions');
        const guestBanner = document.getElementById('guest-key-banner');
        const authBtnText = document.getElementById('btn-auth-text');
        const authBtn = document.getElementById('btn-auth-action');

        if (data.is_guest) {
            const guestLock = document.getElementById('payment-guest-lock');
            if (guestLock) guestLock.style.display = 'flex';
            const depositRefEl = document.getElementById('user-deposit-ref');
            if (depositRefEl) {
                depositRefEl.innerText = 'Sign in to generate memo';
                depositRefEl.style.color = 'var(--text-muted)';
            }
            const btnSidebarSellixText = document.getElementById('btn-sidebar-sellix-text');
            if (btnSidebarSellixText) btnSidebarSellixText.innerText = 'Sign In / Register to Pay with Card';
            const btnVerifyTxText = document.getElementById('btn-verify-tx-text');
            if (btnVerifyTxText) btnVerifyTxText.innerText = 'Sign In to Verify';
            // Guest tester: hide API key & show sign-up banner
            if (apiKeyEl) {
                apiKeyEl.type = 'text';
                apiKeyEl.value = 'Hidden for Guests — Sign Up to Unlock';
            }
            if (apiKeyActions) apiKeyActions.style.display = 'none';
            if (guestBanner) guestBanner.style.display = 'flex';
            if (authBtn) {
                authBtn.href = '/login';
                authBtn.onclick = null;
            }
            if (authBtnText) authBtnText.innerText = 'Sign In / Register';
        } else {
            // Logged-in user: show real API key and allow regeneration
            const guestLock = document.getElementById('payment-guest-lock');
            if (guestLock) guestLock.style.display = 'none';
            const depositRefEl = document.getElementById('user-deposit-ref');
            if (depositRefEl) {
                depositRefEl.innerText = data.deposit_ref || 'XPK-REF';
                depositRefEl.style.color = 'var(--text-accent)';
            }
            const btnSidebarSellixText = document.getElementById('btn-sidebar-sellix-text');
            if (btnSidebarSellixText) btnSidebarSellixText.innerText = `Pay $${currentSidebarPrice} with Card / Apple Pay`;
            const btnVerifyTxText = document.getElementById('btn-verify-tx-text');
            if (btnVerifyTxText) btnVerifyTxText.innerText = 'Verify On-Chain';
            if (apiKeyEl) {
                apiKeyEl.type = 'password';
                apiKeyEl.value = data.api_key;
            }
            if (apiKeyActions) apiKeyActions.style.display = 'flex';
            if (guestBanner) guestBanner.style.display = 'none';
            if (authBtn) {
                authBtn.href = 'javascript:void(0)';
                authBtn.onclick = logoutUser;
            }
            if (authBtnText) authBtnText.innerText = 'Sign Out';
        }

        // ── Hero CTA Button State (Claim vs Copy Key) ─────────────
        const heroClaimBtn = document.getElementById('btn-hero-claim');
        if (heroClaimBtn) {
            if (data.is_guest) {
                heroClaimBtn.href = '/login';
                heroClaimBtn.onclick = null;
                const span = heroClaimBtn.querySelector('span');
                if (span) span.innerText = 'Claim Free API Key';
            } else {
                heroClaimBtn.href = 'javascript:void(0)';
                heroClaimBtn.onclick = (e) => {
                    e.preventDefault();
                    const keyCard = document.querySelector('.panel-auth');
                    if (keyCard) {
                        keyCard.scrollIntoView({ behavior: 'smooth' });
                    }
                    if (data.api_key) {
                        navigator.clipboard.writeText(data.api_key);
                        showToast('🔑 API Key copied to clipboard!', 'success');
                    }
                };
                const span = heroClaimBtn.querySelector('span');
                if (span) span.innerText = 'Copy My API Key';
            }
        }

        // ── Plan Badge & Concurrency Info ──────────────────────────
        const tierBadge = document.getElementById('tier-badge');
        const tierLabel = document.getElementById('tier-label');
        const costEl = document.getElementById('cost-per-req');
        const dailyInfoEl = document.getElementById('daily-info');
        const resetTimerEl = document.getElementById('reset-timer');
        const metricDebit = document.getElementById('metric-debit');

        const planKey = String(data.tier || (data.is_guest ? 'guest' : 'free')).toLowerCase();
        const planName = data.plan_name || planKey.toUpperCase();
        const concurrency = data.concurrency_limit || (planKey === 'free' ? 3 : 10);

        if (metricDebit) {
            metricDebit.textContent = getPlanDebitText(planKey);
        }

        if (tierBadge) {
            tierBadge.className = 'tier-badge tier-' + planKey;
            tierBadge.textContent = planName.toUpperCase();
        }
        if (tierLabel) {
            if (planKey === 'moderato') {
                tierLabel.textContent = 'MODERATO — 30,000 solves/mo • 50 workers concurrency';
            } else if (planKey === 'vince') {
                tierLabel.textContent = 'VINCE — 150,000 solves/mo • 150+ workers • Dedicated cluster';
            } else if (planKey === 'enterprise') {
                tierLabel.textContent = 'ENTERPRISE — 1,000,000 solves/mo • 500+ workers • Dedicated cluster';
            } else if (planKey === 'starter') {
                tierLabel.textContent = 'STARTER — 5,000 solves/mo • 10 workers concurrency';
            } else if (planKey === 'pay_as_you_go') {
                tierLabel.textContent = 'PAY-AS-YOU-GO — $0.002/req ($2/1k) • Never expires';
            } else if (planKey === 'guest') {
                tierLabel.textContent = 'GUEST — 5 test requests only';
            } else {
                tierLabel.textContent = 'FREE — 75 requests/day • 3 slots • Resets daily (no rollover)';
            }
        }
        if (costEl) {
            if (planKey === 'vince') {
                costEl.textContent = '$0.0008 / solve';
                costEl.style.color = '#ffe0a8';
            } else if (planKey === 'enterprise') {
                costEl.textContent = '$0.0005 / solve';
                costEl.style.color = '#bbf7d0';
            } else if (planKey === 'moderato') {
                costEl.textContent = '$0.0012 / solve';
                costEl.style.color = '#f6b8c8';
            } else if (planKey === 'starter') {
                costEl.textContent = '$0.0025 / solve';
                costEl.style.color = '#9fd8ff';
            } else if (planKey === 'pay_as_you_go') {
                costEl.textContent = '$0.0020 / solve';
                costEl.style.color = '#f6b8c8';
            } else {
                costEl.textContent = 'Free (75/day)';
                costEl.style.color = '#9fd8ff';
            }
        }
        if (dailyInfoEl) {
            dailyInfoEl.textContent = `${concurrency} concurrent worker slots`;
        }

        // Countdown to next UTC midnight reset
        if (resetTimerEl && data.next_reset_in_seconds != null) {
            startResetCountdown(data.next_reset_in_seconds, resetTimerEl);
        }
        // ────────────────────────────────────────────────────────

        const solanaWalletEl = document.getElementById('solana-wallet-val');
        if (solanaWalletEl && data.solana_wallet) {
            solanaWalletEl.innerText = data.solana_wallet;
        }
        const onrampWalletEl = document.getElementById('onramp-solana-wallet');
        if (onrampWalletEl && data.solana_wallet) {
            onrampWalletEl.innerText = data.solana_wallet;
        }

        const depositRefEl = document.getElementById('user-deposit-ref');
        if (depositRefEl) {
            depositRefEl.innerText = data.is_guest ? 'REGISTER_FOR_REF' : (data.deposit_ref || 'XPK-REF');
        }
        const onrampRefEl = document.getElementById('onramp-deposit-ref');
        if (onrampRefEl) {
            onrampRefEl.innerText = data.is_guest ? 'REGISTER_FOR_REF' : (data.deposit_ref || 'XPK-REF');
        }

        // Plan Expiry Tag / Pill
        const tierExpiryEl = document.getElementById('tier-expiry');
        if (tierExpiryEl) {
            if (data.plan_expires_at && data.plan_expires_at > 0) {
                const expDate = new Date(data.plan_expires_at * 1000);
                tierExpiryEl.innerText = 'Valid until: ' + expDate.toLocaleDateString();
                tierExpiryEl.style.display = 'inline-block';
            } else {
                tierExpiryEl.style.display = 'none';
            }
        }

        // Update on-ramp fee calculator with currently selected or default amount
        const onrampAmtInput = document.getElementById('onramp-amount-input');
        if (onrampAmtInput) {
            updateOnRampCalculation(onrampAmtInput.value || 29);
        }

        // Update code snippet box
        updateSnippetDisplay();

        // Promo status
        const promoMsg = document.getElementById('promo-status-msg');
        if (promoMsg) {
            if (data.timeout_active) {
                promoMsg.innerHTML = `<span style="color: #ffe0a8; font-weight: 600;">COOLDOWN ACTIVE:</span> ${data.timeout_minutes} minutes remaining. Invite link absent from profile.`;
            } else if (data.has_promo) {
                promoMsg.innerHTML = `<span style="color: #f6b8c8; font-weight: 600;">ACTIVE PROMO:</span> 500 Credits claimed successfully.`;
            } else {
                promoMsg.innerText = data.is_guest ? 'Sign in to claim Discord promo credits' : 'Verification status: Ready';
            }
        }
    } catch (err) {
        console.error('Failed to load user profile:', err);
    }
}

// Countdown to next daily credit reset (UTC midnight)
function startResetCountdown(initialSeconds, el) {
    let remaining = initialSeconds;
    el.textContent = formatCountdown(remaining);
    const interval = setInterval(() => {
        remaining--;
        if (remaining <= 0) {
            clearInterval(interval);
            el.textContent = 'Refreshing...';
            setTimeout(loadUserProfile, 1500); // Auto-reload after reset
            return;
        }
        el.textContent = formatCountdown(remaining);
    }, 1000);
}

function formatCountdown(secs) {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}



async function logoutUser() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
        showToast('Signed out successfully. Switched to guest mode.', 'info');
        setTimeout(() => window.location.reload(), 400);
    } catch (e) {
        window.location.reload();
    }
}


// Mode specifications and descriptions
const MODE_SPECS = {
    'auto': {
        name: 'Auto Dual-Tier Mode',
        desc: '<strong>Auto Dual-Tier Mode:</strong> Tries fast 50ms TLS impersonation first. If Cloudflare Turnstile or 5s challenge is triggered, auto-escalates to Distributed Chrome CDP Solver cluster.',
        toast: 'Engine mode set: Auto Dual-Tier (Fast TLS + CDP Fallback)'
    },
    'stealth': {
        name: 'Pure CDP Stealth Mode',
        desc: '<strong>Pure CDP Stealth Mode:</strong> Direct dispatch to Chrome DevTools Protocol runners. Emulates human mouse bezier curves, solving Turnstile, DataDome, and slider captchas.',
        toast: 'Engine mode set: Pure CDP Stealth (Chrome Emulation)'
    },
    'fast': {
        name: 'Fast TLS Impersonation',
        desc: '<strong>Fast TLS Impersonation (50ms):</strong> Raw HTTP requests with Chrome 124 JA3/JA4 fingerprinting. Maximum throughput for targets without active JS challenges.',
        toast: 'Engine mode set: Fast TLS (50ms Lightweight)'
    }
};

// Mode Selector
function setMode(mode) {
    currentMode = mode;
    document.querySelectorAll('.seg-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    const info = MODE_SPECS[mode] || MODE_SPECS['auto'];
    const descEl = document.getElementById('mode-info-desc');
    if (descEl) {
        descEl.innerHTML = info.desc;
    }

    updateSnippetDisplay();
    showToast(info.toast, 'info');
}

// Multi-Language Snippet Generator (cURL, Python, Node.js)
function setSnippetLang(lang) {
    currentSnippetLang = lang;
    document.querySelectorAll('.snippet-lang-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.lang === lang);
    });
    updateSnippetDisplay();
}

function updateSnippetDisplay() {
    const displayEl = document.getElementById('snippet-code-display');
    if (!displayEl) return;

    const isGuest = !currentUser || Boolean(currentUser.is_guest);
    // GUEST RESTRICTION: Never expose API key to guests in code snippets
    const apiKey = isGuest ? 'YOUR_API_KEY_HERE' : currentUser.api_key;
    const targetUrl = (document.getElementById('target-url')?.value.trim()) || 'https://gitlab.com/users/sign_in';
    const method = (document.getElementById('target-method')?.value) || 'GET';
    const proxy = (document.getElementById('target-proxy')?.value.trim()) || '';
    const host = window.location.origin;

    if (currentSnippetLang === 'curl') {
        const proxyField = proxy ? `,\n    "proxy": "${proxy}"` : '';
        const guestComment = isGuest ? '# Note: Register at /register to unlock your personal X-API-Key\n' : '';
        displayEl.innerText = 
`${guestComment}curl -X POST "${host}/v1/unlock" \\
  -H "X-API-Key: ${apiKey}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "url": "${targetUrl}",
    "mode": "${currentMode}",
    "method": "${method}"${proxyField}
  }'`;
    } else if (currentSnippetLang === 'python') {
        const proxyParam = proxy ? `, "proxy": "${proxy}"` : '';
        const guestComment = isGuest ? '# Note: Register at /register to unlock your personal X-API-Key\n' : '';
        displayEl.innerText = 
`${guestComment}import requests

url = "${host}/v1/unlock"
headers = {
    "X-API-Key": "${apiKey}",
    "Content-Type": "application/json"
}
payload = {
    "url": "${targetUrl}",
    "mode": "${currentMode}",
    "method": "${method}"${proxyParam}
}

response = requests.post(url, headers=headers, json=payload)
data = response.json()
print("Success:", data.get("success"), "| Mode:", data.get("mode"))
print("Cookies:", len(data.get("cookies", [])))
print("Page Title:", data.get("title"))`;
    } else if (currentSnippetLang === 'node') {
        const proxyParam = proxy ? `,\n    proxy: '${proxy}'` : '';
        const guestComment = isGuest ? '// Note: Register at /register to unlock your personal X-API-Key\n' : '';
        displayEl.innerText = 
`${guestComment}const fetch = require('node-fetch'); // or native fetch in Node 18+

async function unlockTarget() {
  const response = await fetch('${host}/v1/unlock', {
    method: 'POST',
    headers: {
      'X-API-Key': '${apiKey}',
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      url: '${targetUrl}',
      mode: '${currentMode}',
      method: '${method}'${proxyParam}
    })
  });

  const data = await response.json();
  console.log('Cleared:', data.success, 'Duration:', data.duration_ms + 'ms');
  console.log('Captured Cookies:', data.cookies);
}

unlockTarget();`;
    }
}

function copySnippetCode() {
    const displayEl = document.getElementById('snippet-code-display');
    if (!displayEl) return;
    navigator.clipboard.writeText(displayEl.innerText);
    if (!currentUser || currentUser.is_guest) {
        showToast(`${currentSnippetLang.toUpperCase()} snippet copied! Register at /register to unlock your personal API key.`, 'info');
    } else {
        showToast(`${currentSnippetLang.toUpperCase()} snippet copied to clipboard.`, 'info');
    }
}

// Tab Switcher for Output
function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab-item').forEach(btn => {
        btn.classList.toggle('active', btn.innerText.toLowerCase().includes(tab));
    });

    // Toggle Netscape Export button visibility
    const netscapeBtn = document.getElementById('btn-export-netscape');
    if (netscapeBtn) {
        netscapeBtn.style.display = (tab === 'cookies') ? 'inline-flex' : 'none';
    }

    renderConsoleOutput();
}

// Export cookies in standard Netscape format for curl/wget/Playwright/yt-dlp
function exportNetscapeCookies() {
    if (!lastResponseData || !lastResponseData.cookies || lastResponseData.cookies.length === 0) {
        showToast('No clearance cookies available to export.', 'error');
        return;
    }

    let netscapeText = '# Netscape HTTP Cookie File\n# https://curl.haxx.se/docs/http-cookies.html\n# Exported from Xploit Unblocker API\n\n';
    const targetUrl = document.getElementById('target-url')?.value.trim() || '';
    let defaultDomain = 'example.com';
    try {
        defaultDomain = new URL(targetUrl).hostname;
    } catch (e) {}

    const now = Math.floor(Date.now() / 1000) + 86400 * 30; // default 30 days expiration

    lastResponseData.cookies.forEach(c => {
        const domain = c.domain ? (c.domain.startsWith('.') ? c.domain : '.' + c.domain) : '.' + defaultDomain;
        const flag = 'TRUE';
        const path = c.path || '/';
        const secure = c.secure ? 'TRUE' : 'FALSE';
        const expiration = c.expires || c.expirationDate || now;
        const name = c.name || '';
        const value = c.value || '';
        netscapeText += `${domain}\t${flag}\t${path}\t${secure}\t${Math.floor(expiration)}\t${name}\t${value}\n`;
    });

    const blob = new Blob([netscapeText], { type: 'text/plain;charset=utf-8' });
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = `cookies_${defaultDomain.replace(/[^a-zA-Z0-9.-]/g, '_')}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(downloadUrl);

    showToast('Exported Netscape cookies.txt successfully.', 'success');
}


// Poll GitHub Actions Worker Nodes Fleet Status
async function pollFleetStatus() {
    try {
        const res = await fetch('/api/workers/status');
        const data = await res.json();
        const count = data.workers_online || 0;
        
        const countEl = document.getElementById('fleet-count');
        const dotEl = document.getElementById('fleet-dot');
        const pillEl = document.getElementById('fleet-status-pill');

        if (countEl) countEl.innerText = count;
        if (dotEl) {
            dotEl.classList.toggle('online', count > 0);
        }
        if (pillEl) {
            pillEl.title = count > 0
                ? `${count} Distributed CDP solver node(s) active & ready`
                : 'Edge cluster operational. High-priority clearance ready.';
        }
    } catch (e) {
        // Silent fail on background poll
    }
}

// ══════════════════════════════════════════════════════════
//  UNIFIED 4-TAB PAYMENT CONTROLLER (Panel 3 & Modals)
// ══════════════════════════════════════════════════════════
function switchDashboardPaymentTab(tab) {
    const tabs = ['solana', 'voucher'];
    tabs.forEach(t => {
        const tabBtn = document.getElementById(`tab-${t}`);
        const viewEl = document.getElementById(`deposit-view-${t}`);
        if (tabBtn) {
            if (t === tab) tabBtn.classList.add('active');
            else tabBtn.classList.remove('active');
        }
        if (viewEl) {
            if (t === tab) viewEl.style.display = 'block';
            else viewEl.style.display = 'none';
        }
    });
}

// Backwards compatibility alias
function toggleDepositTab(tab) {
    switchDashboardPaymentTab(tab);
}

// ══════════════════════════════════════════════════════════
//  LIVE UNBLOCK EXECUTION
// ══════════════════════════════════════════════════════════
async function executeScrape() {
    const url = document.getElementById('target-url').value.trim();
    const proxyInput = document.getElementById('target-proxy');
    const proxy = proxyInput ? proxyInput.value.trim() : null;
    const btn = document.getElementById('btn-run');
    const btnText = document.getElementById('btn-run-text');
    const metricStatus = document.getElementById('metric-status');
    const metricLatency = document.getElementById('metric-latency');
    const metricBypass = document.getElementById('metric-bypass');
    const metricDebit = document.getElementById('metric-debit');
    const consoleOutput = document.getElementById('console-output');

    if (!url) {
        showToast('Please enter a target URL to process.', 'error');
        return;
    }

    // Refresh profile to prevent stale client-side credits check
    await loadUserProfile();
    if (!currentUser || Number(currentUser.credits || 0) < 1) {
        showToast('Insufficient credits. Claim 500 free requests via Discord promo or top up.', 'error');
        return;
    }

    // UI Loading state
    btn.disabled = true;
    if (btnText) btnText.innerText = 'Resolving Challenge...';
    metricStatus.className = 'cell-val text-muted';
    metricStatus.innerText = 'Connecting CDP...';
    metricLatency.innerText = 'Computing...';
    metricBypass.innerText = 'Pending';
    if (metricDebit) {
        metricDebit.textContent = getPlanDebitText(currentUser?.tier || 'free');
    }
    consoleOutput.innerHTML = `<code>// Connecting to Chrome DevTools Protocol...
// Injecting stealth anti-detection overrides...
// Generating human Bezier cursor trajectories...</code>`;

    const startTime = Date.now();
    try {
        const method = (document.getElementById('target-method')?.value) || 'GET';
        const payload = {
            url: url,
            mode: currentMode,
            method: method,
            force_cdp: currentMode === 'stealth'
        };
        if (proxy) payload.proxy = proxy;

        const reqHeaders = { 'Content-Type': 'application/json' };
        if (currentUser && !currentUser.is_guest && currentUser.api_key) {
            reqHeaders['X-API-Key'] = currentUser.api_key;
        }

        const res = await fetch('/v1/unlock', {
            method: 'POST',
            headers: reqHeaders,
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        const duration = Date.now() - startTime;
        lastResponseData = data;

        if (data.success) {
            metricStatus.className = 'cell-val status-ok';
            const nodeInfo = data.worker_node ? ` @ ${data.worker_node}` : '';
            metricStatus.innerText = `200 OK (${data.mode}${nodeInfo})`;
            metricLatency.innerText = `${data.duration_ms} ms`;
            metricBypass.innerText = 'SOLVED / CLEARED';
            if (metricDebit) {
                metricDebit.textContent = getPlanDebitText(currentUser?.tier || 'free');
            }

            renderConsoleOutput();
            loadUserProfile(); // Refresh credit count
            showToast('Challenge bypassed successfully.', 'success');
        } else {
            metricStatus.className = 'cell-val status-err';
            metricStatus.innerText = '400 Blocked';
            metricLatency.innerText = `${duration} ms`;
            metricBypass.innerText = 'FAILED';
            if (metricDebit) {
                metricDebit.textContent = '0 Solves (0 on fail)';
            }
            consoleOutput.innerHTML = `<code>// ERROR: Challenge resolution failed
// Response: ${escapeHtml(data.error || 'Challenge timeout or target refused')}</code>`;
            showToast(data.error || 'Bypass failed on target URL.', 'error');
        }
    } catch (err) {
        metricStatus.className = 'cell-val status-err';
        metricStatus.innerText = 'Network Error';
        if (metricDebit) {
            metricDebit.textContent = '0 Solves (0 on fail)';
        }
        consoleOutput.innerHTML = `<code>// Network Error: ${escapeHtml(err.message)}</code>`;
        showToast('Network error contacting backend.', 'error');
    } finally {
        btn.disabled = false;
        if (btnText) btnText.innerText = 'Run Bypass';
    }
}

function renderConsoleOutput() {
    const consoleOutput = document.getElementById('console-output');
    if (!consoleOutput) return;

    if (!lastResponseData) {
        if (currentTab === 'html') {
            consoleOutput.innerHTML = `<code>// [Decoded HTML Buffer - Standby]
// Enter target URL above and click "Run Bypass".
// The solver extracts the complete post-clearance DOM and renders it here.</code>`;
        } else if (currentTab === 'cookies') {
            consoleOutput.innerHTML = `<code>// [Clearance Cookies Buffer - Standby]
// Post-challenge clearance cookies (cf_clearance, __cf_bm, session tokens)
// captured from the browser context will be formatted as JSON here.</code>`;
        } else if (currentTab === 'headers') {
            consoleOutput.innerHTML = `<code>// [Response Headers Buffer - Standby]
// Target host HTTP response headers (Cloudflare Ray-ID, Server, Cache status)
// returned upon successful bypass will appear here.</code>`;
        }
        return;
    }

    if (currentTab === 'html') {
        const preview = lastResponseData.html ? lastResponseData.html.slice(0, 4500) : '// No HTML content captured';
        consoleOutput.innerHTML = `<code>${escapeHtml(preview)}\n\n// [...Truncated display. Total extracted payload: ${lastResponseData.html ? lastResponseData.html.length : 0} characters]</code>`;
    } else if (currentTab === 'cookies') {
        const cookies = lastResponseData.cookies && lastResponseData.cookies.length > 0
            ? JSON.stringify(lastResponseData.cookies, null, 2)
            : '// No clearance cookies captured for this request';
        consoleOutput.innerHTML = `<code>${escapeHtml(cookies)}</code>`;
    } else if (currentTab === 'headers') {
        const headers = lastResponseData.headers && Object.keys(lastResponseData.headers).length > 0
            ? JSON.stringify(lastResponseData.headers, null, 2)
            : '// No headers captured for this request';
        consoleOutput.innerHTML = `<code>${escapeHtml(headers)}</code>`;
    }
}

function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function setStatusMessage(el, text, color = '#f6b8c8', fontWeight = '600') {
    if (!el) return;
    const span = document.createElement('span');
    span.style.color = color;
    span.style.fontWeight = fontWeight;
    span.textContent = text || '';
    el.replaceChildren(span);
}

// ══════════════════════════════════════════════════════════
//  DISCORD PROMO VERIFIER
// ══════════════════════════════════════════════════════════
async function verifyPromo() {
    const btn = document.getElementById('btn-verify-promo');
    const btnText = document.getElementById('btn-promo-text');
    const msg = document.getElementById('promo-status-msg');

    btn.disabled = true;
    if (btnText) btnText.innerText = 'Checking Discord Profile...';

    try {
        const res = await fetch('/api/user/promo/verify', { method: 'POST' });
        const data = await res.json();

        if (data.success) {
            setStatusMessage(msg, data.message, '#f6b8c8');
            showToast(data.message, 'success');
        } else {
            setStatusMessage(msg, data.message, '#ffe0a8');
            showToast(data.message, 'error');
        }
        loadUserProfile();
    } catch (e) {
        showToast('Verification error: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        if (btnText) btnText.innerText = 'Verify Discord Profile';
    }
}

// ══════════════════════════════════════════════════════════
//  SOLANA DEPOSIT VERIFIER
// ══════════════════════════════════════════════════════════
async function verifyDeposit() {
    const txHash = document.getElementById('tx-hash-input').value.trim();
    const msg = document.getElementById('deposit-msg');

    if (!txHash) {
        showToast('Please provide a valid Solana transaction signature.', 'error');
        return;
    }

    setStatusMessage(msg, 'Verifying confirmation on Solana mainnet RPC...', '#b9bfe6');
    try {
        const res = await fetch('/api/deposit/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tx_hash: txHash })
        });
        const data = await res.json();

        if (data.success) {
            setStatusMessage(msg, data.message, '#f6b8c8');
            document.getElementById('tx-hash-input').value = '';
            loadUserProfile();
            showToast(data.message, 'success');
        } else {
            setStatusMessage(msg, data.error, '#ff8a8a');
            showToast(data.error, 'error');
        }
    } catch (e) {
        msg.innerText = 'Network error: ' + e.message;
        showToast('Failed to reach Solana validator: ' + e.message, 'error');
    }
}

// ══════════════════════════════════════════════════════════
//  VOUCHER REDEMPTION & INSTANT PLAN UPGRADE
// ══════════════════════════════════════════════════════════
let isVoucherRedeeming = false;

async function redeemVoucherCode(inputId = 'voucher-code-input', msgId = 'deposit-msg') {
    if (isVoucherRedeeming) return;

    const inputEl = document.getElementById(inputId);
    const msg = document.getElementById(msgId);
    if (!inputEl) return;
    const code = inputEl.value.trim().toUpperCase();

    if (!code) {
        showToast('Please enter a voucher or gift code.', 'error');
        return;
    }

    isVoucherRedeeming = true;
    inputEl.disabled = true;

    // Disable associated trigger buttons
    const targetBtns = Array.from(document.querySelectorAll(`button[onclick*="${inputId}"], button[onclick*="redeemVoucherCode"]`)).concat(
        inputEl.parentElement ? Array.from(inputEl.parentElement.querySelectorAll('button')) : []
    );
    const uniqueBtns = Array.from(new Set(targetBtns));
    uniqueBtns.forEach(btn => btn.disabled = true);

    if (msg) {
        msg.className = 'voucher-feedback-box loading';
        msg.style.display = 'flex';
        msg.innerHTML = `
            <svg class="spin-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>
            <span>Validating voucher signature...</span>
        `;
    }

    try {
        const res = await fetch('/api/voucher/redeem', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: code })
        });
        const data = await res.json();

        if (data.success) {
            inputEl.value = '';
            const planUpgraded = data.plan ? String(data.plan).toUpperCase() : null;
            const creditsAdded = Number(data.credits_added || 0).toLocaleString();
            const duration = Number(data.duration_days || 30);
            const slots = Number(data.concurrency_limit || 10);

            let feedbackHtml = `
                <div style="display:flex;align-items:flex-start;gap:8px;">
                    <span style="font-size:16px;color:var(--text-ok);">✓</span>
                    <div>
                        <strong style="color:var(--text-ok);">Voucher Activated Successfully!</strong><br>
                        ${planUpgraded ? `Upgraded to <strong style="color:#ffffff;">${planUpgraded}</strong> (${duration} days validity, ${slots} concurrent slots).<br>` : ''}
                        <span>+${creditsAdded} solves credited to your account balance.</span>
                    </div>
                </div>
            `;
            if (msg) {
                msg.className = 'voucher-feedback-box success';
                msg.style.display = 'flex';
                msg.innerHTML = feedbackHtml;
            }
            showToast(data.message || `+${creditsAdded} solves credited!`, 'success');
            await loadUserProfile();
        } else {
            const errMsg = data.detail || data.error || 'Failed to redeem voucher.';
            if (msg) {
                msg.className = 'voucher-feedback-box error';
                msg.style.display = 'flex';
                msg.innerHTML = `<span style="font-size:16px;color:var(--text-danger);">✕</span><span>${escapeHtml(errMsg)}</span>`;
            }
            showToast(errMsg, 'error');
        }
    } catch (e) {
        if (msg) {
            msg.className = 'voucher-feedback-box error';
            msg.style.display = 'flex';
            msg.innerHTML = `<span style="font-size:16px;color:var(--text-danger);">✕</span><span>Network error: ${escapeHtml(e.message)}</span>`;
        }
        showToast('Error validating voucher code.', 'error');
    } finally {
        isVoucherRedeeming = false;
        inputEl.disabled = false;
        uniqueBtns.forEach(btn => btn.disabled = false);
    }
}

// ══════════════════════════════════════════════════════════
//  ON-RAMP & SELLIX CHECKOUT CONTROLLERS
// ══════════════════════════════════════════════════════════






function openOnRampModal(amount = 29, planName = 'Moderato ($29/mo)') {
    const modal = document.getElementById('modal-onramp');
    if (!modal) return;
    const input = document.getElementById('onramp-amount-input');
    if (input) input.value = amount;
    const nameEl = document.getElementById('onramp-target-title');
    if (nameEl) nameEl.innerText = planName;
    updateOnRampCalculation(amount);
    modal.style.display = 'flex'; modal.classList.add('open');
}

function closeOnRampModal() {
    const modal = document.getElementById('modal-onramp');
    if (modal) modal.style.display = 'none'; modal.classList.remove('open');
}

function openVoucherModal() {
    const modal = document.getElementById('modal-voucher-redeem');
    if (modal) modal.style.display = 'flex'; modal.classList.add('open');
    const input = document.getElementById('modal-voucher-input');
    if (input) setTimeout(() => input.focus(), 50);
}

function closeVoucherModal() {
    const modal = document.getElementById('modal-voucher-redeem');
    if (modal) modal.style.display = 'none'; modal.classList.remove('open');
}

// Global modal keyboard navigation (Escape to close, Enter to submit)
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeOnRampModal();
        closeVoucherModal();
        const openModals = document.querySelectorAll('.sovereign-modal-backdrop.open');
        openModals.forEach(m => m.classList.remove('open'));
    }
});

// ══════════════════════════════════════════════════════════
//  CLIPBOARD & UTILITY HELPERS
// ══════════════════════════════════════════════════════════
function toggleApiKeyVisibility() {
    const input = document.getElementById('api-key-val');
    const eyeBtn = document.getElementById('btn-toggle-key');
    if (!input) return;
    const isPass = input.type === 'password';
    input.type = isPass ? 'text' : 'password';
    if (eyeBtn) {
        if (isPass) {
            eyeBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                <line x1="1" y1="1" x2="23" y2="23"></line>
            </svg>`;
        } else {
            eyeBtn.innerHTML = `<svg id="svg-eye" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                <circle cx="12" cy="12" r="3"></circle>
            </svg>`;
        }
    }
}

function copyApiKey() {
    const key = document.getElementById('api-key-val').value;
    navigator.clipboard.writeText(key);
    showToast('API Key copied to clipboard.', 'info');
}

async function regenerateApiKey() {
    if (!confirm('Regenerate secret API key? Any active scripts or bots using the current key will be revoked immediately.')) {
        return;
    }
    try {
        const res = await fetch('/api/user/regenerate-key', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            document.getElementById('api-key-val').value = data.api_key;
            if (currentUser) currentUser.api_key = data.api_key;
            updateSnippetDisplay();
            showToast('New API Key generated & saved to database.', 'success');
        } else {
            showToast(data.error || 'Failed to regenerate API key.', 'error');
        }
    } catch (e) {
        showToast('Error regenerating key: ' + e.message, 'error');
    }
}


function copyPromoLink() {
    const link = document.getElementById('promo-link-text').innerText;
    navigator.clipboard.writeText(link);
    showToast('Invite link copied. Add to your Discord Bio or Custom Status.', 'info');
}

function copySolanaWallet() {
    const wallet = document.getElementById('solana-wallet-val').innerText;
    navigator.clipboard.writeText(wallet);
    showToast('Solana Treasury Wallet copied to clipboard.', 'info');
}

function copyDepositRef() {
    const ref = document.getElementById('user-deposit-ref').innerText;
    navigator.clipboard.writeText(ref);
    showToast('Deposit Reference ID copied.', 'info');
}

function copyCurlSnippet() {
    const snippetEl = document.getElementById('snippet-code-display') || document.getElementById('curl-snippet');
    if (!snippetEl) return;
    const code = snippetEl.innerText;
    navigator.clipboard.writeText(code);
    showToast('Code snippet copied to clipboard.', 'info');
}

function copyConsoleOutput() {
    if (!lastResponseData) return;
    navigator.clipboard.writeText(lastResponseData.html || '');
    showToast('Terminal buffer copied to clipboard.', 'info');
}
