// WebAuthn / Passkeys — Ludus Party Planner
// Uses the Web Authentication API and communicates with the server
// using base64url-encoded binary fields (as emitted by py_webauthn).

function bufferToBase64url(buffer) {
    const bytes = new Uint8Array(buffer);
    let str = '';
    for (const b of bytes) str += String.fromCharCode(b);
    return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

function base64urlToBuffer(base64url) {
    const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64.padEnd(base64.length + (4 - base64.length % 4) % 4, '=');
    const binary = atob(padded);
    const buf = new ArrayBuffer(binary.length);
    const bytes = new Uint8Array(buf);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return buf;
}

// Fields that must stay as strings (not converted to ArrayBuffer).
const _STRING_FIELDS = new Set([
    'type', 'alg', 'attestation', 'authenticatorAttachment',
    'residentKey', 'userVerification', 'rpId', 'fmt',
]);

// Recursively decode base64url strings in a WebAuthn options object to ArrayBuffers.
// Only converts values that look like binary data (non-empty strings in known-binary positions).
function _decodeOptions(obj, key) {
    if (obj === null || obj === undefined) return obj;
    if (typeof obj === 'number' || typeof obj === 'boolean') return obj;
    if (typeof obj === 'string') {
        // Keep string-typed fields as strings; convert binary fields to ArrayBuffer.
        if (key && _STRING_FIELDS.has(key)) return obj;
        if (obj.length === 0) return obj;
        try { return base64urlToBuffer(obj); } catch (_) { return obj; }
    }
    if (Array.isArray(obj)) return obj.map(function (item) { return _decodeOptions(item, null); });
    if (typeof obj === 'object') {
        const result = {};
        for (const k of Object.keys(obj)) result[k] = _decodeOptions(obj[k], k);
        return result;
    }
    return obj;
}

function _showError(id, msg) {
    const el = document.getElementById(id);
    if (el) { el.textContent = msg; el.classList.remove('hidden'); }
}

// ---------- Registration (from profile page) ----------

async function registerPasskey(deviceName) {
    try {
        const optResp = await fetch('/auth/passkey/register/begin');
        if (!optResp.ok) { _showError('passkey-error', 'Server error starting registration.'); return; }
        const opts = await optResp.json();
        const decoded = _decodeOptions(opts, null);

        const credential = await navigator.credentials.create({ publicKey: decoded });
        if (!credential) { _showError('passkey-error', 'Passkey creation was cancelled.'); return; }

        const payload = {
            id: credential.id,
            rawId: bufferToBase64url(credential.rawId),
            type: credential.type,
            device_name: deviceName || '',
            response: {
                clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
                attestationObject: bufferToBase64url(credential.response.attestationObject),
            },
        };

        const verResp = await fetch('/auth/passkey/register/complete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await verResp.json();
        if (result.ok) { location.reload(); }
        else { _showError('passkey-error', result.error || 'Registration failed.'); }
    } catch (e) {
        _showError('passkey-error', e.message || 'An error occurred.');
    }
}

// ---------- Authentication (from login page) ----------

async function loginWithPasskey() {
    try {
        const optResp = await fetch('/auth/passkey/login/begin');
        if (!optResp.ok) { _showError('passkey-error', 'Server error starting login.'); return; }
        const opts = await optResp.json();
        const decoded = _decodeOptions(opts, null);

        const assertion = await navigator.credentials.get({ publicKey: decoded });
        if (!assertion) { _showError('passkey-error', 'Passkey login was cancelled.'); return; }

        const payload = {
            id: assertion.id,
            rawId: bufferToBase64url(assertion.rawId),
            type: assertion.type,
            response: {
                clientDataJSON: bufferToBase64url(assertion.response.clientDataJSON),
                authenticatorData: bufferToBase64url(assertion.response.authenticatorData),
                signature: bufferToBase64url(assertion.response.signature),
                userHandle: assertion.response.userHandle
                    ? bufferToBase64url(assertion.response.userHandle) : null,
            },
        };

        const verResp = await fetch('/auth/passkey/login/complete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await verResp.json();
        if (result.ok) { window.location.href = result.redirect; }
        else { _showError('passkey-error', result.error || 'Login failed.'); }
    } catch (e) {
        _showError('passkey-error', e.message || 'An error occurred.');
    }
}
