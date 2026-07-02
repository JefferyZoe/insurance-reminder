var ENCRYPTED_DATA = "__ENCRYPTED_DATA__";

async function decrypt() {
    var password = document.getElementById('password-input').value;
    if (!password) return;
    try {
        var packed = Uint8Array.from(atob(ENCRYPTED_DATA), function(c) { return c.charCodeAt(0); });
        var salt = packed.slice(0, 16);
        var iv = packed.slice(16, 28);
        var ciphertext = packed.slice(28);

        var encoder = new TextEncoder();
        var keyMaterial = await crypto.subtle.importKey('raw', encoder.encode(password), 'PBKDF2', false, ['deriveKey']);
        var key = await crypto.subtle.deriveKey(
            { name: 'PBKDF2', salt: salt, iterations: 10000, hash: 'SHA-256' },
            keyMaterial,
            { name: 'AES-GCM', length: 256 },
            false,
            ['decrypt']
        );
        var decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: iv }, key, ciphertext);
        var decoder = new TextDecoder('utf-8', { fatal: true });
        var html = decoder.decode(decrypted);
        if (html.indexOf('<') === -1) throw new Error('invalid');

        document.getElementById('login-screen').style.display = 'none';
        document.getElementById('main-content').innerHTML = html;
        document.getElementById('main-content').style.display = 'block';
    } catch (e) {
        document.getElementById('error-msg').style.display = 'block';
        document.getElementById('password-input').value = '';
        document.getElementById('password-input').focus();
    }
}

function filterMonth(month, e) {
    e.preventDefault();
    e.stopPropagation();
    document.querySelectorAll('#tab-payment .monthly-tag').forEach(function(tag) { tag.classList.remove('active'); });
    e.target.classList.add('active');
    document.querySelectorAll('#tab-payment table tbody tr').forEach(function(row) {
        if (month === 0) { row.style.display = ''; }
        else { row.style.display = (parseInt(row.getAttribute('data-month')) === month) ? '' : 'none'; }
    });
}

function filterCashYear(year, e) {
    if (e) { e.preventDefault(); e.stopPropagation(); }
    if (!year || isNaN(year)) return;
    // 同步下拉框
    var sel = document.getElementById('year-select');
    if (sel) sel.value = year;
    // 切换按钮 active
    document.querySelectorAll('.monthly-tag').forEach(function(tag) {
        tag.classList.toggle('active', tag.textContent == year);
    });
    // 切换数据块
    document.querySelectorAll('.cash-year-block').forEach(function(block) {
        block.style.display = (parseInt(block.getAttribute('data-cash-year')) === year) ? '' : 'none';
    });
}


function switchTab(tab, e) {
    e.preventDefault();
    document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
    e.target.classList.add('active');
    document.querySelectorAll('.tab-content').forEach(function(c) { c.style.display = 'none'; });
    document.getElementById('tab-' + tab).style.display = '';
}
