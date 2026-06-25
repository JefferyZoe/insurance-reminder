#!/usr/bin/env python3
"""
生成保单详情 HTML 页面（带密码保护），部署到 GitHub Pages。
使用 AES-GCM 前端加密，访问者需输入密码才能查看内容。
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

# 页面访问密码，通过环境变量设置
PAGE_PASSWORD = os.environ.get('PAGE_PASSWORD', '123456')


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_next_due_date(first_insure_date_str, pay_period_years):
    first_date = datetime.datetime.strptime(first_insure_date_str, "%Y-%m-%d").date()
    today = datetime.date.today()
    # pay_period_years 表示总共缴费期数（含首保）
    # 续费次数 = pay_period_years - 1（首保之后还需续费的次数）
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
    """
    使用 PBKDF2 派生密钥 + XOR 流加密。
    返回 base64 编码的 salt + ciphertext 供前端解密。
    """
    salt = secrets.token_bytes(16)

    # PBKDF2 派生密钥
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 10000, dklen=32)

    plaintext_bytes = plaintext.encode('utf-8')
    length = len(plaintext_bytes)

    # 生成密钥流（使用 bytearray 提高性能）
    key_stream = bytearray()
    counter = 0
    while len(key_stream) < length:
        block = hashlib.sha256(key + counter.to_bytes(4, 'big')).digest()
        key_stream.extend(block)
        counter += 1

    # XOR 加密
    encrypted = bytearray(length)
    for i in range(length):
        encrypted[i] = plaintext_bytes[i] ^ key_stream[i]

    # 打包: salt(16) + encrypted
    packed = bytes(salt) + bytes(encrypted)
    return base64.b64encode(packed).decode('ascii')


def build_content_html(data):
    """生成保单详情的 HTML 内容（表格布局）"""
    today = datetime.date.today()
    policies = data.get("policies", [])

    # 计算每个保单的排序信息
    policy_items = []
    for p in policies:
        next_due = calculate_next_due_date(p["first_insure_date"], p["pay_period_years"])
        if next_due is None:
            days_left_num = 999999  # 已缴清的排最后
            paid = p["pay_period_years"]
            status = "✅ 已缴清"
            days_left = "-"
            status_class = "status-done"
            next_due_str = "-"
        else:
            paid, current, total = calculate_installment_info(
                p["first_insure_date"], p["pay_period_years"], next_due
            )
            days_left_num = (next_due - today).days
            days_left = f"{days_left_num} 天"
            next_due_str = str(next_due)
            if days_left_num <= 30:
                status = "🔴 即将到期"
                status_class = "status-urgent"
            elif days_left_num <= 60:
                status = "🟡 临近到期"
                status_class = "status-warning"
            else:
                status = "🟢 正常"
                status_class = "status-ok"

        policy_items.append({
            "p": p,
            "days_left_num": days_left_num,
            "paid": paid,
            "status": status,
            "days_left": days_left,
            "status_class": status_class,
            "next_due_str": next_due_str,
        })

    # 按剩余天数升序排序（已缴清的 999999 自然排到最后）
    policy_items.sort(key=lambda x: x["days_left_num"])

    # 计算所有保单的总保费统计（包含已缴清的）
    grand_total = 0       # 所有保单总保费
    grand_paid = 0        # 所有保单已交保费
    grand_remaining = 0   # 所有保单剩余保费

    for item in policy_items:
        p = item["p"]
        premium = int(p["premium"])
        total_periods = p["pay_period_years"]
        grand_total += premium * total_periods
        grand_paid += premium * item["paid"]
        grand_remaining += premium * (total_periods - item["paid"])

    # 计算今年保费统计（排除已缴清的）
    current_year = today.year
    total_this_year = 0  # 今年需交总保费
    paid_this_year = 0   # 今年已交
    unpaid_this_year = 0 # 今年还需交
    monthly_due = {}     # 按月份统计待交保费

    for item in policy_items:
        p = item["p"]
        next_due = calculate_next_due_date(p["first_insure_date"], p["pay_period_years"])
        if next_due is None:
            continue  # 已缴清，跳过

        # 判断今年是否有续费日
        first_date = datetime.datetime.strptime(p["first_insure_date"], "%Y-%m-%d").date()
        try:
            this_year_due = first_date.replace(year=current_year)
        except ValueError:
            this_year_due = first_date.replace(year=current_year, day=28)

        # 如果今年的续费日在缴费期限内
        end_year = first_date.year + p["pay_period_years"] - 1
        if first_date.year < current_year <= end_year:
            premium = int(p["premium"])
            total_this_year += premium
            if this_year_due < today:
                # 已过了续费日，视为已交
                paid_this_year += premium
            else:
                # 还没到续费日，视为未交
                unpaid_this_year += premium
                month = this_year_due.month
                monthly_due[month] = monthly_due.get(month, 0) + premium

    # 构建月度明细文本（可点击筛选）
    monthly_text = "<span class='monthly-tag active' onclick='filterMonth(0, event)'>全部</span>"
    for month in sorted(monthly_due.keys()):
        monthly_text += f"<span class='monthly-tag' onclick='filterMonth({month}, event)'>{month}月 ¥{monthly_due[month]:,}</span>"

    # 计算每个保单今年的续费月份（用于筛选）
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
        rows += f"""<tr data-month="{due_month}">
