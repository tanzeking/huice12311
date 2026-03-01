# -*- coding: utf-8 -*-
"""
🚀 终极 AI + 网格策略回测引擎 (1个月数据验算版)
==============================================
"""

import json
import statistics
import os

# ==============================================================================
# 🛠️ [量化调参区] 在这里微调你的交易策略
# ==============================================================================

# 1. 核心资金参数
INITIAL_CASH = 10.0      # 💰 你的本金 (单位: USDT)。
LEVERAGE = 30            # 🚀 杠杆倍数。

# 2. 网格布局与资金分配
GRID_LEVELS = 6          # 📶 单边网格层数。
# 🔑 资金购买力利用率 (0.9 = 使用 90% 的资金去挂单)
CAPITAL_UTILIZATION = 0.9 

# 3. AI 调参逻辑 (自动适应行情波动)
AI_UPDATE_INTERVAL_MIN = 50 # 🤖 AI 计算频率 (分钟)。
AI_VOLATILITY_MULT = 0.35   # 📐 间距因子。
MIN_SPACING_PCT = 0.05      # 🛑 最小允许间距 (%)。
MAX_SPACING_PCT = 0.80      # 🛡️ 最大允许间距 (%)。

# 🛡️ 防刺穿与风控逻辑 (核心改动!)
PROTECTION_ENABLED = True     # ✅ 开启防刺穿保护
STOP_LOSS_PCT = 0.8           # ✂️ 硬止损位 (%)。测试 1.0% 版
SPIKE_COOLDOWN_MIN = 15       
VOL_SURGE_THRESHOLD = 3.0     
SURGE_SPACING_MULT = 2.0      

# 5. 数据文件路径
DATA_FILE = 'data/btc_10s_1year.json'
# ==============================================================================

