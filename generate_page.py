#!/usr/bin/env python3
"""
生成保单详情 HTML 页面（带密码保护），部署到 GitHub Pages。
PDF 文件单独加密存储为独立文件，使用 PDF.js 在手机端渲染。
"""
import json
import os
import datetime
import hashlib
import secrets
import base64

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "insurance_data.json")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "docs")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

PAGE_PASSWORD = os.environ.get('PAGE_PASSWORD', '123456')
POLICY_FILES_DIR = os.environ.get('POLICY_FILES_DIR', os.path.join(SCRIPT_DIR, "policy_files"))


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_next_due_date(first_insure_date_str, pay_period_years):
    first_date = datetime.datetime.strptime(first_insure_date_str, "%Y-%m-%d").date()
    today = datetime.date.today()
    end_year = first_date.year + pay_period_years - 1
    for year in range(first_date.year + 1, end_year + 1):
        try:
            due_date = first_date.replace(year=year)
        except ValueError:
            due_date = first_date.replace(year=year, day=28)
        if due_date >= today:
            return due_date
    return None


def calculate_installment_info(first_insure_date_str, pay_period_years, due_date):
    first_date = datetime.datetime.strptime(first_insure_date_str, "%Y-%m-%d").date()
    current_installment = due_date.year - first_date.year + 1
    paid_installments = current_installment - 1
    return paid_installments, current_installment, pay_period_years


def encrypt_content(plaintext, password):
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 10000, dklen=32)
    plaintext_bytes = plaintext.encode('utf-8')
    length = len(plaintext_bytes)
    key_stream = bytearray()
    counter = 0
    while len(key_stream) < length:
        block = hashlib.sha256(key + counter.to_bytes(4, 'big')).digest()
        key_stream.extend(block)
        counter += 1
    encrypted = bytearray(length)
    for i in range(length):
        encrypted[i] = plaintext_bytes[i] ^ key_stream[i]
    packed = bytes(salt) + bytes(encrypted)
    return base64.b64encode(packed).decode('ascii')


def encrypt_file_to_output(filepath, password, output_path):
    with open(filepath, "rb") as f:
        data = f.read()
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 10000, dklen=32)
    length = len(data)
    key_stream = bytearray()
    counter = 0
    while len(key_stream) < length:
        block = hashlib.sha256(key + counter.to_bytes(4, 'big')).digest()
        key_stream.extend(block)
        counter += 1
    encrypted = bytearray(length)
    for i in range(length):
        encrypted[i] = data[i] ^ key_stream[i]
    packed = bytes(salt) + bytes(encrypted)
    with open(output_path, "w", encoding="ascii") as f:
        f.write(base64.b64encode(packed).decode('ascii'))
    return len(data)


def convert_pdf_to_images(filepath, pdf_password=None):
    """将 PDF 转换为 JPEG 图片列表（每页一张），返回 [(page_num, jpeg_bytes), ...]"""
    try:
        import fitz  # PyMuPDF
        # 用二进制方式读取避免路径编码问题
        with open(filepath, "rb") as f:
            pdf_data = f.read()
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        if doc.is_encrypted:
            if pdf_password:
                if not doc.authenticate(pdf_password):
                    # 尝试空密码
                    if not doc.authenticate(""):
                        print(f"  ❌ PDF 密码错误: {os.path.basename(filepath)}")
                        doc.close()
                        return []
            else:
                # 尝试空密码解锁（部分 PDF 只有 owner password 没有 user password）
                if not doc.authenticate(""):
                    print(f"  ❌ PDF 需要密码但未提供: {os.path.basename(filepath)}")
                    doc.close()
                    return []
        result = []
        for i, page in enumerate(doc):
            # 2x 缩放确保清晰
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            result.append((i + 1, pix.tobytes("jpeg")))
        doc.close()
        return result
    except ImportError:
        print("  ❌ 需要安装 PyMuPDF: pip install PyMuPDF")
        return []
    except Exception as e:
        print(f"  ❌ PDF 处理失败 ({os.path.basename(filepath)}): {e}")
        return []


