#!/usr/bin/env python3
"""
微信公众号保单续费提醒脚本

功能：
- 从配置文件加载用户列表和保单列表
- 根据首保时间和缴费期间，自动计算每年续费日期
- 到期前30天内自动推送微信模板消息提醒
"""
import json
import os
import requests
import datetime
import traceback

# ==================== 微信公众号配置 ====================
APPID = os.environ.get('WX_APPID')
APPSECRET = os.environ.get('WX_APPSECRET')
TEMPLATE_ID =  os.environ.get('WX_TEMPLATE_ID')
TEMPLATE_ID2 =  os.environ.get('WX_TEMPLATE_ID2')

# ==================== GitHub Pages 详情页地址 ====================
# 格式: https://<用户名>.github.io/<仓库名>/
DETAIL_PAGE_URL = os.environ.get('DETAIL_PAGE_URL', '')

# ==================== 配置文件路径 ====================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "insurance_data.json")


def load_config():
    """从JSON文件加载用户和保单配置"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        users = data.get("users", [])
        policies = data.get("policies", [])
        
        if not users:
            print("⚠️  警告: 用户列表为空")
        if not policies:
            print("⚠️  警告: 保单列表为空")
            
        return users, policies
    except FileNotFoundError:
        raise Exception(f"配置文件未找到: {CONFIG_FILE}")
    except json.JSONDecodeError as e:
        raise Exception(f"配置文件格式错误: {e}")


# ==================== 提醒配置 ====================
REMIND_DAYS_BEFORE = 60  # 到期前多少天开始提醒

# 保单文件目录
POLICY_FILES_DIR = os.environ.get('POLICY_FILES_DIR', os.path.join(SCRIPT_DIR, "policy_files"))
EXCEL_FILE = os.path.join(POLICY_FILES_DIR, "insurance.xlsx")


def load_cash_values():
    """从 Excel 读取现金价值。返回 {policy_id: {年度: 值}}"""
    if not os.path.exists(EXCEL_FILE):
        return {}
    try:
        from openpyxl import load_workbook
        wb = load_workbook(EXCEL_FILE, read_only=True, data_only=True)
        ws = wb.active
        row2 = list(ws.iter_rows(min_row=2, max_row=2, values_only=True))[0]
        policy_cols = {}
        for col_idx, val in enumerate(row2):
            if val and str(val).startswith("POL"):
                policy_cols[str(val)] = col_idx
        result = {pid: {} for pid in policy_cols}
        for row in ws.iter_rows(min_row=4, values_only=True):
            if row[0] is None:
                continue
            try:
                year = int(row[0])
            except (ValueError, TypeError):
                continue
            for pid, col_idx in policy_cols.items():
                if col_idx < len(row) and row[col_idx] is not None:
                    try:
                        result[pid][year] = float(row[col_idx])
                    except (ValueError, TypeError):
                        pass
        wb.close()
        return result
    except Exception:
        return {}


def calculate_policy_year(first_insure_date_str):
    """计算当前保单年度"""
    first_date = datetime.datetime.strptime(first_insure_date_str, "%Y-%m-%d").date()
    today = datetime.date.today()
    try:
        anniversary = first_date.replace(year=today.year)
    except ValueError:
        anniversary = first_date.replace(year=today.year, day=28)
    if today >= anniversary:
        return today.year - first_date.year + 1
    else:
        return today.year - first_date.year


def send_cash_value_message(access_token, user, policies):
    """用 WX_TEMPLATE_ID 给第一个用户发送现金价值汇总"""
    cash_values = load_cash_values()
    if not cash_values:
        print("⚠️ 无现金价值数据，跳过发送")
        return

    today = datetime.date.today()
    total_value = 0
    details = []

    for p in policies:
        pid = p["policy_id"]
        if pid not in cash_values:
            continue
        policy_year = calculate_policy_year(p["first_insure_date"])
        if policy_year < 1:
            continue
        cv = cash_values[pid].get(policy_year)
        if cv is None:
            continue
        total_value += cv
        details.append(f"{p['policy_name']} 第{policy_year}年 ¥{cv:,.0f}")

    if not details:
        print("⚠️ 无可用现金价值数据")
        return

    url = f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}"

    # 构建消息（使用 WX_TEMPLATE_ID 模板）
    data = {
        "first": {
            "value": f"【{today.year}年保单现金价值汇总】",
            "color": "#173177",
        },
        "keyword1": {
            "value": f"¥{total_value:,.0f}",
            "color": "#FF0000",
        },
        "keyword2": {
            "value": f"共{len(details)}份保单",
            "color": "#173177",
        },
        "keyword3": {
            "value": today.strftime("%Y-%m-%d"),
            "color": "#173177",
        },
        "remark": {
            "value": "点击查看详细信息",
            "color": "#666666",
        },
    }

    payload = {
        "touser": user["openid"],
        "template_id": TEMPLATE_ID,
        "url": DETAIL_PAGE_URL,
        "data": data,
    }

    resp = requests.post(url, json=payload, timeout=10)
    result = resp.json()
    if result.get("errcode") == 0:
        print(f"✅ 现金价值汇总消息已发送给 {user['name']}")
    else:
        print(f"❌ 现金价值消息发送失败: {result}")


def get_access_token():
    """获取微信access_token"""
    token_url = (
        f"https://api.weixin.qq.com/cgi-bin/token"
        f"?grant_type=client_credential&appid={APPID}&secret={APPSECRET}"
    )
    resp = requests.get(token_url, timeout=10)
    data = resp.json()
    if "access_token" not in data:
        raise Exception(f"获取access_token失败: {data}")
    return data["access_token"]


def calculate_next_due_date(first_insure_date_str, pay_period_years):
    """
    根据首保时间和缴费期间，计算今年（或下一个）的续费日期。

    逻辑：
    - 首保日期每年同一天为续费日
    - 如果今年的续费日已过，返回明年的续费日
    - 如果超过缴费期间，返回None（已缴清）
    """
    first_date = datetime.datetime.strptime(first_insure_date_str, "%Y-%m-%d").date()
    today = datetime.date.today()

    # 计算缴费结束年份（pay_period_years 是总期数，含首保）
    end_year = first_date.year + pay_period_years - 1

    # 从首保次年开始，每年同日续费
    # 找到今年或未来最近的一个续费日
    for year in range(first_date.year + 1, end_year + 1):
        try:
            due_date = first_date.replace(year=year)
        except ValueError:
            # 处理2月29日的情况，改为2月28日
            due_date = first_date.replace(year=year, day=28)

        # 如果这个续费日还没过（或就是今天），就是下一个续费日
        if due_date >= today:
            return due_date

    # 所有缴费期都已过，已缴清
    return None


def calculate_installment_info(first_insure_date_str, pay_period_years, due_date):
    """
    计算保费缴纳进度信息
    
    Args:
        first_insure_date_str: 首保日期字符串
        pay_period_years: 缴费总期数（年）
        due_date: 本次续费日期
    
    Returns:
        tuple: (已缴费期数, 当前是第几期, 总期数)
        
    说明：首保日期就是第一期，后续每年同日为续费日
    举例：首保2024-06-23，缴费10年
        - 2024-06-23：第1期
        - 2025-06-23：第2期
        - 2026-06-23：第3期
        今天2026-06-22，due_date=2026-06-23，已缴2期，当前是第3期
    """
    first_date = datetime.datetime.strptime(first_insure_date_str, "%Y-%m-%d").date()
    
    # due_date 是下一个待缴费日期
    # 当前是第几期 = due_date的年份 - 首保年份 + 1
    current_installment = due_date.year - first_date.year + 1
    
    # 已缴费期数 = 当前期数 - 1
    paid_installments = current_installment - 1
    
    total_installments = pay_period_years
    
    return paid_installments, current_installment, total_installments


def send_summary_message(access_token, openid, user_name, policies):
    """发送保单汇总信息（一条消息展示所有保单，每张保单占一个keyword）"""
    url = f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}"
    
    today = datetime.date.today()
    
    # 构建data字典
    data = {
        "first": {
            "value": "【保单汇总信息】",
            "color": "#173177",
        },
    }
    
    # 每张保单占一个keyword
    for i, policy in enumerate(policies, 1):
        next_due = calculate_next_due_date(
            policy["first_insure_date"], policy["pay_period_years"]
        )
        total = policy["pay_period_years"]
        if next_due is None:
            # 已缴清
            paid = total
        else:
            paid, current, total = calculate_installment_info(
                policy["first_insure_date"], policy["pay_period_years"], next_due
            )
        
        data[f"keyword{i}"] = {
            "value": f"{policy['policy_name']}，{policy['first_insure_date']}，{paid}/{total}期",
            "color": "#173177",
        }
    
    # data["remark"] = {
    #     "value": f"共{len(policies)}张保单",
    #     "color": "#666666",
    # }
    
    payload = {
        "touser": openid,
        "template_id": TEMPLATE_ID2,
        "url": DETAIL_PAGE_URL,
        "data": data,
    }

    resp = requests.post(url, json=payload, timeout=10)
    return resp.json()


def send_template_message(access_token, openid, user_name, policy, due_date, days_left):
    """发送微信模板消息"""
    url = f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}"
    
    # 计算缴费进度
    paid, current, total = calculate_installment_info(
        policy["first_insure_date"], 
        policy["pay_period_years"], 
        due_date
    )

    payload = {
        "touser": openid,
        "template_id": TEMPLATE_ID,
        "url": DETAIL_PAGE_URL,
        "data": {
            "first": {
                "value": f"【保险付费提醒】{policy['policy_name']}",
                "color": "#FF0000",
            },
            "keyword1": {
                "value": policy["policy_name"],
                "color": "#173177",
            },
            "keyword2": {
                "value": policy["user_name"],
                "color": "#173177",
            },
            "keyword3": {
                "value": datetime.date.today().strftime("%Y-%m-%d"),
                "color": "#FF6600",
            },
            "keyword4": {
                "value": f"¥{policy['premium']}",
                "color": "#FF0000",
            },
            "keyword5": {
                "value": policy["first_insure_date"],
                "color": "#173177",
            },
            "keyword6": {
                "value": f"{total}期",
                "color": "#173177",
            },
            "keyword7": {
                "value": f"{paid}期",
                "color": "#173177",
            },
            "remark": {
                "value": (
                    f"当前是第 {current} 期缴费，剩余{days_left} 天"
                ),
                "color": "#666666",
            },
        },
    }

    resp = requests.post(url, json=payload, timeout=10)
    return resp.json()


def main():
    print(f"🚀 开始执行保单续费提醒任务...")
    print(f"📅 当前日期: {datetime.date.today()}")
    print(f"⏰ 提醒窗口: 到期前 {REMIND_DAYS_BEFORE} 天")
    print()

    # 加载配置
    print("📁 正在加载配置文件...")
    users, policies = load_config()
    print(f"✅ 加载成功 - 用户: {len(users)} 人, 保单: {len(policies)} 张\n")

    today = datetime.date.today()
    total_sent = 0
    total_skipped = 0

    # 获取access_token
    print("🔑 正在获取微信access_token...")
    access_token = get_access_token()
    print("✅ access_token获取成功\n")

    # 发送现金价值汇总给第一个用户
    if users:
        send_cash_value_message(access_token, users[0], policies)

    # 按用户发送提醒（所有保单通知发给每个用户）
    for user in users:
        user_name = user["name"]
        openid = user["openid"]

        print(f"{'=' * 50}")
        print(f"👤 处理用户 {len(users)} 人中...")
        print(f"{'=' * 50}")

        # 先检查是否有需要提醒的保单
        remind_policies = []
        for policy in policies:
            next_due = calculate_next_due_date(
                policy["first_insure_date"], policy["pay_period_years"]
            )
            if next_due is not None:
                days_left = (next_due - today).days
                if 0 <= days_left <= REMIND_DAYS_BEFORE:
                    remind_policies.append((policy, next_due, days_left))

        # 汇总信息已取消，用户可点击模板消息进入详情页查看全部保单
        # if remind_policies:
        #     result = send_summary_message(access_token, openid, user_name, policies)

        # 再逐个发送续费提醒
        for policy in policies:
            next_due = calculate_next_due_date(
                policy["first_insure_date"], policy["pay_period_years"]
            )

            if next_due is None:
                total_skipped += 1
                continue

            days_left = (next_due - today).days

            # 判断是否在提醒窗口内
            if 0 <= days_left <= REMIND_DAYS_BEFORE:
                result = send_template_message(
                    access_token, openid, user_name, policy, next_due, days_left
                )
                if result.get("errcode") == 0:
                    print(f"  ✅ 提醒发送成功 (剩余{days_left}天)")
                    total_sent += 1
                else:
                    print(f"  ❌ 发送失败: errcode={result.get('errcode')}")
            else:
                total_skipped += 1

        print()

    # 统计结果
    print(f"{'=' * 50}")
    print(f"📊 执行统计")
    print(f"{'=' * 50}")
    print(f"✅ 发送提醒: {total_sent} 条")
    print(f"⏭️  跳过: {total_skipped} 条")
    print(f"📋 保单总数: {len(policies)} 张")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 执行出错: {e}")
        traceback.print_exc()
        exit(1)
