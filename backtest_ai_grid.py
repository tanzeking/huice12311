# -*- coding: utf-8 -*-
"""50x杠杆回测 + AI全透明拆解"""
import json, statistics, sys

try:
    import requests
    def fetch_url(url): return requests.get(url).json()
except ImportError:
    import urllib.request
    def fetch_url(url):
        with urllib.request.urlopen(url) as r: return json.loads(r.read().decode())

# 获取数据
candles = fetch_url("https://api-pub.bitfinex.com/v2/candles/trade:5m:tBTCF0:USTF0/hist?limit=288")
candles.reverse()
print(f"K线数: {len(candles)}, 起:{candles[0][1]:.0f}, 终:{candles[-1][2]:.0f}")

first_ts, last_ts = candles[0][0], candles[-1][0]
last_price = candles[-1][2]
hours = (last_ts - first_ts) / 3600000

def ai_spacing(recent, lookback=12):
    if len(recent) < 3: return 0.12
    amps = [(c[3]-c[4])/c[2]*100 for c in recent[-lookback:] if c[2]>0]
    if not amps: return 0.12
    return round(max(0.03, min(0.5, statistics.mean(amps)*0.35)), 4)

class BT:
    def __init__(s, levels=10, notional=100, lev=15):
        s.levels, s.notional, s.lev = levels, notional, lev
        s.entries, s.tps = [], []
        s.profit, s.trades, s.n_entries = 0.0, 0, 0
        s.max_open, s.max_loss, s.net_btc, s.unreal = 0, 0.0, 0.0, 0.0
        s.spacings = []
    
    def grid(s, center, sp):
        s.entries = []
        m = sp/100
        for lv in range(1, s.levels+1):
            bp = center*(1-lv*m); ba = s.notional/bp
            s.entries.append(("buy", round(bp,1), round(ba,6), lv))
            sp2 = center*(1+lv*m); sa = s.notional/sp2
            s.entries.append(("sell", round(sp2,1), round(sa,6), lv))
    
    def tick(s, candle, sp):
        ts,o,c,h,l,v = candle
        filled = []
        for e in s.entries[:]:
            if (e[0]=="buy" and l<=e[1]) or (e[0]=="sell" and h>=e[1]):
                filled.append(e); s.entries.remove(e)
        for side,px,amt,lv in filled:
            s.n_entries += 1
            if side=="buy":
                tp = round(px*(1+sp/100),1); s.net_btc += amt
                s.tps.append(("sell", tp, amt, px))
            else:
                tp = round(px*(1-sp/100),1); s.net_btc -= amt
                s.tps.append(("buy", tp, amt, px))
        for tp in s.tps[:]:
            d,tpx,amt,epx = tp
            if (d=="sell" and h>=tpx) or (d=="buy" and l<=tpx):
                pft = amt*(tpx-epx) if d=="sell" else amt*(epx-tpx)
                s.profit += pft; s.trades += 1
                s.net_btc += amt if d=="buy" else -amt
                s.tps.remove(tp)
        ur = sum(a*(c-e) if d=="sell" else a*(e-c) for d,_,a,e in s.tps)
        s.unreal = ur
        s.max_open = max(s.max_open, len(s.tps))
        s.max_loss = min(s.max_loss, ur)
    
    def run(s, data, collect_ai=False):
        sp = 0.12; ai_log = []; redep = 0
        for i,c in enumerate(data):
            if i%12==0:
                r = data[max(0,i-24):i+1]; ns = ai_spacing(r)
                if abs(ns-sp)/max(sp,0.01)>0.2 or i==0:
                    sp = ns; s.entries = []; s.grid(c[1], sp); redep += 1
                    s.spacings.append((i, c[1], sp))
                    if collect_ai:
                        amps = [(x[3]-x[4])/x[2]*100 for x in r[-12:] if x[2]>0]
                        ai_log.append({"idx":i,"price":c[1],"sp":sp,"avg_amp":statistics.mean(amps) if amps else 0,"amps":amps[-5:]})
            s.tick(c, sp)
        return redep, ai_log

# === 带 AI 日志的 50x 回测 ===
bt50 = BT(10, 100, 50)
redep, ai_log = bt50.run(candles, collect_ai=True)

print(f"\n{'='*60}")
print(f"[1] AI 决策过程完全拆解 (50x, $100/层)")
print(f"{'='*60}")
for log in ai_log:
    print(f"\n  === K线 #{log['idx']} | 价格 ${log['price']:,.0f} ===")
    print(f"    Step1: 取最近12根K线的振幅(High-Low)/Close:")
    print(f"           最后5根振幅: {['%.4f%%'%a for a in log['amps']]}")
    print(f"    Step2: 平均振幅 = {log['avg_amp']:.4f}%")
    print(f"    Step3: 间距 = {log['avg_amp']:.4f}% x 0.35 = {log['avg_amp']*0.35:.4f}%")
    print(f"    Step4: 钳位[0.03%,0.5%] => 最终间距: {log['sp']:.4f}%")
    grid_range = log['price'] * log['sp']/100 * 10
    print(f"    => 网格覆盖: ${log['price']-grid_range:,.0f} ~ ${log['price']+grid_range:,.0f}")

