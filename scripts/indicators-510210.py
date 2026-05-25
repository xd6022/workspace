#!/usr/bin/env python3
"""510210 技术指标推送 — 抓取行情 + 均线，输出预格式化文本。
模型只需读输出 → 发送，不再手工解析原始数据。
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


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


def fetch_tencent_510210():
    """抓取腾讯行情 510210"""
    text = fetch_text("https://qt.gtimg.cn/q=sh510210", timeout=5)
    match = re.search(r'v_sh510210="([^"]*)"', text, re.DOTALL)
    if not match:
        return None
    fields = match.group(1).split("~")
    if len(fields) < 51:
        return None
    # 自适应偏移
    off = -1 if (len(fields) > 30 and fields[30].strip().isdigit() and len(fields[30].strip()) == 14) else 0
    try:
        return {
            "name": fields[1],
            "price": round(float(fields[3]), 3),
            "prev_close": round(float(fields[4]), 3),
            "open": round(float(fields[5]), 3),
            "high": round(float(fields[34 + off]), 3),
            "low": round(float(fields[35 + off]), 3),
            "volume": int(fields[6]),
            "turnover_wan": float(fields[38 + off]) if fields[38 + off] else 0,
            "change_pct": round(float(fields[33 + off]), 2),
            "turnover_rate": round(float(fields[39 + off]), 2) if fields[39 + off] else 0,
            "volume_ratio": round(float(fields[50 + off]), 2) if fields[50 + off] else 0,
            "timestamp": fields[31 + off] if len(fields) > 31 + off else "",
        }
    except (ValueError, IndexError):
        return None


def fetch_kline_mas():
    """获取日K线并计算5/10/20/60日均线 + 方向"""
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
        closes_hist = closes[:-1]  # 排除今日

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
            "close_count": len(closes_hist),
        }
    except Exception:
        return None


def fmt_output(quote, mas, time_str):
    """生成预格式化文本，模型直接拿去发"""
    p = quote["price"]
    prev = quote["prev_close"]
    change = round(p - prev, 3)
    change_pct = quote["change_pct"]
    volume_wan = quote["volume"] // 10000
    turnover_yi = round(quote["turnover_wan"] / 10000, 2)
    amplitude = round((quote["high"] - quote["low"]) / prev * 100, 2)

    lines = [
        f"📊 510210 今日技术指标（{time_str}）",
        f"━━━━━━━━━━━━━━",
        f"现价: {p:.3f}  涨跌: {change:+.3f} ({change_pct:+.2f}%)",
        f"昨收: {prev:.3f}  今开: {quote['open']:.3f}",
        f"最高: {quote['high']:.3f}  最低: {quote['low']:.3f}",
        f"成交量: {volume_wan}万手  成交额: {turnover_yi:.2f}亿",
        f"━━━━━━━━━━━━━━",
        f"振幅: {amplitude:.2f}% │ 量比: {quote['volume_ratio']:.2f} │ 换手率: {quote['turnover_rate']:.2f}%",
    ]

    if mas:
        ma20_dir = mas.get("ma20_dir", "→")
        ma60_dir = mas.get("ma60_dir", "→")
        lines.append(f"MA5: {mas['ma5']:.3f}  MA10: {mas['ma10']:.3f}")
        lines.append(f"MA20: {mas['ma20']:.3f}{ma20_dir}  MA60: {mas['ma60']:.3f}{ma60_dir}")
        # 价-均线关系
        above_ma20 = "✅ 上方" if p > mas["ma20"] else "⚠️ 下方"
        above_ma60 = "✅ 上方" if p > mas["ma60"] else "⚠️ 下方"
        lines.append(f"价 vs MA20: {above_ma20}  │ 价 vs MA60: {above_ma60}")
        lines.append(f"━━━━━━━━━━━━━━")

    return "\n".join(lines)


def main():
    now = datetime.now(CST)
    time_str = now.strftime("%H:%M:%S")

    quote = fetch_tencent_510210()
    if quote is None:
        print(json.dumps({"status": "error", "reason": "fetch_failed", "text": "⚠️ 510210 技术指标获取失败，请手动查看"}))
        return

    mas = fetch_kline_mas()

    formatted = fmt_output(quote, mas, time_str)
    result = {"status": "ok", "text": formatted}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
