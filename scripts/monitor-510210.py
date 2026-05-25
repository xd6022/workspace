#!/usr/bin/env python3
"""监控 510210 上证综指ETF — 双API源 + 盘口 + 历史追踪"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
WORKSPACE = "/home/node/.openclaw/workspace"
STATE_FILE = f"{WORKSPACE}/memory/510210-state.json"

MARKET_INDICES = [
    ("sh", "1.000001", "上证指数"),
    ("cy", "0.399006", "创业板指"),
    ("hs300", "1.000300", "沪深300"),
]

# 腾讯字段索引
# 3=当前价, 4=昨收, 5=今开, 6=成交量, 32=涨跌额, 33=涨跌幅, 34=最高, 35=最低, 38=成交额(万)
# 39=换手率(%), 44=市盈率, 45=流通市值(亿), 46=总市值(亿), 48=涨停价, 49=跌停价, 50=量比
# 9-18: 买一价/量 ~ 买五价/量
# 19-28: 卖一价/量 ~ 卖五价/量
# 31: 时间戳 YYYYMMDDHHmmss

API_SOURCES = [
    {
        "name": "tencent",
        "url": "https://qt.gtimg.cn/q=sh510210",
        "parser": "tencent",
    },
    {
        "name": "eastmoney",
        "url": (
            "https://push2.eastmoney.com/api/qt/stock/get"
            "?secid=1.510210&fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f116,f117,f169,f170,f171"
        ),
        "parser": "eastmoney",
    },
]


def fetch_text(url, timeout=10):
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


def parse_eastmoney(text):
    data = json.loads(text)
    d = data["data"]
    if d is None or d.get("f43") is None:
        return None
    return {
        "price": round(d["f43"] / 1000, 3),
        "prev_close": round(d["f60"] / 1000, 3),
        "open": round(d["f46"] / 1000, 3),
        "high": round(d["f44"] / 1000, 3),
        "low": round(d["f45"] / 1000, 3),
        "change_pct": round(d["f170"] / 100, 2),
        "change_amt": round(d["f169"] / 1000, 3),
        "volume": d["f47"],
        "turnover_yi": round(d["f48"] / 100000000, 2),
        "source": "eastmoney",
        "order_book": None,
        "volume_ratio": round(d.get("f50", 0) / 100, 2) if d.get("f50") else 0,
        "total_mc_yi": round(d.get("f116", 0) / 100000000, 2) if d.get("f116") else 0,
        "circulating_mc_yi": round(d.get("f117", 0) / 100000000, 2) if d.get("f117") else 0,
        "amplitude": round(d.get("f171", 0) / 100, 2) if d.get("f171") else 0,
    }


def parse_tencent(text):
    match = re.search(r'v_sh510210="([^"]*)"', text, re.DOTALL)
    if not match:
        return None
    fields = match.group(1).split("~")
    if len(fields) < 40:
        return None
    # 自适应偏移: 交易时段field[29]有逐笔数据, 收盘后为空导致下标整体-1
    off = -1 if (len(fields) > 30 and fields[30].strip().isdigit() and len(fields[30].strip()) == 14) else 0
    i_ts   = 31 + off
    i_amt  = 32 + off
    i_pct  = 33 + off
    i_high = 34 + off
    i_low  = 35 + off
    i_amtw = 38 + off
    i_tor  = 39 + off
    i_cmc  = 45 + off
    i_tmc  = 46 + off
    i_vr   = 50 + off
    try:
        # 解析时间戳
        raw_ts = fields[i_ts].strip()
        ts_str = f"{raw_ts[:4]}-{raw_ts[4:6]}-{raw_ts[6:8]} {raw_ts[8:10]}:{raw_ts[10:12]}:{raw_ts[12:14]}" if len(raw_ts) >= 14 else raw_ts

        return {
            "price": round(float(fields[3]), 3),
            "prev_close": round(float(fields[4]), 3),
            "open": round(float(fields[5]), 3),
            "high": round(float(fields[i_high]), 3),
            "low": round(float(fields[i_low]), 3),
            "change_pct": round(float(fields[i_pct]), 2),
            "change_amt": round(float(fields[i_amt]), 3),
            "volume": int(fields[6]),
            "turnover_yi": round(float(fields[i_amtw]) / 10000, 2) if fields[i_amtw] else 0,
            "source": "tencent",
            "timestamp": ts_str,
            "turnover_rate": round(float(fields[i_tor]), 2) if fields[i_tor] else 0,
            "total_mc_yi": round(float(fields[i_tmc]), 2) if fields[i_tmc] else 0,
            "circulating_mc_yi": round(float(fields[i_cmc]), 2) if fields[i_cmc] else 0,
            "volume_ratio": round(float(fields[i_vr]), 2) if fields[i_vr] else 0,
            "order_book": {
                "b1_price": float(fields[9]) if fields[9] else 0,
                "b1_vol": int(fields[10]) if fields[10] else 0,
                "b2_price": float(fields[11]) if fields[11] else 0,
                "b2_vol": int(fields[12]) if fields[12] else 0,
                "b3_price": float(fields[13]) if fields[13] else 0,
                "b3_vol": int(fields[14]) if fields[14] else 0,
                "b4_price": float(fields[15]) if fields[15] else 0,
                "b4_vol": int(fields[16]) if fields[16] else 0,
                "b5_price": float(fields[17]) if fields[17] else 0,
                "b5_vol": int(fields[18]) if fields[18] else 0,
                "a1_price": float(fields[19]) if fields[19] else 0,
                "a1_vol": int(fields[20]) if fields[20] else 0,
                "a2_price": float(fields[21]) if fields[21] else 0,
                "a2_vol": int(fields[22]) if fields[22] else 0,
                "a3_price": float(fields[23]) if fields[23] else 0,
                "a3_vol": int(fields[24]) if fields[24] else 0,
                "a4_price": float(fields[25]) if fields[25] else 0,
                "a4_vol": int(fields[26]) if fields[26] else 0,
                "a5_price": float(fields[27]) if fields[27] else 0,
                "a5_vol": int(fields[28]) if fields[28] else 0,
            },
        }
    except (ValueError, IndexError):
        return None


def fetch_price(timeout=5):
    for src in API_SOURCES:
        for attempt in range(2):
            try:
                text = fetch_text(src["url"], timeout=timeout)
                if src["parser"] == "eastmoney":
                    result = parse_eastmoney(text)
                else:
                    result = parse_tencent(text)
                if result:
                    return result
            except Exception:
                if attempt < 1:
                    time.sleep(0.5)
                continue
            break
    return None


def fetch_kline_mas(timeout=4):
    """获取日K线并计算5/10/20/60日均线 + 趋势判断"""
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData?symbol=sh510210&scale=60&datalen=65"
    )
    try:
        text = fetch_text(url, timeout=timeout)
        data = json.loads(text)
        closes = []
        for k in data:
            if k.get("close"):
                closes.append(float(k["close"]))
        if len(closes) < 3:
            return None
        # 排除今日(最后一条)，用历史收盘价
        closes_hist = closes[:-1]

        def ma(arr, n):
            if len(arr) < n:
                return round(sum(arr) / len(arr), 3)
            return round(sum(arr[-n:]) / n, 3)

        def ma_slope(arr, n):
            """MA方向: ↑上行 →走平 ↓下行"""
            if len(arr) < n + 2:
                return "—"
            ma_prev = sum(arr[-(n+1):-1]) / n
            ma_curr = sum(arr[-n:]) / n
            diff_pct = (ma_curr - ma_prev) / ma_prev * 100 if ma_prev > 0 else 0
            if diff_pct > 0.05:
                return "↑"
            elif diff_pct < -0.05:
                return "↓"
            return "→"

        ma5_val = ma(closes_hist, 5)
        ma10_val = ma(closes_hist, 10)
        ma20_val = ma(closes_hist, 20)
        ma60_val = ma(closes_hist, 60)
        ma20_dir = ma_slope(closes_hist, 20)
        ma60_dir = ma_slope(closes_hist, 60)

        return {
            "ma5": ma5_val,
            "ma10": ma10_val,
            "ma20": ma20_val,
            "ma60": ma60_val,
            "ma20_dir": ma20_dir,
            "ma60_dir": ma60_dir,
            "close_count": len(closes_hist),
        }
    except Exception:
        return None


def fetch_market_data(timeout=2):
    """获取市场环境: 三大指数涨跌幅 + 北向资金净流入"""
    result = {"indices": {}, "northbound_yi": 0}
    # 三大指数
    for key, secid, name in MARKET_INDICES:
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f60,f170"
        try:
            text = fetch_text(url, timeout=timeout)
            data = json.loads(text).get("data")
            if data and data.get("f43") is not None:
                result["indices"][key] = {
                    "name": name,
                    "price": round(data["f43"] / 100, 2),
                    "prev_close": round(data["f60"] / 100, 2),
                    "change_pct": round(data["f170"] / 100, 2),
                }
        except Exception:
            pass
    # 北向资金
    try:
        url = "https://push2.eastmoney.com/api/qt/kamt/get?fields1=f1,f2,f3,f4&fields2=f51,f52&secid=1.000001"
        text = fetch_text(url, timeout=2)
        data = json.loads(text).get("data", {})
        nb = (data.get("hk2sh", {}).get("dayNetAmtIn", 0) +
              data.get("hk2sz", {}).get("dayNetAmtIn", 0))
        result["northbound_yi"] = round(nb / 10000, 2)  # 万元→亿
    except Exception:
        pass
    return result


def fmt_table(data, is_alert=False):
    """简洁多行展示，不画表线。"""
    time_str = data.get("time", "")
    sent = data.get("sentiment", {})
    
    title = "⚠️ 波动预警" if is_alert else "📊 510210 上证综指ETF"
    if is_alert:
        title += f"  {data.get('change_from_last', 0):+.2f}%"
    
    trend = data.get("trend", {})
    tech = data.get("technical", {})
    trend_line = ""
    strategy_line = ""
    if trend and tech:
        scenario = trend.get("scenario", "震荡整理")
        risk = trend.get("risk", "中")
        ma5_val = tech.get("ma5", 0)
        ma10_val = tech.get("ma10", 0)
        ma20_val = tech.get("ma20", 0)
        ma60_val = tech.get("ma60", 0)
        ma20_dir = tech.get("ma20_dir", "→")
        ma60_dir = tech.get("ma60_dir", "→")
        price = data.get("price", 0)
        trend_line = f"MA5:{ma5_val:.3f} MA10:{ma10_val:.3f} MA20:{ma20_val:.3f}{ma20_dir} MA60:{ma60_val:.3f}{ma60_dir}"
        # 决策建议
        above_ma20 = price > ma20_val if ma20_val > 0 else None
        if ma60_dir == "↑" and above_ma20:
            advice = "📌 偏多，回踩MA20可加仓"
        elif ma60_dir == "↑" and above_ma20 is False:
            advice = "📌 回调中，等站回MA20再动"
        elif ma60_dir == "→" and above_ma20:
            advice = "📌 震荡偏强，轻仓试探"
        elif ma60_dir == "→" and above_ma20 is False:
            advice = "📌 观望，等价格站上MA20或MA60抬头"
        elif ma60_dir == "↓":
            advice = "📌 MA60下行，不加仓"
        else:
            advice = "📌 信号不明，观望"
        strategy_line = f"{scenario}（风险:{risk}）{advice}"
    
    lines = [
        f"⏱ {time_str} 行情速递：",
        "",
        title,
        f"💰 当前 {data.get('price', 0):.3f} │涨跌 {data.get('change_amt', 0):+.3f} ({data.get('change_pct', 0):+.2f}%) │ 📅 昨收 {data.get('prev_close', 0):.3f}",
        f"🔺最高 {data.get('high', 0):.3f} │ 🔻最低 {data.get('low', 0):.3f}",
        f"📊 成交量 {data.get('volume', 0) // 10000}万手 │ 成交额 {data.get('turnover_yi', 0):.2f}亿",
        "",
        f"5min涨跌: {sent.get('change_5min', 0):+.2f}% │ 今日振幅: {sent.get('amplitude', 0):.2f}% │ 量比: {sent.get('volume_ratio', 0):.2f} │ 换手率: {sent.get('turnover_rate', 0):.2f}%",
    ]
    if trend_line:
        lines.append(trend_line)
    if strategy_line:
        lines.append(strategy_line)
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=None, help="覆盖开始时间(分钟,如870=14:30)")
    parser.add_argument("--end", type=int, default=None, help="覆盖结束时间(分钟,如870=14:30)")
    args = parser.parse_args()

    now = datetime.now(CST)
    current_minutes = now.hour * 60 + now.minute
    weekday = now.weekday()

    # 支持命令行覆盖交易时段
    morning_start, morning_end = 570, 690   # 9:30-11:30
    afternoon_start, afternoon_end = 780, 900  # 13:00-15:00

    if args.end is not None:
        afternoon_end = args.end
        if afternoon_end <= afternoon_start:
            afternoon_start = afternoon_end  # 无效区间, afternoon段关闭
    if args.start is not None:
        afternoon_start = max(afternoon_start, args.start)

    if args.start is not None and args.end is not None and args.start >= args.end:
        # 自定义区间无效时跳过
        print(json.dumps({"status": "skip", "reason": "outside_custom_range"}))
        return

    in_trading = (morning_start <= current_minutes <= morning_end) or (afternoon_start <= current_minutes <= afternoon_end)
    if not in_trading or weekday >= 5:
        print(json.dumps({"status": "skip", "reason": "outside_trading_hours"}))
        return

    # Fetch price (try all sources)
    fresh = fetch_price(timeout=8)

    # Read last state
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
        except:
            pass

    # 初始化默认值（API失败时用缓存）
    market = state.get("market", {"indices": {}, "northbound_yi": 0})
    technical = state.get("technical", {})
    trend = state.get("trend", {})

    if fresh is None:
        cached_price = state.get("last_price_raw")
        if cached_price:
            price_raw = cached_price
            price = state.get("last_price", price_raw / 1000)
            prev_close = state.get("prev_close", 0)
            open_price = state.get("open", 0)
            high = state.get("high", 0)
            low = state.get("low", 0)
            change_pct = state.get("change_pct", 0)
            change_amt = 0
            turnover = state.get("turnover_yi", 0)
            volume = state.get("volume", 0)
            data_fresh = False
            source = "cache"
            order_book = state.get("order_book")
            volume_ratio = state.get("volume_ratio", 0)
            turnover_rate = state.get("turnover_rate", 0)
            circulating_mc_yi = state.get("circulating_mc_yi", 0)
            ts = ""
        else:
            print(json.dumps({"status": "error", "reason": "all_sources_failed"}))
            return
    else:
        price_raw = int(fresh["price"] * 1000)
        price = fresh["price"]
        prev_close = fresh["prev_close"]
        open_price = fresh.get("open", 0)
        high = fresh["high"]
        low = fresh["low"]
        change_pct = fresh["change_pct"]
        change_amt = fresh.get("change_amt", 0)
        turnover = fresh["turnover_yi"]
        volume = fresh["volume"]
        data_fresh = True
        source = fresh["source"]
        order_book = fresh.get("order_book")
        volume_ratio = fresh.get("volume_ratio", 0)
        turnover_rate_api = fresh.get("turnover_rate", 0)
        circulating_mc_yi = fresh.get("circulating_mc_yi", 0)
        # 换手率: API直接给就用, 否则从流通市值算
        if turnover_rate_api:
            turnover_rate = turnover_rate_api
        elif circulating_mc_yi and circulating_mc_yi > 0 and price > 0:
            circ_units = circulating_mc_yi * 100000000 / price / 100
            turnover_rate = round(volume / circ_units * 100, 2) if circ_units > 0 else 0
        else:
            turnover_rate = 0
        ts = fresh.get("timestamp", now.strftime("%H:%M:%S"))

    # 历史记录：保留最近7个数据点(约35分钟，足够30分钟回溯)
    # 跨日清理：上午时段过滤掉昨天下午(>=12:00)的旧数据
    history = state.get("history", [])
    if history and now.hour < 12:
        filtered = []
        for h in history:
            try:
                h_hour = int(h.get("time", "00").split(":")[0])
            except (ValueError, IndexError):
                h_hour = 0
            if h_hour < 12:
                filtered.append(h)
        if len(filtered) != len(history):
            history = filtered
    if data_fresh:
        history.append({
            "price": price,
            "low": low,
            "high": high,
            "volume": volume,
            "change_pct": change_pct,
            "time": now.strftime("%H:%M:%S"),
        })
        # 只保留最近7条
        if len(history) > 7:
            history = history[-7:]

    # Update state
    state.update({
        "last_price_raw": price_raw,
        "last_price": price,
        "last_check": now.isoformat(),
    })
    if data_fresh:
        state.update({
            "prev_close": prev_close,
            "open": open_price if open_price else state.get("open", 0),
            "high": high,
            "low": low,
            "change_pct": change_pct,
            "turnover_yi": turnover,
            "volume": volume,
            "source": source,
            "order_book": order_book,
            "history": history,
            "volume_ratio": volume_ratio,
            "turnover_rate": turnover_rate,
            "circulating_mc_yi": circulating_mc_yi,
            "market": market,
            "technical": technical,
            "trend": trend,
        })
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False)

    # 从历史判断趋势
    # 30分钟内最低价
    low_30m = None
    avg_vol_30m = 0
    for h in history:
        if h["low"] is not None:
            if low_30m is None or h["low"] < low_30m:
                low_30m = h["low"]
    if history:
        avg_vol_30m = sum(h.get("volume", 0) for h in history) / len(history)

    # Change from last check
    last_price_raw_state = state.get("last_price_raw", 0)
    if "history" in state and len(state["history"]) >= 2:
        prev = state["history"][-2]["price"]
        if prev > 0:
            change_from_last = round((price - prev) / prev * 100, 4)
        else:
            change_from_last = 0.0
    else:
        change_from_last = 0.0

    # 判断条件汇总
    near_low = (price - low) / low * 100 < 0.15 if low > 0 else False  # 距最低<0.15%
    near_high = (high - price) / high * 100 < 0.15 if high > 0 else False
    continuous_fall = all(
        i == 0 or h["price"] <= history[i - 1]["price"]
        for i, h in enumerate(history)
    ) if len(history) >= 2 else False
    range_30m = (max(h["price"] for h in history) - min(h["price"] for h in history)) if len(history) >= 2 else 0
    sideways = range_30m / price * 100 < 0.25 if price > 0 and len(history) >= 3 else False
    volume_surge = volume > avg_vol_30m * 1.5 if avg_vol_30m > 0 else False
    bid_ask_ratio = 0
    if order_book:
        b1 = order_book.get("b1_vol", 0)
        a1 = order_book.get("a1_vol", 0)
        if a1 > 0:
            bid_ask_ratio = round(b1 / a1, 2)

    # 情绪指标
    # 1) 5分钟涨跌幅: 从历史中找最接近5分钟前的价格
    change_5min = 0.0
    if len(history) >= 2:
        target_minutes = now.hour * 60 + now.minute - 5
        best_entry = None
        best_diff = 999
        for h in history:
            try:
                hp = h["time"].split(":")
                hmin = int(hp[0]) * 60 + int(hp[1])
                diff = abs(hmin - target_minutes)
                if diff < best_diff:
                    best_diff = diff
                    best_entry = h
            except:
                pass
        if best_entry and best_entry.get("price", 0) > 0:
            change_5min = round((price - best_entry["price"]) / best_entry["price"] * 100, 2)

    # 2) 今日振幅: (最高-最低)/昨收*100
    amplitude = round((high - low) / prev_close * 100, 2) if prev_close > 0 else 0

    # 市场环境: 三大指数 + 北向资金
    if data_fresh:
        try:
            fresh_market = fetch_market_data(timeout=2)
            if fresh_market:
                market = fresh_market
        except Exception:
            pass

    # 技术指标: 5/10/20/60日均线 — 每日首次拉取，失败后每次重试
    last_check = state.get("last_check", "")
    prev_tech = state.get("technical", {})
    first_run_today = last_check[:10] != now.strftime("%Y-%m-%d")
    need_kline = first_run_today or not prev_tech
    if data_fresh and need_kline:
        try:
            tech = fetch_kline_mas(timeout=4)
            if tech:
                technical = tech
        except Exception:
            pass

    # 趋势判断：价 vs 均线
    if data_fresh and technical:
        p = price
        m20 = technical.get("ma20", 0)
        m60 = technical.get("ma60", 0)
        d20 = technical.get("ma20_dir", "—")
        d60 = technical.get("ma60_dir", "—")
        if m60 > 0 and p < m60 and d60 == "↓":
            scenario, risk = "⚠️ 跌破MA60+MA60下行", "高"
        elif m20 > 0 and p < m20 and d20 == "→":
            scenario, risk = "跌破MA20+MA20走平,趋势转弱", "中"
        elif m20 > 0 and p < m20 and d20 == "↑":
            scenario, risk = "回调至MA20,MA20仍向上", "低(正常回调)"
        elif m20 > 0 and p > m20 and d20 == "↑":
            scenario, risk = "价在MA20上方,MA20↑", "低(强势)"
        else:
            scenario, risk = "震荡整理", "中"
        trend = {"scenario": scenario, "risk": risk, "ma20_dir": d20, "ma60_dir": d60}

    is_alert = abs(change_from_last) > 0.5
    result = {
        "status": "alert" if is_alert else "update",
        "price": price,
        "prev_close": prev_close,
        "open": open_price,
        "high": high,
        "low": low,
        "change_pct": change_pct,
        "change_amt": round(change_amt, 3),
        "change_from_last": change_from_last,
        "volume": volume,
        "turnover_yi": turnover,
        "time": now.strftime("%H:%M:%S"),
        "data_fresh": data_fresh,
        "source": source,
        "order_book": order_book,
        "sentiment": {
            "change_5min": change_5min,
            "amplitude": amplitude,
            "volume_ratio": volume_ratio,
            "turnover_rate": turnover_rate,
        },
        "analysis": {
            "near_low": near_low,
            "near_high": near_high,
            "continuous_fall": continuous_fall,
            "sideways_30m": sideways,
            "volume_surge": volume_surge,
            "bid_ask_ratio": bid_ask_ratio,
            "low_30m": round(low_30m, 3) if low_30m else None,
            "avg_vol_30m": int(avg_vol_30m),
        },
        "history": history[-6:] if history else [],
        "market": market,
        "technical": technical,
        "trend": trend,
    }
    result["table_text"] = fmt_table(result, is_alert=is_alert)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
