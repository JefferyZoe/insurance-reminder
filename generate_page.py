#!/usr/bin/env python3
"""
生成保单详情 HTML 页面（带密码保护），部署到 GitHub Pages。
PDF 文件单独加密存储为独立文件，构建时转为图片。
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
TEMPLATES_DIR = os.path.join(SCRIPT_DIR, "templates")

PAGE_PASSWORD = os.environ.get('PAGE_PASSWORD', '123456')
POLICY_FILES_DIR = os.environ.get('POLICY_FILES_DIR', os.path.join(SCRIPT_DIR, "policy_files"))


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_template(filename):
    with open(os.path.join(TEMPLATES_DIR, filename), "r", encoding="utf-8") as f:
        return f.read()


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
    """AES-GCM 加密文本，返回 base64(salt + iv + ciphertext + tag)"""
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 10000, dklen=32)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext.encode('utf-8'), None)
    # ciphertext 包含密文 + 16字节 tag
    packed = salt + iv + ciphertext
    return base64.b64encode(packed).decode('ascii')


def encrypt_file_to_output(filepath, password, output_path):
    """AES-GCM 加密文件"""
    with open(filepath, "rb") as f:
        data = f.read()
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 10000, dklen=32)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, data, None)
    packed = salt + iv + ciphertext
    with open(output_path, "w", encoding="ascii") as f:
        f.write(base64.b64encode(packed).decode('ascii'))
    return len(data)


def encrypt_bytes_to_file(data, password, output_path):
    """AES-GCM 加密字节数据"""
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 10000, dklen=32)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, data, None)
    packed = salt + iv + ciphertext
    with open(output_path, "w", encoding="ascii") as f:
        f.write(base64.b64encode(packed).decode('ascii'))


def convert_pdf_to_images(filepath, pdf_password=None):
    """将 PDF 转换为 JPEG 图片列表，返回 [(page_num, jpeg_bytes), ...]"""
    try:
        import fitz
        with open(filepath, "rb") as f:
            pdf_data = f.read()
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        if doc.is_encrypted:
            if pdf_password:
                if not doc.authenticate(pdf_password):
                    if not doc.authenticate(""):
                        doc.close()
                        return []
            else:
                if not doc.authenticate(""):
                    doc.close()
                    return []
        result = []
        for i, page in enumerate(doc):
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            result.append((i + 1, pix.tobytes("jpeg")))
        doc.close()
        return result
    except Exception:
        return []


def build_content_html(data, available_files):
    today = datetime.date.today()
    policies = data.get("policies", [])

    policy_items = []
    for p in policies:
        next_due = calculate_next_due_date(p["first_insure_date"], p["pay_period_years"])
        if next_due is None:
            days_left_num = 999999
            paid = p["pay_period_years"]
            status = "✅ 已缴清"
            days_left = "-"
            status_class = "status-done"
            next_due_str = "-"
        else:
            paid, current, total = calculate_installment_info(
                p["first_insure_date"], p["pay_period_years"], next_due)
            days_left_num = (next_due - today).days
            days_left = f"{days_left_num} 天"
            next_due_str = str(next_due)
            if days_left_num <= 30:
                status = "🔴 即将缴费"
                status_class = "status-urgent"
            elif days_left_num <= 60:
                status = "🟡 临近缴费"
                status_class = "status-warning"
            else:
                status = "🟢 正常"
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

    monthly_text = "<span class='monthly-tag active' onclick='filterMonth(0, event)'>全部</span>"
    for month in sorted(monthly_due.keys()):
        monthly_text += f"<span class='monthly-tag' onclick='filterMonth({month}, event)'>{month}月 ¥{monthly_due[month]:,}</span>"
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
            view_btn = f'<div class="btn-group"><button class="view-btn" onclick="viewPolicy(\'{p["policy_id"]}\', {page_count})">查看</button><button class="dl-btn" onclick="downloadPolicy(\'{p["policy_id"]}\')">下载</button></div>'
        else:
            view_btn = '<span class="no-file">暂无</span>'
        rows += f"""<tr data-month="{due_month}" class="{row_class}">
<td>{p['user_name']}</td><td><strong>{p['policy_name']}</strong></td><td>{p['company']}</td>
<td class="amount">¥{int(p['premium']):,}</td><td class="amount">¥{int(p['premium']) * item['paid']:,}</td><td class="amount">¥{int(p['premium']) * p['pay_period_years']:,}</td>
<td>{p['first_insure_date']}</td><td>{item['next_due_str']}</td>
<td><div class="progress-wrap"><div class="progress-bar" style="width:{progress_pct}%"></div><span class="progress-text">{item['paid']}/{p['pay_period_years']}期</span></div></td>
<td>{item['days_left']}</td><td class="{item['status_class']}">{item['status']}</td><td>{view_btn}</td>
</tr>"""

    content = f"""<div class="header">
