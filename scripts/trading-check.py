#!/usr/bin/env python3
"""510210 交易规则检查 — 抓行情 + 读持仓 + 对照规则 → JSON。
模型只需读 JSON → 润色 → 发送，不再手工分析。
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
WORKSPACE = "/home/node/.openclaw/workspace"
POSITION_FILE = f"{WORKSPACE}/memory/position.json"


def fetch_text(url, timeout=8):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Connection": "close",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        for enc in ("gbk", "gb2312", "utf-8"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")


def fetch_510210():
    """抓取510210行情"""
    text = fetch_text("https://qt.gtimg.cn/q=sh510210", timeout=5)
    match = re.search(r'v_sh510210="([^"]*)"', text, re.DOTALL)
    if not match:
        return None
    fields = match.group(1).split("~")
    off = -1 if (len(fields) > 30 and fields[30].strip().isdigit() and len(fields[30].strip()) == 14) else 0
    try:
        return {
            "price": round(float(fields[3]), 3),
            "prev_close": round(float(fields[4]), 3),
            "open": round(float(fields[5]), 3),
            "high": round(float(fields[34 + off]), 3),
            "low": round(float(fields[35 + off]), 3),
            "volume": int(fields[6]),
            "turnover_wan": float(fields[38 + off]) if fields[38 + off] else 0,
            "change_pct": round(float(fields[33 + off]), 2),
            "timestamp": fields[31 + off] if len(fields) > 31 + off else "",
        }
    except (ValueError, IndexError):
        return None


def fetch_sh_index():
    """抓取上证综指"""
    text = fetch_text("https://qt.gtimg.cn/q=sh000001", timeout=5)
    match = re.search(r'v_sh000001="([^"]*)"', text, re.DOTALL)
    if not match:
        return None
    fields = match.group(1).split("~")
    try:
        return {
            "price": round(float(fields[3]), 2),
            "prev_close": round(float(fields[4]), 2),
            "change_pct": round(float(fields[32]), 2),
        }
    except (ValueError, IndexError):
        return None


def fetch_kline_mas():
    """获取日K线均线"""
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData?symbol=sh510210&scale=60&datalen=65"
    )
    try:
        text = fetch_text(url, timeout=5)
        data = json.loads(text)
        closes = [float(k["close"]) for k in data if k.get("close")]
        if len(closes) < 3:
            return None
        closes_hist = closes[:-1]

        def ma(arr, n):
            return round(sum(arr[-n:]) / min(n, len(arr)), 3)

        def ma_dir(arr, n):
            if len(arr) < n + 2:
                return "—"
            prev = sum(arr[-(n+1):-1]) / n
            curr = sum(arr[-n:]) / n
            if curr > prev * 1.0005:
                return "↑"
            elif curr < prev * 0.9995:
                return "↓"
            return "→"

        return {
            "ma5": ma(closes_hist, 5),
            "ma10": ma(closes_hist, 10),
            "ma20": ma(closes_hist, 20),
            "ma60": ma(closes_hist, 60),
            "ma20_dir": ma_dir(closes_hist, 20),
            "ma60_dir": ma_dir(closes_hist, 60),
        }
    except Exception:
        return None


def get_position_tier(shares, thresholds):
    """判断仓位档位"""
    if shares == 0:
        return "空仓"
    if thresholds["light"][0] <= shares <= thresholds["light"][1]:
        return "轻仓"
    if thresholds["medium"][0] <= shares <= thresholds["medium"][1]:
        return "中等"
    if thresholds["heavy"][0] <= shares <= thresholds["heavy"][1]:
        return "重仓"
    return "未知"


def check_buy_rules(price, pos, mas, sh_idx):
    """检查所有买入规则"""
    triggers = []
    buy_points = pos.get("buy_points", {})
    cost = pos["cost"]
    shares = pos["shares"]

    # 第一档: 试探性回补 @1.033
    bp1 = buy_points.get("buy1", {})
    if bp1:
        target = bp1["price"]
        if price <= target:
            dist_pct = round((target - price) / target * 100, 2)
            triggers.append({
                "level": 1,
                "trigger_price": target,
                "current_price": price,
                "dist_pct": dist_pct,
                "desc": f"触及第一买点 {target}，下方{dist_pct}%",
                "action": "加500股，总持仓→1500",
                "stop_loss": bp1["stop_loss"],
            })

    # 第二档: 趋势修复 @1.047
    bp2 = buy_points.get("buy2", {})
    if bp2:
        target = bp2["price"]
        if price >= target:
            triggers.append({
                "level": 2,
                "trigger_price": target,
                "current_price": price,
                "desc": f"突破第二买点 {target}",
                "action": "加500股，总持仓→2000",
                "stop_loss": bp2["stop_loss"],
                "note": "需确认放量突破且站稳15分钟",
            })

    # 第三档: 真空抄底 0.995-1.000
    bp3 = buy_points.get("buy3", {})
    if bp3:
        lo, hi = bp3.get("price_min", 0.995), bp3.get("price_max", 1.000)
        if price <= hi:
            triggers.append({
                "level": 3,
                "trigger_price": f"{lo}-{hi}",
                "current_price": price,
                "desc": f"进入真空抄底区 {lo}-{hi}",
                "action": "加500股，总持仓→2500",
                "stop_loss": bp3["stop_loss"],
                "warning": "⚠️ 高风险！需确认放量恐慌+30分钟不创新低+买盘回升",
            })

    return triggers


def check_sell_rules(price, pos, mas, sh_idx):
    """检查所有卖出规则"""
    triggers = []
    shares = pos["shares"]
    cost = pos["cost"]
    pnl_pct = round((price - cost) / cost * 100, 2)
    thresholds = pos.get("tier_thresholds", {})

    # 判断持仓类型
    is_deep_profit = pnl_pct > 10  # 深度盈利底仓

    # === 无条件卖出 ===
    if sh_idx and sh_idx["change_pct"] < -2:
        triggers.append({
            "type": "无条件",
            "desc": f"上证综指单日跌 {sh_idx['change_pct']}%（>2%），触发无条件清仓",
            "action": "清仓",
        })

    # === 轻仓卖出规则 ===
    if shares <= 800:
        if is_deep_profit:
            # 深度盈利底仓: 移动止盈
            triggers.append({
                "type": "轻仓-深度盈利",
                "desc": f"浮盈 {pnl_pct}%，成本 {cost}，适用移动止盈规则",
                "rules": [
                    "从近期高点回撤3%+ → 全出",
                    "跌破第一买点锚(1.033) → 全出",
                    "均线死叉/放量破位 → 全出",
                    "上证单日跌>2% → 跟随清仓",
                ],
                "action": "持有观察，关注回撤",
            })
        else:
            # 活跃轻仓: 快进快出
            triggers.append({
                "type": "轻仓-活跃",
                "desc": f"浮盈 {pnl_pct}%，快进快出模式",
                "rules": [
                    "日内冲高回落>1% → 减半",
                    "浮盈>3%且30分钟不涨 → 全出",
                    "连续3个15分不创新高 → 减至400",
                ],
                "action": "短线操作，快出快进",
            })

    # 均线卖出检查
    if mas:
        if price < mas["ma5"]:
            triggers.append({
                "type": "均线",
                "desc": f"跌破MA5 ({mas['ma5']:.3f})",
                "action": "关注，轻仓可暂持" if shares <= 800 else "减500股",
            })
        if price < mas["ma20"]:
            triggers.append({
                "type": "均线",
                "desc": f"跌破MA20 ({mas['ma20']:.3f})",
                "action": "减500股" if shares > 400 else "底仓观察",
            })
        if mas["ma60"] and price < mas["ma60"] and mas["ma60_dir"] == "↓":
            triggers.append({
                "type": "均线",
                "desc": f"跌破MA60 ({mas['ma60']:.3f}) 且MA60↓",
                "action": "清至400底仓",
            })

    return triggers


def main():
    now = datetime.now(CST)
    time_str = now.strftime("%H:%M:%S")

    # 抓行情
    quote = fetch_510210()
    if quote is None:
        print(json.dumps({"status": "error", "reason": "fetch_failed"}))
        return

    sh_idx = fetch_sh_index()
    mas = fetch_kline_mas()

    # 读持仓
    try:
        with open(POSITION_FILE) as f:
            pos = json.load(f)
    except Exception:
        pos = {
            "symbol": "510210", "cost": 0.918, "shares": 500,
            "max_shares": 3000, "note": "fallback",
            "tier_thresholds": {
                "light": [400, 800], "medium": [1000, 1500], "heavy": [2000, 3000]
            },
            "buy_points": {
                "buy1": {"price": 1.033, "desc": "试探回补500股", "stop_loss": 1.030},
                "buy2": {"price": 1.047, "desc": "趋势修复500股", "stop_loss": 1.042},
                "buy3": {"price_min": 0.995, "price_max": 1.000, "desc": "真空抄底500股", "stop_loss": 0.990},
            },
            "key_levels": {"strong_resistance": 1.050, "iron_top": 1.058},
        }

    price = quote["price"]
    shares = pos["shares"]
    cost = pos["cost"]
    pnl = round((price - cost) * shares, 2)
    pnl_pct = round((price - cost) / cost * 100, 2)
    tier = get_position_tier(shares, pos.get("tier_thresholds", {}))

    # 检查买卖规则
    buy_triggers = check_buy_rules(price, pos, mas, sh_idx)
    sell_triggers = check_sell_rules(price, pos, mas, sh_idx)

    # 信号汇总
    trend_signals = []
    if mas:
        if mas["ma20_dir"] == "↑":
            trend_signals.append("趋势✅")
        elif mas["ma20_dir"] == "→":
            trend_signals.append("趋势➖")
        else:
            trend_signals.append("趋势❌")
        if quote["change_pct"] > 0:
            trend_signals.append("力度✅")
        elif quote["change_pct"] < -1:
            trend_signals.append("力度❌")
        else:
            trend_signals.append("力度➖")
        if sh_idx and sh_idx["change_pct"] > -1:
            trend_signals.append("环境✅")
        elif sh_idx and sh_idx["change_pct"] < -2:
            trend_signals.append("环境❌")
        else:
            trend_signals.append("环境➖")

    result = {
        "status": "ok",
        "time": time_str,
        "quote": {
            "price": price,
            "prev_close": quote["prev_close"],
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "change_pct": quote["change_pct"],
            "volume": quote["volume"],
        },
        "position": {
            "shares": shares,
            "cost": cost,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "pnl_pct_raw": round(pnl_pct, 2),
            "tier": tier,
            "max_shares": pos["max_shares"],
            "utilization": round(shares / pos["max_shares"] * 100, 1),
        },
        "indices": {
            "shanghai": sh_idx,
        },
        "mas": mas,
        "buy_triggers": buy_triggers,
        "sell_triggers": sell_triggers,
        "signals": trend_signals,
        "key_levels": pos.get("key_levels", {}),
    }

    # 预格式化摘要
    lines = [
        f"📊 510210 操作参考 | {time_str}",
        f"",
        f"💰 现价: {price:.3f}  涨跌: {quote['change_pct']:+.2f}%",
        f"📦 持仓: {shares}股  ┃  成本: {cost:.3f}  ┃  浮盈: ¥{pnl:.0f} ({pnl_pct:+.2f}%)",
        f"📐 仓位: {tier}（{round(shares/pos['max_shares']*100,1)}%）",
    ]

    if mas:
        lines.append(f"📈 MA5:{mas['ma5']:.3f} MA10:{mas['ma10']:.3f} MA20:{mas['ma20']:.3f}{mas['ma20_dir']} MA60:{mas['ma60']:.3f}{mas['ma60_dir']}")

    if sh_idx:
        lines.append(f"🏛️ 上证: {sh_idx['price']:.0f} ({sh_idx['change_pct']:+.2f}%)")

    if trend_signals:
        lines.append(f"🎯 信号: {' '.join(trend_signals)}")

    # 买入触发
    if buy_triggers:
        lines.append(f"\n📥 买入触发:")
        for bt in buy_triggers:
            lines.append(f"  L{bt['level']}: {bt['desc']} → {bt['action']}")
    else:
        lines.append(f"\n📥 买入: 无触发")

    # 卖出触发
    if sell_triggers:
        lines.append(f"\n📤 卖出触发:")
        for st in sell_triggers:
            lines.append(f"  • {st['desc']} → {st['action']}")
    else:
        lines.append(f"\n📤 卖出: 无触发")

    result["summary"] = "\n".join(lines)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
