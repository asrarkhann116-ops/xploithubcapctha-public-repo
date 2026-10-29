// ══════════════════════════════════════════════════════════
//  XPLOIT UNBLOCKER — DEVELOPER CONSOLE CLIENT CONTROLLER
//  Aesthetic: Human Developer Standards (Zero Emojis, Pure SVGs)
// ══════════════════════════════════════════════════════════

let currentUser = null;
let currentMode = 'auto';
let currentTab = 'html';
let lastResponseData = null;

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    loadUserProfile();
});

// Toast System (Clean, non-intrusive notification replacing alert)
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    let iconSvg = '';
    if (type === 'success') {
        iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
    } else if (type === 'error') {
        iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`;
    } else {
        iconSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`;
    }

    toast.innerHTML = `${iconSvg}<span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.2s';
        setTimeout(() => toast.remove(), 250);
    }, 3500);
}

// Load User Profile & State
async function loadUserProfile() {
    try {
        const res = await fetch('/api/user/me');
        const data = await res.json();
        currentUser = data;

        // Navbar & Profile Info
        const usernameEl = document.getElementById('nav-username');
        if (usernameEl) usernameEl.innerText = data.username || 'Guest Operator';

        const creditsEl = document.getElementById('nav-credits');
        if (creditsEl) creditsEl.innerText = Number(data.credits).toFixed(1);

        const apiKeyEl = document.getElementById('api-key-val');
        if (apiKeyEl) apiKeyEl.value = data.api_key;

        const solanaWalletEl = document.getElementById('solana-wallet-val');
        if (solanaWalletEl && data.solana_wallet) {
            solanaWalletEl.innerText = data.solana_wallet;
        }

        const depositRefEl = document.getElementById('user-deposit-ref');
        if (depositRefEl && data.deposit_ref) {
            depositRefEl.innerText = data.deposit_ref;
        }
        
        // Update cURL snippet
        const curlSnippetEl = document.getElementById('curl-snippet');
        if (curlSnippetEl) {
            curlSnippetEl.innerText = 
`curl -X POST "http://localhost:8000/v1/unlock" \\
  -H "X-API-Key: ${data.api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{"url": "https://gitlab.com/users/sign_in", "mode": "auto"}'`;
        }

        // Promo status
        const promoMsg = document.getElementById('promo-status-msg');
        if (promoMsg) {
            if (data.timeout_active) {
                promoMsg.innerHTML = `<span style="color: #f59e0b; font-weight: 600;">COOLDOWN ACTIVE:</span> ${data.timeout_minutes} minutes remaining. Invite link absent from profile.`;
            } else if (data.has_promo) {
                promoMsg.innerHTML = `<span style="color: #10b981; font-weight: 600;">ACTIVE PROMO:</span> 500 Credits claimed successfully.`;
            } else {
                promoMsg.innerText = 'Verification status: Ready';
            }
        }
    } catch (err) {
        console.error('Failed to load user profile:', err);
    }
}

// Mode Selector
function setMode(mode) {
    currentMode = mode;
    document.querySelectorAll('.seg-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
}

// Tab Switcher for Output
function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab-item').forEach(btn => {
        btn.classList.toggle('active', btn.innerText.toLowerCase().includes(tab));
    });
    renderConsoleOutput();
}

// Deposit Tab Switcher (Solana vs Voucher)
function toggleDepositTab(tab) {
    const solanaTab = document.getElementById('tab-solana');
    const voucherTab = document.getElementById('tab-voucher');
    const solanaView = document.getElementById('deposit-view-solana');
    const voucherView = document.getElementById('deposit-view-voucher');

    if (tab === 'solana') {
        solanaTab.classList.add('active');
        voucherTab.classList.remove('active');
        solanaView.style.display = 'block';
        voucherView.style.display = 'none';
    } else {
        voucherTab.classList.add('active');
        solanaTab.classList.remove('active');
        voucherView.style.display = 'block';
        solanaView.style.display = 'none';
    }
}

// ══════════════════════════════════════════════════════════
//  LIVE UNBLOCK EXECUTION
// ══════════════════════════════════════════════════════════
async function executeScrape() {
    const url = document.getElementById('target-url').value.trim();
    const btn = document.getElementById('btn-run');
    const btnText = document.getElementById('btn-run-text');
    const metricStatus = document.getElementById('metric-status');
    const metricLatency = document.getElementById('metric-latency');
    const metricBypass = document.getElementById('metric-bypass');
    const consoleOutput = document.getElementById('console-output');

    if (!url) {
        showToast('Please enter a target URL to process.', 'error');
        return;
    }

    if (!currentUser || currentUser.credits < 1) {
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
    consoleOutput.innerHTML = `<code>// Connecting to Chrome DevTools Protocol...
// Injecting stealth anti-detection overrides...
// Emulating natural cursor trajectories and Turnstile clearance...</code>`;

    const startTime = Date.now();
    try {
        const res = await fetch('/v1/unlock', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': currentUser.api_key
            },
            body: JSON.stringify({
                url: url,
                mode: currentMode,
                force_cdp: currentMode === 'stealth'
            })
        });

        const data = await res.json();
        const duration = Date.now() - startTime;
        lastResponseData = data;

        if (data.success) {
            metricStatus.className = 'cell-val status-ok';
            metricStatus.innerText = `200 OK (${data.mode})`;
            metricLatency.innerText = `${data.duration_ms} ms`;
            metricBypass.innerText = 'SOLVED / CLEARED';

            renderConsoleOutput();
            loadUserProfile(); // Refresh credit count
            showToast('Challenge bypassed successfully.', 'success');
        } else {
            metricStatus.className = 'cell-val status-err';
            metricStatus.innerText = '400 Blocked';
            metricLatency.innerText = `${duration} ms`;
            metricBypass.innerText = 'FAILED';
            consoleOutput.innerHTML = `<code>// ERROR: Challenge resolution failed
// Response: ${data.error || 'Challenge timeout or target refused'}</code>`;
            showToast(data.error || 'Bypass failed on target URL.', 'error');
        }
    } catch (err) {
        metricStatus.className = 'cell-val status-err';
        metricStatus.innerText = 'Network Error';
        consoleOutput.innerHTML = `<code>// Network Error: ${err.message}</code>`;
        showToast('Network error contacting backend.', 'error');
    } finally {
        btn.disabled = false;
        if (btnText) btnText.innerText = 'Run Bypass';
    }
}