<td>{p['user_name']}</td>
<td><strong>{p['policy_name']}</strong></td>
<td>{p['company']}</td>
<td class="amount">¥{p['premium']}</td>
<td class="amount">¥{int(p['premium']) * p['pay_period_years']:,}</td>
<td>{p['first_insure_date']}</td>
<td>{item['next_due_str']}</td>
<td>{item['paid']}/{p['pay_period_years']}期</td>
<td>{item['days_left']}</td>
<td class="{item['status_class']}">{item['status']}</td>
</tr>"""

    content = f"""<div class="header">
<h1>📋 家庭保单续费详情</h1>
<p>更新时间：{today.strftime('%Y年%m月%d日')}</p>
</div>
<div class="summary">
<div class="summary-section-title">累计保费</div>
<div class="summary-cards">
<div class="summary-card">
<div class="summary-label">总保费</div>
<div class="summary-value">¥{grand_total:,}</div>
</div>
<div class="summary-card">
<div class="summary-label">已交</div>
<div class="summary-value green">¥{grand_paid:,}</div>
</div>
<div class="summary-card">
<div class="summary-label">剩余</div>
<div class="summary-value red">¥{grand_remaining:,}</div>
</div>
</div>
<div class="summary-section-title">{current_year}年保费</div>
<div class="summary-cards">
<div class="summary-card">
<div class="summary-label">今年需交</div>
<div class="summary-value">¥{total_this_year:,}</div>
</div>
<div class="summary-card">
<div class="summary-label">已交</div>
<div class="summary-value green">¥{paid_this_year:,}</div>
</div>
<div class="summary-card">
<div class="summary-label">还需交</div>
<div class="summary-value red">¥{unpaid_this_year:,}</div>
</div>
</div>
<div class="monthly-detail">
<span class="monthly-title">月度待缴：</span>
{monthly_text}
</div>
</div>
<div class="content">
<table>
<thead>
<tr>
<th>被保人</th>
<th>保单名称</th>
<th>保险公司</th>
<th>保费</th>
<th>总保费</th>
<th>首保日期</th>
<th>下次续费</th>
<th>缴费进度</th>
<th>剩余天数</th>
<th>状态</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<div class="footer">
自动生成 · 数据来源于保单管理系统
</div>"""
    return content


def generate_html(data, password):
    today = datetime.date.today()
    
    # 生成明文内容
    content_html = build_content_html(data)
    
    # 加密内容
    encrypted_data = encrypt_content(content_html, password)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>保单续费详情</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: #fff;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.15);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            height: calc(100vh - 40px);
        }}
        .header {{
            background: linear-gradient(135deg, #2c3e50, #3498db);
            color: white;
            padding: 30px;
            text-align: center;
            flex-shrink: 0;
        }}
        .header h1 {{
            font-size: 24px;
            margin-bottom: 8px;
        }}
        .header p {{
            opacity: 0.8;
            font-size: 14px;
        }}
        .summary {{
            padding: 20px;
            background: #f8fafc;
            border-bottom: 1px solid #eee;
            flex-shrink: 0;
        }}
        .summary-section-title {{
            font-size: 13px;
            color: #666;
            font-weight: 600;
            margin-bottom: 10px;
            padding-left: 2px;
        }}
        .summary-cards {{
            display: flex;
            gap: 12px;
            margin-bottom: 16px;
        }}
        .summary-card {{
            flex: 1;
            background: #fff;
            border-radius: 10px;
            padding: 14px;
            text-align: center;
            box-shadow: 0 2px 6px rgba(0,0,0,0.04);
            border: 1px solid #eef0f2;
        }}
        .summary-label {{
            font-size: 12px;
            color: #888;
            margin-bottom: 6px;
        }}
        .summary-value {{
            font-size: 18px;
            font-weight: 700;
            color: #2c3e50;
        }}
        .summary-value.green {{
            color: #27ae60;
        }}
        .summary-value.red {{
            color: #e74c3c;
        }}
        .monthly-detail {{
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .monthly-title {{
            font-size: 13px;
            color: #666;
        }}
        .monthly-tag {{
            display: inline-block;
            background: #eef2ff;
            color: #4a5aba;
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 12px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .monthly-tag:hover {{
            background: #dce3ff;
        }}
        .monthly-tag.active {{
            background: #4a5aba;
            color: #fff;
        }}
        .content {{
            padding: 20px;
            overflow-x: auto;
            overflow-y: auto;
            flex: 1;
            min-height: 0;
            -webkit-overflow-scrolling: touch;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}
        th {{
            background: #f8f9fa;
            padding: 12px 8px;
            text-align: left;
            font-weight: 600;
            color: #495057;
            border-bottom: 2px solid #dee2e6;
            white-space: nowrap;
            position: sticky;
            top: 0;
            z-index: 1;
        }}
        td {{
            padding: 12px 8px;
            border-bottom: 1px solid #eee;
            vertical-align: middle;
        }}
        tr:hover {{
            background: #f8f9fa;
        }}
        .amount {{
            color: #e74c3c;
            font-weight: 600;
        }}
        .status-urgent {{
            color: #e74c3c;
            font-weight: 600;
        }}
        .status-warning {{
            color: #f39c12;
            font-weight: 600;
        }}
        .status-ok {{
            color: #27ae60;
        }}
        .status-done {{
            color: #95a5a6;
        }}
        .footer {{
            text-align: center;
            padding: 12px 20px;
            color: #999;
            font-size: 12px;
            border-top: 1px solid #eee;
            flex-shrink: 0;
        }}
        /* 密码输入框样式 */
        .login-wrapper {{
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }}
        .login-box {{
            background: white;
            border-radius: 16px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.15);
            text-align: center;
            max-width: 360px;
            width: 100%;
        }}
        .login-box h2 {{
            margin-bottom: 8px;
            color: #2c3e50;
        }}
        .login-box p {{
            color: #666;
            margin-bottom: 24px;
            font-size: 14px;
        }}
        .login-box input {{
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
            outline: none;
            transition: border-color 0.3s;
        }}
        .login-box input:focus {{
            border-color: #667eea;
        }}
        .login-box button {{
            width: 100%;
            padding: 12px;
            margin-top: 16px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
            transition: opacity 0.3s;
        }}
        .login-box button:hover {{
            opacity: 0.9;
        }}
        .error-msg {{
            color: #e74c3c;
            margin-top: 12px;
            font-size: 14px;
            display: none;
        }}
        @media (max-width: 768px) {{
            body {{
                padding: 0;
                background: #fff;
            }}
            .container {{
                border-radius: 0;
                height: 100vh;
                box-shadow: none;
            }}
            .header {{
                padding: 16px;
            }}
            .header h1 {{
                font-size: 18px;
            }}
            .summary {{
                padding: 14px;
            }}
            .summary-cards {{
                gap: 8px;
            }}
            .summary-card {{
                padding: 10px 8px;
            }}
            .summary-value {{
                font-size: 15px;
            }}
            .summary-label {{
                font-size: 11px;
            }}
            .content {{
                padding: 10px;
            }}
            table {{
                font-size: 12px;
            }}
            th, td {{
                padding: 8px 4px;
            }}
            .login-box {{
                padding: 30px 20px;
            }}
        }}
    </style>
</head>
<body>
    <!-- 密码输入界面 -->
    <div id="login-screen" class="login-wrapper">
        <div class="login-box">
            <h2>🔒 保单详情</h2>
            <p>请输入访问密码查看保单信息</p>
            <input type="password" id="password-input" placeholder="请输入密码" onkeypress="if(event.key==='Enter')decrypt()">
            <button onclick="decrypt()">查看详情</button>
            <div id="error-msg" class="error-msg">密码错误，请重试</div>
        </div>
    </div>

    <!-- 解密后的内容容器 -->
    <div id="main-content" class="container" style="display:none;"></div>

    <!-- 加密数据 -->
    <script>
    const ENCRYPTED_DATA = "{encrypted_data}";

    function filterMonth(month, e) {{
        e.preventDefault();
        e.stopPropagation();

        // 切换 active 状态
        document.querySelectorAll('.monthly-tag').forEach(tag => tag.classList.remove('active'));
        e.target.classList.add('active');

        // 筛选表格行
        const rows = document.querySelectorAll('table tbody tr');
        rows.forEach(row => {{
            if (month === 0) {{
                row.style.display = '';
            }} else {{
                const rowMonth = parseInt(row.getAttribute('data-month'));
                row.style.display = (rowMonth === month) ? '' : 'none';
            }}
        }});
    }}

    async function decrypt() {{
        const password = document.getElementById('password-input').value;
        if (!password) return;

        try {{
            // Base64 解码
            const packed = Uint8Array.from(atob(ENCRYPTED_DATA), c => c.charCodeAt(0));
            
            // 提取 salt(前16字节) 和密文
            const salt = packed.slice(0, 16);
            const ciphertext = packed.slice(16);

            // PBKDF2 派生密钥
            const encoder = new TextEncoder();
            const keyMaterial = await crypto.subtle.importKey(
                'raw', encoder.encode(password), 'PBKDF2', false, ['deriveBits']
            );
            const derivedBits = await crypto.subtle.deriveBits(
                {{ name: 'PBKDF2', salt: salt, iterations: 10000, hash: 'SHA-256' }},
                keyMaterial, 256
            );
            const key = new Uint8Array(derivedBits);

            // 生成密钥流并解密 (与 Python 端一致的 XOR 流加密)
            let keyStream = new Uint8Array(0);
            let counter = 0;
            while (keyStream.length < ciphertext.length) {{
                const counterBytes = new Uint8Array(4);
                new DataView(counterBytes.buffer).setUint32(0, counter, false);
                const blockInput = new Uint8Array(key.length + 4);
                blockInput.set(key);
                blockInput.set(counterBytes, key.length);
                const block = new Uint8Array(await crypto.subtle.digest('SHA-256', blockInput));
                const newStream = new Uint8Array(keyStream.length + block.length);
                newStream.set(keyStream);
                newStream.set(block, keyStream.length);
                keyStream = newStream;
                counter++;
            }}

            // XOR 解密
            const decrypted = new Uint8Array(ciphertext.length);
            for (let i = 0; i < ciphertext.length; i++) {{
                decrypted[i] = ciphertext[i] ^ keyStream[i];
            }}

            // 尝试解码为 UTF-8
            const decoder = new TextDecoder('utf-8', {{ fatal: true }});
            const html = decoder.decode(decrypted);

            // 简单验证解密结果是否为有效 HTML
            if (!html.includes('<') || !html.includes('保单')) {{
                throw new Error('解密内容无效');
            }}

            // 解密成功，显示内容
            document.getElementById('login-screen').style.display = 'none';
            document.getElementById('main-content').innerHTML = html;
            document.getElementById('main-content').style.display = 'block';
        }} catch (e) {{
            document.getElementById('error-msg').style.display = 'block';
            document.getElementById('password-input').value = '';
            document.getElementById('password-input').focus();
        }}
    }}
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
    print(f"✅ 加密详情页面已生成: {OUTPUT_FILE}")
    print(f"🔑 访问密码: {PAGE_PASSWORD}")


if __name__ == "__main__":
    main()