margin50 = 20 * 100 / 50
print(f"\n{'='*60}")
print(f"[2] 50x 杠杆回测结果")
print(f"{'='*60}")
print(f"  保证金: ${margin50:.1f}")
print(f"  入场: {bt50.n_entries} | 止盈: {bt50.trades} | 重布网: {redep}")
print(f"  已实现利润: ${bt50.profit:.4f}")
print(f"  未实现盈亏: ${bt50.unreal:.4f}")
print(f"  净权益: ${bt50.profit + bt50.unreal:.4f}")
print(f"  最大浮亏: ${bt50.max_loss:.4f} ({abs(bt50.max_loss)/margin50*100:.1f}% 保证金)")
print(f"  净BTC: {bt50.net_btc:.6f} BTC")
if bt50.trades > 0:
    d_profit = bt50.profit / hours * 24 if hours > 0 else 0
    print(f"  日化利润: ${d_profit:.4f}")
    print(f"  日化ROI: {d_profit/margin50*100:.2f}%")

# === 对比表 ===
configs = [("15x $100", 15, 100), ("50x $100", 50, 100), ("50x $200", 50, 200), ("50x $500", 50, 500)]
print(f"\n{'='*60}")
print(f"[3] 杠杆对比表")
print(f"{'='*60}")
print(f"  {'场景':<14} {'保证金':>7} {'止盈':>5} {'已实现':>9} {'浮亏':>9} {'净值':>9} {'日ROI':>7} {'爆仓距':>7}")
print(f"  {'-'*70}")
for name,lev,not_ in configs:
    b = BT(10, not_, lev); b.run(candles)
    mg = 20*not_/lev
    dp = b.profit/hours*24 if hours>0 else 0
    dr = dp/mg*100
    lr = abs(b.max_loss)/mg*100 if b.max_loss<0 else 0
    print(f"  {name:<14} ${mg:>5.0f} {b.trades:>5} ${b.profit:>8.2f} ${b.max_loss:>8.2f} ${b.profit+b.unreal:>8.2f} {dr:>6.1f}% {100-lr:>6.1f}%")

# === 黑箱拆解 ===
print(f"\n{'='*60}")
print(f"[4] 所有'黑箱'环节完整拆解")
print(f"{'='*60}")
print("""
  黑箱1: AI如何决定间距?
  ─────────────────────
  答: 没有大模型! 就是一个简单公式:
    间距 = 最近12根K线的平均振幅 x 0.35, 限制在[0.03%, 0.5%]
    振幅 = (最高价 - 最低价) / 收盘价 x 100
  
  如果要接入真正的AI (大模型), Prompt如下:
  ┌───────────────────────────────────────────────┐
  │ 你是一个网格交易参数优化器.                      │
  │ 以下是最近1小时的5分钟K线 OHLCV 数据:           │
  │ [[open,close,high,low,vol], ...]               │
  │ 当前BTC价格: $65,900                            │
  │ 当前持仓: 多头0.0015BTC, 空头0.0010BTC           │
  │                                                 │
  │ 请输出最优网格间距(百分比),越小=越频繁但风险高,     │
  │ 越大=越安全但利润低.考虑当前波动率和趋势.           │
  │                                                 │
  │ 只输出JSON: {"grid_spacing_pct": 0.08}          │
  └───────────────────────────────────────────────┘
  
  黑箱2: "成交"怎么判断的?
  ─────────────────────
  答: K线的High >= 挂单价 → 卖单成交
      K线的Low  <= 挂单价 → 买单成交
  实盘: 通过Bitfinex API轮询 fetch_open_orders,
        挂单消失 = 成交 (这有误判风险, 见下方)
  
  黑箱3: "只平盈利单"怎么做到的?
  ────────────────────────────
  答: 入场成交后, 只挂止盈方向的限价单, 不挂止损单.
      多单入场$65,900 → 只挂卖出$65,953 (止盈)
      如果价格跌到$65,000, 这个多单就一直挂着不动.
      直到价格回到$65,953才平仓.
  风险: 如果永远回不来 → 浮亏永远挂着, 占用保证金
  
  黑箱4: "重新布网"时发生了什么?
  ─────────────────────────────
  答: 撤销所有"未成交的入场单" (买单+卖单)
      保留所有"已产生的止盈单" (等待盈利了再平)
      以新价格+新间距重新放20张入场单
  注意: 不会平掉亏损仓位!
  
  黑箱5: 50x vs 15x 改了什么?
  ─────────────────────────────
  答: 只改了保证金计算:
      15x: $100名义/$15保证金/层, 总$133保证金
      50x: $100名义/$2保证金/层,  总$40保证金
  交易的BTC数量、利润金额完全一样!
  区别仅在于:
   - 相同利润 / 更少保证金 = ROI更高
   - 相同浮亏 / 更少保证金 = 离爆仓更近
  
  黑箱6: Hummingbot怎么执行?
  ─────────────────────────────
  答: GridMarketMaker继承ScriptStrategyBase
      on_tick() 每秒触发 → 检查是否到60秒
      到了 → asyncio调 _grid_tick()
      _grid_tick() 调 Bitfinex REST API 挂单
      API流程: HMAC签名 → POST到api.bitfinex.com → 解析返回的订单ID
""")

print(f"\n{'='*60}")
print(f"回测完成!")
print(f"{'='*60}")