def build_content_html(data, available_files, pdf_passwords):
    today = datetime.date.today()
    policies = data.get("policies", [])

    policy_items = []
    for p in policies:
        next_due = calculate_next_due_date(p["first_insure_date"], p["pay_period_years"])
        if next_due is None:
            days_left_num = 999999
            paid = p["pay_period_years"]
            status = "\u2705 \u5df2\u7f34\u6e05"
            days_left = "-"
            status_class = "status-done"
            next_due_str = "-"
        else:
            paid, current, total = calculate_installment_info(
                p["first_insure_date"], p["pay_period_years"], next_due)
            days_left_num = (next_due - today).days
            days_left = f"{days_left_num} \u5929"
            next_due_str = str(next_due)
            if days_left_num <= 30:
                status = "\U0001f534 \u5373\u5c06\u7f34\u8d39"
                status_class = "status-urgent"
            elif days_left_num <= 60:
                status = "\U0001f7e1 \u4e34\u8fd1\u7f34\u8d39"
                status_class = "status-warning"
            else:
                status = "\U0001f7e2 \u6b63\u5e38"
                status_class = "status-ok"
        policy_items.append({"p": p, "days_left_num": days_left_num, "paid": paid,
                             "status": status, "days_left": days_left,
                             "status_class": status_class, "next_due_str": next_due_str})

    policy_items.sort(key=lambda x: x["days_left_num"])

    grand_total = grand_paid = grand_remaining = 0
    for item in policy_items:
        p = item["p"]
        premium = int(p["premium"])
        total_periods = p["pay_period_years"]
        grand_total += premium * total_periods
        grand_paid += premium * item["paid"]
        grand_remaining += premium * (total_periods - item["paid"])

    current_year = today.year
    total_this_year = paid_this_year = unpaid_this_year = 0
    monthly_due = {}
    for item in policy_items:
        p = item["p"]
        next_due = calculate_next_due_date(p["first_insure_date"], p["pay_period_years"])
        if next_due is None:
            continue
        first_date = datetime.datetime.strptime(p["first_insure_date"], "%Y-%m-%d").date()
        try:
            this_year_due = first_date.replace(year=current_year)
        except ValueError:
            this_year_due = first_date.replace(year=current_year, day=28)
        end_year = first_date.year + p["pay_period_years"] - 1
        if first_date.year < current_year <= end_year:
            premium = int(p["premium"])
            total_this_year += premium
            if this_year_due < today:
                paid_this_year += premium
            else:
                unpaid_this_year += premium
                month = this_year_due.month
                monthly_due[month] = monthly_due.get(month, 0) + premium

    monthly_text = "<span class='monthly-tag active' onclick='filterMonth(0, event)'>\u5168\u90e8</span>"
    for month in sorted(monthly_due.keys()):
        monthly_text += f"<span class='monthly-tag' onclick='filterMonth({month}, event)'>{month}\u6708 \u00a5{monthly_due[month]:,}</span>"
    monthly_text = f"<div class='monthly-tags'>{monthly_text}</div>"

    policy_months = {}
    for item in policy_items:
        p = item["p"]
        next_due = calculate_next_due_date(p["first_insure_date"], p["pay_period_years"])
        if next_due is not None and next_due.year == current_year:
            policy_months[p["policy_id"]] = next_due.month
        else:
            policy_months[p["policy_id"]] = 0

    rows = ""
    for item in policy_items:
        p = item["p"]
        due_month = policy_months.get(p["policy_id"], 0)
        progress_pct = int(item['paid'] / p['pay_period_years'] * 100)
        row_class = ""
        if item["status_class"] == "status-urgent":
            row_class = "row-urgent"
        elif item["status_class"] == "status-warning":
            row_class = "row-warning"
        has_file = p["policy_id"] in available_files
        if has_file:
            page_count = available_files[p["policy_id"]]
            view_btn = f'<button class="view-btn" onclick="viewPolicy(\'{p["policy_id"]}\', {page_count})">📄 查看</button>'
        else:
            view_btn = '<span class="no-file">暂无</span>'
        rows += f"""<tr data-month="{due_month}" class="{row_class}">
<td>{p['user_name']}</td>
<td><strong>{p['policy_name']}</strong></td>
<td>{p['company']}</td>
<td class="amount">\u00a5{int(p['premium']):,}</td>
<td class="amount">\u00a5{int(p['premium']) * item['paid']:,}</td>
<td class="amount">\u00a5{int(p['premium']) * p['pay_period_years']:,}</td>
<td>{p['first_insure_date']}</td>
<td>{item['next_due_str']}</td>
<td><div class="progress-wrap"><div class="progress-bar" style="width:{progress_pct}%"></div><span class="progress-text">{item['paid']}/{p['pay_period_years']}\u671f</span></div></td>
<td>{item['days_left']}</td>
<td class="{item['status_class']}">{item['status']}</td>
<td>{view_btn}</td>
</tr>"""

    content = f"""<div class="header">
<h1>\U0001f4cb 家庭保单续费详情</h1>
<p>更新时间：{today.strftime('%Y年%m月%d日')}</p>
</div>
<div class="summary">
<div class="summary-section-title">累计保费</div>
<div class="summary-cards">
<div class="summary-card"><div class="summary-label">总保费</div><div class="summary-value">\u00a5{grand_total:,}</div></div>
<div class="summary-card"><div class="summary-label">已交</div><div class="summary-value green">\u00a5{grand_paid:,}</div></div>
<div class="summary-card"><div class="summary-label">剩余</div><div class="summary-value red">\u00a5{grand_remaining:,}</div></div>
</div>
<div class="summary-section-title">{current_year}年保费</div>
<div class="summary-cards">
<div class="summary-card"><div class="summary-label">今年需交</div><div class="summary-value">\u00a5{total_this_year:,}</div></div>
<div class="summary-card"><div class="summary-label">已交</div><div class="summary-value green">\u00a5{paid_this_year:,}</div></div>
<div class="summary-card"><div class="summary-label">还需交</div><div class="summary-value red">\u00a5{unpaid_this_year:,}</div></div>
</div>
<div class="monthly-detail"><span class="monthly-title">月度待缴：</span>{monthly_text}</div>
</div>
<div class="content">
<table><thead><tr>
<th>被保人</th><th>保单名称</th><th>保险公司</th><th>保费</th><th>已交保费</th><th>总保费</th><th>首保日期</th><th>下次续费</th><th>缴费进度</th><th>剩余天数</th><th>状态</th><th>保单详情</th>
</tr></thead><tbody>
{rows}
</tbody></table>
</div>
<div id="pdf-modal" class="modal" onclick="closeModal(event)">
<div class="modal-content" onclick="event.stopPropagation()">
<div class="modal-header">
<span class="modal-title">保单文件</span>
<div class="modal-nav">
<button class="nav-btn" onclick="prevPage()">◀</button>
<span id="page-info">1/1</span>
<button class="nav-btn" onclick="nextPage()">▶</button>
</div>
<button class="modal-close" onclick="closePdfModal()">✕</button>
</div>
<div class="modal-body" id="pdf-container"></div>
</div>
</div>
<div class="footer">自动生成 · 数据来源于保单管理系统</div>"""
    return content


