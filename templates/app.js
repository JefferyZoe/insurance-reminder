var ENCRYPTED_DATA = "__ENCRYPTED_DATA__";
var userPassword = '';
var currentPages = 0;
var currentPage = 1;
var currentPolicyId = '';

async function decryptData(encryptedBase64, password) {
    var packed = Uint8Array.from(atob(encryptedBase64), function(c) { return c.charCodeAt(0); });
    var salt = packed.slice(0, 16);
    var ciphertext = packed.slice(16);
    var encoder = new TextEncoder();
    var keyMaterial = await crypto.subtle.importKey('raw', encoder.encode(password), 'PBKDF2', false, ['deriveBits']);
    var derivedBits = await crypto.subtle.deriveBits({ name: 'PBKDF2', salt: salt, iterations: 10000, hash: 'SHA-256' }, keyMaterial, 256);
    var key = new Uint8Array(derivedBits);
    var numBlocks = Math.ceil(ciphertext.length / 32);
    var keyStream = new Uint8Array(numBlocks * 32);
    var batchSize = 256;
    for (var bStart = 0; bStart < numBlocks; bStart += batchSize) {
        var bEnd = Math.min(bStart + batchSize, numBlocks);
        var promises = [];
        for (var i = bStart; i < bEnd; i++) {
            var counterBytes = new Uint8Array(4);
            new DataView(counterBytes.buffer).setUint32(0, i, false);
            var blockInput = new Uint8Array(36);
            blockInput.set(key);
            blockInput.set(counterBytes, 32);
            promises.push(crypto.subtle.digest('SHA-256', blockInput));
        }
        var results = await Promise.all(promises);
        for (var r = 0; r < results.length; r++) {
            keyStream.set(new Uint8Array(results[r]), (bStart + r) * 32);
        }
    }
    var decrypted = new Uint8Array(ciphertext.length);
    for (var j = 0; j < ciphertext.length; j++) {
        decrypted[j] = ciphertext[j] ^ keyStream[j];
    }
    return decrypted;
}

async function decrypt() {
    var password = document.getElementById('password-input').value;
    if (!password) return;
    try {
        var decryptedBytes = await decryptData(ENCRYPTED_DATA, password);
        var decoder = new TextDecoder('utf-8', { fatal: true });
        var html = decoder.decode(decryptedBytes);
        if (html.indexOf('<') === -1) throw new Error('invalid');
        userPassword = password;
        document.getElementById('login-screen').style.display = 'none';
        document.getElementById('main-content').innerHTML = html;
        document.getElementById('main-content').style.display = 'block';
    } catch (e) {
        document.getElementById('error-msg').style.display = 'block';
        document.getElementById('password-input').value = '';
        document.getElementById('password-input').focus();
    }
}

async function viewPolicy(policyId, pages) {
    var btn = event.target;
    btn.disabled = true;
    btn.textContent = '\u23f3 加载中...';
    try {
        currentPolicyId = policyId;
        currentPages = pages;
        currentPage = 1;
        document.getElementById('pdf-container').innerHTML = '';
        updatePageInfo();
        await renderCurrentPage();
        document.getElementById('pdf-modal').classList.add('active');
    } catch (e) {
        console.error(e);
        alert('文件加载失败: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '查看';
    }
}

async function renderCurrentPage() {
    var container = document.getElementById('pdf-container');
    container.innerHTML = '<p style="color:#fff;">加载中...</p>';
    var url = 'pdfs/' + currentPolicyId + '_p' + currentPage + '.enc';
    var resp = await fetch(url);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var encryptedBase64 = await resp.text();
    var decryptedBytes = await decryptData(encryptedBase64, userPassword);
    var binary = '';
    var chunkSize = 8192;
    for (var i = 0; i < decryptedBytes.length; i += chunkSize) {
        var chunk = decryptedBytes.subarray(i, i + chunkSize);
        binary += String.fromCharCode.apply(null, chunk);
    }
    var imgBase64 = btoa(binary);
    container.innerHTML = '<img src="data:image/jpeg;base64,' + imgBase64 + '" style="max-width:100%;height:auto;">';
    updatePageInfo();
}

function updatePageInfo() {
    var el = document.getElementById('page-info');
    if (el) el.textContent = currentPage + '/' + currentPages;
}

function prevPage() {
    if (currentPage <= 1) return;
    currentPage--;
    renderCurrentPage();
}

function nextPage() {
    if (currentPage >= currentPages) return;
    currentPage++;
    renderCurrentPage();
}

function closePdfModal() {
    document.getElementById('pdf-modal').classList.remove('active');
    document.getElementById('pdf-container').innerHTML = '';
}

async function downloadPolicy(policyId) {
    var btn = event.target;
    btn.disabled = true;
    btn.textContent = '\u23f3 下载中...';
    try {
        var resp = await fetch('pdfs/' + policyId + '.enc');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        var encryptedBase64 = await resp.text();
        var decryptedBytes = await decryptData(encryptedBase64, userPassword);
        var blob = new Blob([decryptedBytes], { type: 'application/pdf' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = policyId + '.pdf';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (e) {
        console.error(e);
        alert('下载失败: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '下载';
    }
}

function closeModal(e) {
    if (e.target === e.currentTarget) closePdfModal();
}

function filterMonth(month, e) {
    e.preventDefault();
    e.stopPropagation();
    document.querySelectorAll('.monthly-tag').forEach(function(tag) { tag.classList.remove('active'); });
    e.target.classList.add('active');
    document.querySelectorAll('table tbody tr').forEach(function(row) {
        if (month === 0) { row.style.display = ''; }
        else { row.style.display = (parseInt(row.getAttribute('data-month')) === month) ? '' : 'none'; }
    });
}
