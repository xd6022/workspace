#!/usr/bin/env python3
"""510210 + 上证综指 价格速递脚本"""
import urllib.request
import re
import json
import sys
from datetime import datetime

def fetch_quote(code):
    """获取腾讯行情数据"""
    url = f"https://qt.gtimg.cn/q={code}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("gbk")
    
    prefix = "v_" + code.replace("sh", "sh").replace("sz", "sz") + '="'
    match = re.search(re.escape(prefix) + r'([^"]+)"', raw)
    if not match:
        return None
    
    fields = match.group(1).split("~")
    price = float(fields[3])
    prev_close = float(fields[4])
    change = round(price - prev_close, 3)
    
    return {
        "name": fields[1],
        "code": fields[2],
        "price": price,
        "prev_close": prev_close,
        "open": float(fields[5]),
        "volume": int(fields[6]) if fields[6] else 0,
        "high": float(fields[33]) if fields[33] else price,
        "low": float(fields[34]) if fields[34] else price,
        "change": change,
        "change_pct": round(change / prev_close * 100, 2),
        "time": fields[30],
        "turnover": float(fields[37]) if fields[37] else 0,
    }

def main():
    etf = fetch_quote("sh510210")
    idx = fetch_quote("sh000001")
    
    now = datetime.now()
    time_str = now.strftime("%H:%M")
    
    print(f"📊 价格速递 | {time_str} CST\n")
    
    if idx:
        arrow = "🔺" if idx["change"] > 0 else "🔻" if idx["change"] < 0 else "➖"
        print(f"🏛️ 上证综指 {arrow} {idx['price']:.0f}  ({idx['change']:+.2f} / {idx['change_pct']:+.2f}%)")
        print(f"   昨收: {idx['prev_close']:.2f}  开: {idx['open']:.2f}")
    
    print()
    
    if etf:
        arrow = "🔺" if etf["change"] > 0 else "🔻" if etf["change"] < 0 else "➖"
        print(f"📈 510210 {etf['name']} {arrow}")
        print(f"   现价: {etf['price']:.3f}  ({etf['change']:+.3f} / {etf['change_pct']:+.2f}%)")
        print(f"   昨收: {etf['prev_close']:.3f}  今开: {etf['open']:.3f}")
        print(f"   最高: {etf['high']:.3f}  最低: {etf['low']:.3f}")
        print(f"   成交量: {etf['volume']:,} 手  成交额: {etf['turnover']:.0f} 万")
        
        # 关键价位提醒
        print(f"\n📌 关键价位参考:")
        cost = 0.971
        buy1 = 1.033
        buy2 = 1.047
        buy3_low, buy3_high = 0.995, 1.000
        strong_resist = 1.050
        iron_top = 1.058
        
        pos = 1000  # 持仓
        pnl = (etf['price'] - cost) * pos
        
        print(f"   成本: {cost:.3f}  持仓: {pos} 股  浮盈: ¥{pnl:.0f}")
        
        # 价格区间判断
        p = etf['price']
        if p >= iron_top:
            status = "🔴 铁顶区上方！"
        elif p >= strong_resist:
            status = "🟠 强阻力区 (1.050+)"
        elif p >= buy2:
            status = "🟡 接近第二买点 (1.047)"
        elif p >= buy1:
            status = "🟢 正常区间"
        elif p >= buy3_low:
            status = "🟡 接近第一买点 (1.033)"
        else:
            status = "🔴 真空区！"
        
        print(f"   区间: {status}")
        
        # 输出JSON供后续处理
        result = {"idx": idx, "etf": etf, "cost": cost, "position": pos, "pnl": round(pnl, 2)}
        with open("/tmp/price_snapshot.json", "w") as f:
            json.dump(result, f, ensure_ascii=False)

if __name__ == "__main__":
    main()
