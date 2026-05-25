#!/usr/bin/env python3
"""510210 成交分布分析 — 过去30日成交量剖面"""

import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
WORKSPACE = "/home/node/.openclaw/workspace"
STATE_FILE = f"{WORKSPACE}/memory/510210-state.json"
N_DAYS = 30
N_BINS = 25

SINA_KLINE = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData?symbol=sh510210&scale=60&datalen=70"
)

TENCENT_QUOTE = "https://qt.gtimg.cn/q=sh510210"


def fetch_text(url, timeout=10):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Connection": "close",
            "Referer": "https://finance.sina.com.cn",
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


def get_current_price():
    """从腾讯接口获取当前价（盘中实时）"""
    try:
        import re
        text = fetch_text(TENCENT_QUOTE, timeout=5)
        m = re.search(r'v_sh510210="([^"]*)"', text, re.DOTALL)
        if m:
            fs = m.group(1).split("~")
            return float(fs[3])
    except Exception:
        pass
    return None


def compute_volume_profile():
    """计算30日成交量分布"""
    text = fetch_text(SINA_KLINE, timeout=10)
    data = json.loads(text)

    days = []
    for d in data:
        try:
            o = float(d.get("open", 0) or 0)
            c = float(d.get("close", 0) or 0)
            h = float(d.get("high", 0) or 0)
            l = float(d.get("low", 0) or 0)
            v = float(d.get("volume", 0) or 0)
            if o > 0 and c > 0 and v > 0:
                days.append((o, c, h, l, v))
        except (ValueError, TypeError):
            continue

    days = days[-N_DAYS:]

    all_low = min(d[3] for d in days)
    all_high = max(d[2] for d in days)
    if all_high <= all_low:
        return None

    bin_width = (all_high - all_low) / N_BINS
    bins = [all_low + i * bin_width for i in range(N_BINS + 1)]
    vol_profile = [0.0] * N_BINS

    for o, c, h, l, v in days:
        li = int((l - all_low) / bin_width)
        hi = int((h - all_low) / bin_width)
        li = max(0, min(li, N_BINS - 1))
        hi = max(0, min(hi, N_BINS - 1))
        if hi < li:
            continue
        n = hi - li + 1
        ci = int((c - all_low) / bin_width)
        ci = max(li, min(ci, hi))
        for i in range(li, hi + 1):
            dist = abs(i - ci)
            w = max(1, 5 - dist)
            vol_profile[i] += v * w / n

    total = sum(vol_profile)
    if total <= 0:
        return None

    ranked = sorted(enumerate(vol_profile), key=lambda x: -x[1])[:5]
    top5 = []
    for rank, (idx, vol) in enumerate(ranked, 1):
        top5.append({
            "rank": rank,
            "low": round(bins[idx], 3),
            "high": round(bins[idx + 1], 3),
            "pct": round(vol / total * 100, 1),
        })

    return {
        "days": len(days),
        "price_low": round(all_low, 3),
        "price_high": round(all_high, 3),
        "top5": top5,
        "bins": [round(b, 3) for b in bins],
        "profile": [round(v / total * 100, 1) for v in vol_profile],
        "total_volume_m": round(sum(d[4] for d in days) / 10000, 0),
    }


def main():
    now = datetime.now(CST)

    # Get current price
    current_price = get_current_price()

    # Compute volume profile
    profile = compute_volume_profile()
    if profile is None:
        print(json.dumps({"status": "error", "reason": "profile_failed"}))
        return

    # Find where current price sits in the profile
    price_position = None
    if current_price and profile["bins"]:
        for i in range(len(profile["bins"]) - 1):
            if profile["bins"][i] <= current_price <= profile["bins"][i + 1]:
                price_position = {
                    "bin_idx": i,
                    "pct": profile["profile"][i],
                    "low": profile["bins"][i],
                    "high": profile["bins"][i + 1],
                }
                break

    result = {
        "status": "ok",
        "current_price": round(current_price, 3) if current_price else None,
        "price_position": price_position,
        "profile": profile,
        "time": now.strftime("%H:%M"),
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