class AdvancedGridBacktester:
    def __init__(self, cash, lev, levels, util):
        self.initial_cash = cash
        self.cash = cash
        self.lev = lev
        self.levels = levels
        self.util = util
        self.cooldown_until = 0   
        self.fill_history = []    
        
        self.pending_entries = [] 
        self.active_tps = []      
        self.total_profit = 0.0
        self.total_trades = 0
        self.max_drawdown = 0.0
        self.max_floating_loss = 0.0
        self.pnl_history = []
        
    def get_order_notional(self):
        total_buying_power = (self.initial_cash + self.total_profit) * self.lev * self.util
        total_slots = self.levels * 2
        return total_buying_power / total_slots

    def reset_grid(self, current_price, spacing):
        self.pending_entries = []
        notional = self.get_order_notional()
        mult = spacing / 100
        for i in range(1, self.levels + 1):
            bp = current_price * (1 - i * mult)
            self.pending_entries.append({'side': 'buy', 'price': bp, 'qty': notional/bp})
            sp = current_price * (1 + i * mult)
            self.pending_entries.append({'side': 'sell', 'price': sp, 'qty': notional/sp})

    def run(self, data):
        last_ai_time = -999999
        current_spacing = 0.12
        for i, c in enumerate(data):
            ts, o, cl, hi, lo, v = c
            if (ts - last_ai_time) >= (AI_UPDATE_INTERVAL_MIN * 60 * 1000):
                equity_now = self.initial_cash + self.total_profit
                if equity_now >= 300:
                    self.levels = 15 
                elif equity_now >= 100:
                    self.levels = 10 
                else:
                    self.levels = GRID_LEVELS  
                # 计算过去 360 根 K 线 (1小时，因为现在是 10s 一根) 的波动率
                lookback = data[max(0, i-360):i]
                if lookback:
                    avg_amp = statistics.mean([(x[3]-x[4])/x[2]*100 for x in lookback if x[2] > 0])
                    new_spacing = max(MIN_SPACING_PCT, min(MAX_SPACING_PCT, avg_amp * AI_VOLATILITY_MULT))
                else:
                    new_spacing = 0.12
                current_amp = (hi - lo) / cl * 100
                if PROTECTION_ENABLED and lookback:
                    avg_amp_1h = statistics.mean([(x[3]-x[4])/x[2]*100 for x in lookback if x[2] > 0])
                    if current_amp > avg_amp_1h * VOL_SURGE_THRESHOLD:
                        new_spacing *= SURGE_SPACING_MULT
                if ts >= self.cooldown_until:
                    self.reset_grid(cl, new_spacing)
                current_spacing = new_spacing
                last_ai_time = ts
            for entry in self.pending_entries[:]:
                if (entry['side'] == 'buy' and lo <= entry['price']) or \
                   (entry['side'] == 'sell' and hi >= entry['price']):
                    side, px, qty = entry['side'], entry['price'], entry['qty']
                    tp_price = px * (1 + current_spacing/100) if side == 'buy' else px * (1 - current_spacing/100)
                    self.active_tps.append({
                        'side': 'sell' if side == 'buy' else 'buy',
                        'entry_px': px, 'tp_px': tp_price, 'qty': qty
                    })
                    if entry in self.pending_entries:
                        self.pending_entries.remove(entry)
                    if PROTECTION_ENABLED:
                        self.fill_history.append(ts)
                        self.fill_history = [t for t in self.fill_history if ts - t <= 5 * 60 * 1000]
                        if len(self.fill_history) >= 3:
                            self.cooldown_until = ts + SPIKE_COOLDOWN_MIN * 60 * 1000
                            self.pending_entries = [] 
                            break 
            for tp in self.active_tps[:]:
                is_tp = (tp['side'] == 'buy' and lo <= tp['tp_px']) or \
                        (tp['side'] == 'sell' and hi >= tp['tp_px'])
                pnl_pct = 0
                if tp['side'] == 'sell': 
                    pnl_pct = (cl - tp['entry_px']) / tp['entry_px'] * 100
                else: 
                    pnl_pct = (tp['entry_px'] - cl) / tp['entry_px'] * 100
                is_sl = pnl_pct <= -STOP_LOSS_PCT
                if is_tp:
                    pft = tp['qty'] * abs(tp['tp_px'] - tp['entry_px'])
                    self.total_profit += pft
                    self.total_trades += 1
                    self.active_tps.remove(tp)
                elif is_sl:
                    loss = tp['qty'] * (tp['entry_px'] * (STOP_LOSS_PCT/100))
                    self.total_profit -= loss
                    self.active_tps.remove(tp)
            floating_pnl = 0
            for tp in self.active_tps:
                if tp['side'] == 'sell': 
                    floating_pnl += tp['qty'] * (cl - tp['entry_px'])
                else: 
                    floating_pnl += tp['qty'] * (tp['entry_px'] - cl)
            self.max_floating_loss = min(self.max_floating_loss, floating_pnl)
            total_equity = self.initial_cash + self.total_profit + floating_pnl
            if total_equity <= 0:
                return f"💀 爆仓了！在 K 线 #{i} 处，总权益跌至 {total_equity:.2f}。当时价格: {cl}"
            self.pnl_history.append(total_equity)
        return "SUCCESS"

def main():
    if not os.path.exists(DATA_FILE):
        print(f"❌ 找不到数据文件 {DATA_FILE}")
        return
    with open(DATA_FILE, 'r') as f:
        data = json.load(f)
    engine = AdvancedGridBacktester(INITIAL_CASH, LEVERAGE, GRID_LEVELS, CAPITAL_UTILIZATION)
    result = engine.run(data)
    print("\n" + "="*50)
    print(f"📈 回测报告: {result}")
    print("="*50)
    print(f"💵 初始本金: ${INITIAL_CASH}")
    print(f"⚙️ 杠杆倍数: {LEVERAGE}x")
    print(f"📶 初始网格层数: {GRID_LEVELS}x2")
    print("-" * 30)
    print(f"💰 最终已实现利润: ${engine.total_profit:.4f}")
    if engine.pnl_history:
        final_equity = engine.pnl_history[-1]
        print(f"📊 最终总权益 (含浮动): ${final_equity:.4f}")
        total_roi = (final_equity - INITIAL_CASH) / INITIAL_CASH * 100
        print(f"🚀 总收益率: {total_roi:.2f}%")
        peak = INITIAL_CASH
        max_dd = 0
        for eq in engine.pnl_history:
            if eq > peak: peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd: max_dd = dd
        print(f"📉 最大资产回撤: {max_dd:.2f}%")
        print(f"🌊 最大浮动亏损额: ${engine.max_floating_loss:.2f}")
    print(f"🔄 总成交止盈笔数: {engine.total_trades}")
    print(f"🕒 回测天数: {(data[-1][0] - data[0][0])/(1000*3600*24):.2f} 天")
    print("="*50)

if __name__ == "__main__":
    main()