<h1>📋 家庭保单续费详情</h1>
<p>更新时间：{today.strftime('%Y年%m月%d日')}</p>
</div>
<div class="summary">
<div class="summary-section-title">累计保费</div>
<div class="summary-cards">
<div class="summary-card"><div class="summary-label">总保费</div><div class="summary-value">¥{grand_total:,}</div></div>
<div class="summary-card"><div class="summary-label">已交</div><div class="summary-value green">¥{grand_paid:,}</div></div>
<div class="summary-card"><div class="summary-label">剩余</div><div class="summary-value red">¥{grand_remaining:,}</div></div>
</div>
<div class="summary-section-title">{current_year}年保费</div>
<div class="summary-cards">
<div class="summary-card"><div class="summary-label">今年需交</div><div class="summary-value">¥{total_this_year:,}</div></div>
<div class="summary-card"><div class="summary-label">已交</div><div class="summary-value green">¥{paid_this_year:,}</div></div>
<div class="summary-card"><div class="summary-label">还需交</div><div class="summary-value red">¥{unpaid_this_year:,}</div></div>
</div>
<div class="monthly-detail"><span class="monthly-title">月度待缴：</span>{monthly_text}</div>
</div>
<div class="content">
<table><thead><tr>
<th>被保人</th><th>保单名称</th><th>保险公司</th><th>保费</th><th>已交保费</th><th>总保费</th><th>首保日期</th><th>下次续费</th><th>缴费进度</th><th>剩余天数</th><th>状态</th><th>保单详情</th>
</tr></thead><tbody>{rows}</tbody></table>
</div>
<div id="pdf-modal" class="modal" onclick="closeModal(event)">
<div class="modal-content" onclick="event.stopPropagation()">
<div class="modal-header"><span class="modal-title">保单文件</span>
<div class="modal-nav"><button class="nav-btn" onclick="prevPage()">◀</button><span id="page-info">1/1</span><button class="nav-btn" onclick="nextPage()">▶</button></div>
<button class="modal-close" onclick="closePdfModal()">✕</button></div>
<div class="modal-body" id="pdf-container"></div>
</div></div>
<div class="footer">自动生成 · 数据来源于保单管理系统</div>"""
    return content


def generate_html(data, password):
    policies = data.get("policies", [])

    # 加密 PDF 文件为独立文件
    pdf_dir = os.path.join(OUTPUT_DIR, "pdfs")
    os.makedirs(pdf_dir, exist_ok=True)
    available_files = {}
    for p in policies:
        policy_file = p.get("policy_file", "")
        if not policy_file:
            continue
        filepath = os.path.join(POLICY_FILES_DIR, policy_file)
        if not os.path.exists(filepath):
            continue
        pdf_pwd = p.get("pdf_password", "")
        images = convert_pdf_to_images(filepath, pdf_pwd)
        if not images:
            continue
        page_count = len(images)
        for page_num, jpeg_bytes in images:
            output_path = os.path.join(pdf_dir, f"{p['policy_id']}_p{page_num}.enc")
            encrypt_bytes_to_file(jpeg_bytes, password, output_path)
        # 保存加密原始 PDF 用于下载
        encrypt_file_to_output(filepath, password, os.path.join(pdf_dir, f"{p['policy_id']}.enc"))
        available_files[p["policy_id"]] = page_count

    content_html = build_content_html(data, available_files)
    encrypted_data = encrypt_content(content_html, password)

    # 从模板文件加载 CSS 和 JS
    css = load_template("style.css")
    js = load_template("app.js").replace("__ENCRYPTED_DATA__", encrypted_data)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>保单续费详情</title>
<style>
{css}
</style>
</head>
<body>
<div id="login-screen" class="login-wrapper">
    <div class="login-box">
        <h2>🔒 保单详情</h2>
        <p>请输入访问密码查看保单信息</p>
        <input type="password" id="password-input" placeholder="请输入密码" onkeypress="if(event.key==='Enter')decrypt()">
        <button onclick="decrypt()">查看详情</button>
        <div id="error-msg" class="error-msg">密码错误，请重试</div>
    </div>
</div>
<div id="main-content" class="container" style="display:none;"></div>
<script>
{js}
</script>
</body>
</html>"""
    return html


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    data = load_config()
    html = generate_html(data, PAGE_PASSWORD)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()