def generate_html(data, password):
    policies = data.get("policies", [])

    # 加密 PDF 文件为独立文件
    pdf_dir = os.path.join(OUTPUT_DIR, "pdfs")
    os.makedirs(pdf_dir, exist_ok=True)
    available_files = {}
    pdf_passwords = {}
    for p in policies:
        policy_file = p.get("policy_file", "")
        if not policy_file:
            continue
        filepath = os.path.join(POLICY_FILES_DIR, policy_file)
        if not os.path.exists(filepath):
            print(f"  \u26a0\ufe0f  保单文件不存在: {filepath}")
            continue
        pdf_pwd = p.get("pdf_password", "")
        # 将 PDF 转为图片，每页加密存储
        images = convert_pdf_to_images(filepath, pdf_pwd)
        if not images:
            print(f"  \u26a0\ufe0f  PDF 转图片失败: {policy_file}")
            continue
        page_count = len(images)
        for page_num, jpeg_bytes in images:
            output_path = os.path.join(pdf_dir, f"{p['policy_id']}_p{page_num}.enc")
            # 加密图片数据
            salt = secrets.token_bytes(16)
            key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 10000, dklen=32)
            length = len(jpeg_bytes)
            key_stream = bytearray()
            counter = 0
            while len(key_stream) < length:
                block = hashlib.sha256(key + counter.to_bytes(4, 'big')).digest()
                key_stream.extend(block)
                counter += 1
            encrypted = bytearray(length)
            for i in range(length):
                encrypted[i] = jpeg_bytes[i] ^ key_stream[i]
            packed = bytes(salt) + bytes(encrypted)
            with open(output_path, "w", encoding="ascii") as f:
                f.write(base64.b64encode(packed).decode('ascii'))
        available_files[p["policy_id"]] = page_count
        if pdf_pwd:
            pdf_passwords[p["policy_id"]] = pdf_pwd
        print(f"  \U0001f4c4 已转换: {policy_file} ({page_count}页)")

    content_html = build_content_html(data, available_files, pdf_passwords)
    encrypted_data = encrypt_content(content_html, password)

    html = '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
    html += '<meta charset="UTF-8">\n'
    html += '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    html += '<title>保单续费详情</title>\n'
    html += '<style>\n'
    html += CSS_CONTENT
    html += '\n</style>\n</head>\n<body>\n'
    html += BODY_TEMPLATE.replace('__ENCRYPTED_DATA__', encrypted_data)
    html += '\n</body>\n</html>'
    return html