function renderConsoleOutput() {
    const consoleOutput = document.getElementById('console-output');
    if (!lastResponseData) return;

    if (currentTab === 'html') {
        const preview = lastResponseData.html ? lastResponseData.html.slice(0, 4500) : '// No HTML content captured';
        consoleOutput.innerHTML = `<code>${escapeHtml(preview)}\n\n// [...Truncated display. Total extracted payload: ${lastResponseData.html ? lastResponseData.html.length : 0} characters]</code>`;
    } else if (currentTab === 'cookies') {
        const cookies = lastResponseData.cookies ? JSON.stringify(lastResponseData.cookies, null, 2) : '// No clearance cookies captured';
        consoleOutput.innerHTML = `<code>${escapeHtml(cookies)}</code>`;
    } else if (currentTab === 'headers') {
        const headers = lastResponseData.headers ? JSON.stringify(lastResponseData.headers, null, 2) : '// No headers captured';
        consoleOutput.innerHTML = `<code>${escapeHtml(headers)}</code>`;
    }
}

function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
            msg.innerHTML = `<span style="color: #10b981; font-weight: 600;">${data.message}</span>`;
            showToast(data.message, 'success');
        } else {
            msg.innerHTML = `<span style="color: #f59e0b; font-weight: 600;">${data.message}</span>`;
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

    msg.innerHTML = '<span style="color: #94a3b8;">Verifying confirmation on Solana mainnet RPC...</span>';
    try {
        const res = await fetch('/api/deposit/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tx_hash: txHash })
        });
        const data = await res.json();

        if (data.success) {
            msg.innerHTML = `<span style="color: #10b981; font-weight: 600;">${data.message}</span>`;
            document.getElementById('tx-hash-input').value = '';
            loadUserProfile();
            showToast(data.message, 'success');
        } else {
            msg.innerHTML = `<span style="color: #ef4444; font-weight: 600;">${data.error}</span>`;
            showToast(data.error, 'error');
        }
    } catch (e) {
        msg.innerText = 'Network error: ' + e.message;
        showToast('Failed to reach Solana validator: ' + e.message, 'error');
    }
}

// ══════════════════════════════════════════════════════════
//  VOUCHER REDEMPTION
// ══════════════════════════════════════════════════════════
async function redeemVoucherCode() {
    const code = document.getElementById('voucher-code-input').value.trim();
    const msg = document.getElementById('deposit-msg');

    if (!code) {
        showToast('Please enter a voucher or gift code.', 'error');
        return;
    }

    msg.innerHTML = '<span style="color: #94a3b8;">Validating code...</span>';
    try {
        const res = await fetch('/api/voucher/redeem', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: code })
        });
        const data = await res.json();

        if (data.success) {
            msg.innerHTML = `<span style="color: #10b981; font-weight: 600;">${data.message}</span>`;
            document.getElementById('voucher-code-input').value = '';
            loadUserProfile();
            showToast(data.message, 'success');
        } else {
            msg.innerHTML = `<span style="color: #ef4444; font-weight: 600;">${data.error}</span>`;
            showToast(data.error, 'error');
        }
    } catch (e) {
        msg.innerText = 'Network error: ' + e.message;
        showToast('Error validating voucher code.', 'error');
    }
}

// ══════════════════════════════════════════════════════════
//  CLIPBOARD & UTILITY HELPERS
// ══════════════════════════════════════════════════════════
function toggleApiKeyVisibility() {
    const input = document.getElementById('api-key-val');
    input.type = input.type === 'password' ? 'text' : 'password';
}

function copyApiKey() {
    const key = document.getElementById('api-key-val').value;
    navigator.clipboard.writeText(key);
    showToast('API Key copied to clipboard.', 'info');
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
    const code = document.getElementById('curl-snippet').innerText;
    navigator.clipboard.writeText(code);
    showToast('cURL snippet copied to clipboard.', 'info');
}

function copyConsoleOutput() {
    if (!lastResponseData) return;
    navigator.clipboard.writeText(lastResponseData.html || '');
    showToast('Terminal buffer copied to clipboard.', 'info');
}