CSS_CONTENT = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
.container { max-width: 1200px; margin: 0 auto; background: #fff; border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.15); overflow: hidden; }
.header { background: linear-gradient(135deg, #2c3e50, #3498db); color: white; padding: 30px; text-align: center; position: sticky; top: 0; z-index: 10; }
.header h1 { font-size: 24px; margin-bottom: 8px; }
.header p { opacity: 0.8; font-size: 14px; }
.summary { padding: 20px; padding-bottom: 10px; background: #f8fafc; }
.summary-section-title { font-size: 13px; color: #666; font-weight: 600; margin-bottom: 10px; }
.summary-cards { display: flex; gap: 12px; margin-bottom: 16px; }
.summary-card { flex: 1; background: #fff; border-radius: 10px; padding: 14px; text-align: center; box-shadow: 0 2px 6px rgba(0,0,0,0.04); border: 1px solid #eef0f2; }
.summary-label { font-size: 12px; color: #888; margin-bottom: 6px; }
.summary-value { font-size: 18px; font-weight: 700; color: #2c3e50; }
.summary-value.green { color: #27ae60; }
.summary-value.red { color: #e74c3c; }
.monthly-detail { display: flex; align-items: center; gap: 8px; }
.monthly-title { font-size: 13px; color: #666; line-height: 28px; }
.monthly-tags { display: flex; gap: 8px; overflow-x: auto; white-space: nowrap; scrollbar-width: none; }
.monthly-tags::-webkit-scrollbar { display: none; }
.monthly-tag { display: inline-flex; background: #eef2ff; color: #4a5aba; font-size: 12px; padding: 6px 12px; border-radius: 14px; font-weight: 500; cursor: pointer; }
.monthly-tag:hover { background: #dce3ff; }
.monthly-tag.active { background: #4a5aba; color: #fff; }
.content { padding: 10px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { background: #f8f9fa; padding: 12px 8px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap; }
td { padding: 12px 8px; border-bottom: 1px solid #eee; vertical-align: middle; }
tr:hover { background: #f8f9fa; }
.amount { color: #e74c3c; font-weight: 600; }
.status-urgent { color: #e74c3c; font-weight: 600; }
.status-warning { color: #f39c12; font-weight: 600; }
.status-ok { color: #27ae60; }
.status-done { color: #95a5a6; }
.progress-wrap { position: relative; background: #e9ecef; border-radius: 10px; height: 20px; min-width: 80px; overflow: hidden; }
.progress-bar { height: 100%; background: linear-gradient(90deg, #27ae60, #2ecc71); border-radius: 10px; }
.progress-text { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 11px; font-weight: 600; color: #333; white-space: nowrap; }
.row-urgent { background: #fff0f0; }
.row-warning { background: #fffbf0; }
.footer { text-align: center; padding: 12px 20px; color: #999; font-size: 12px; border-top: 1px solid #eee; }
.view-btn { background: linear-gradient(135deg, #667eea, #764ba2); color: white; border: none; padding: 6px 12px; border-radius: 6px; font-size: 12px; cursor: pointer; white-space: nowrap; }
.view-btn:hover { opacity: 0.85; }
.view-btn:disabled { opacity: 0.5; cursor: wait; }
.no-file { color: #bbb; font-size: 12px; }
.modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); z-index: 9999; align-items: center; justify-content: center; }
.modal.active { display: flex; }
.modal-content { background: #fff; border-radius: 12px; width: 90%; max-width: 900px; height: 85vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 20px; border-bottom: 1px solid #eee; background: #f8f9fa; }
.modal-title { font-size: 16px; font-weight: 600; color: #2c3e50; }
.modal-nav { display: flex; align-items: center; gap: 8px; }
.nav-btn { background: #eee; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 14px; }
.nav-btn:hover { background: #ddd; }
#page-info { font-size: 13px; color: #666; }
.modal-close { background: none; border: none; font-size: 20px; cursor: pointer; color: #666; padding: 4px 8px; border-radius: 4px; }
.modal-close:hover { background: #eee; }
.modal-body { flex: 1; overflow: auto; display: flex; flex-direction: column; align-items: center; padding: 10px; background: #525659; }
.modal-body canvas { max-width: 100%; margin-bottom: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }
.login-wrapper { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
.login-box { background: white; border-radius: 16px; padding: 40px; box-shadow: 0 20px 60px rgba(0,0,0,0.15); text-align: center; max-width: 360px; width: 100%; }
.login-box h2 { margin-bottom: 8px; color: #2c3e50; }
.login-box p { color: #666; margin-bottom: 24px; font-size: 14px; }
.login-box input { width: 100%; padding: 12px 16px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 16px; outline: none; }
.login-box input:focus { border-color: #667eea; }
.login-box button { width: 100%; padding: 12px; margin-top: 16px; background: linear-gradient(135deg, #667eea, #764ba2); color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; }
.login-box button:hover { opacity: 0.9; }
.error-msg { color: #e74c3c; margin-top: 12px; font-size: 14px; display: none; }
@media (max-width: 768px) {
    body { padding: 0; background: #fff; }
    .container { border-radius: 0; box-shadow: none; }
    .header { padding: 16px; }
    .header h1 { font-size: 18px; }
    .summary { padding: 14px; }
    .summary-cards { gap: 8px; }
    .summary-card { padding: 10px 8px; }
    .summary-value { font-size: 15px; }
    .summary-label { font-size: 11px; }
    .content { padding: 10px; }
    table { font-size: 12px; }
    th, td { padding: 8px 4px; }
    .progress-wrap { min-width: 60px; height: 16px; }
    .progress-text { font-size: 10px; }
    .login-box { padding: 30px 20px; }
    .modal-content { width: 100%; height: 100vh; border-radius: 0; }
}
"""

BODY_TEMPLATE = """
<div id="login-screen" class="login-wrapper">
    <div class="login-box">
        <h2>\U0001f512 保单详情</h2>
        <p>请输入访问密码查看保单信息</p>
        <input type="password" id="password-input" placeholder="请输入密码" onkeypress="if(event.key==='Enter')decrypt()">
        <button onclick="decrypt()">查看详情</button>
        <div id="error-msg" class="error-msg">密码错误，请重试</div>
    </div>
</div>
<div id="main-content" class="container" style="display:none;"></div>
<script>
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
        btn.textContent = '\U0001f4c4 查看';
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
    // 转为 base64 图片
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
</script>
"""


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    data = load_config()
    html = generate_html(data, PAGE_PASSWORD)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("\u2705 加密详情页面已生成: " + OUTPUT_FILE)
    print("\U0001f511 访问密码: " + PAGE_PASSWORD)


if __name__ == "__main__":
    main()
