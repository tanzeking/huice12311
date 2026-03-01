import os
import csv
import statistics

# ==============================================================================
# 🎯 [不对称对冲实战配置]
# ==============================================================================
INITIAL_CASH = 1000.0
LEVERAGE = 10
GRID_LEVELS = 6
CAPITAL_UTILIZATION = 0.9

DEFAULT_LONG_WEIGHT = 1.0   # 多单基准量
DEFAULT_SHORT_WEIGHT = 0.6  # 空单基准量 (默认对冲 60%)
DEFENSIVE_SHORT_MULT = 2.5  # 🚨 触发防御时，空单量扩大倍数
DD_THRESHOLD = 0.10         # 多单浮亏 10% 触发防御

AI_UPDATE_MIN = 1           # 极速 1 分钟更新
CSV_DIR = 'data_processed_10s'
# ==============================================================================

class AsymmetricHedgeBacktester:
    def __init__(self, cash, lev, levels, util):
        self.initial_cash, self.lev, self.base_levels, self.levels, self.util = cash, lev, levels, levels, util
        self.total_profit, self.total_trades, self.max_floating_loss, self.pnl_history = 0.0, 0, 0.0, []
        self.long_tps, self.short_tps = [], []
        self.pending_buys, self.pending_sells = [], []
        
    def get_equity_basis(self): return self.initial_cash + self.total_profit

    def reset_grid(self, cl, spacing, l_drawdown):
        self.pending_buys, self.pending_sells = [], []
        basis = self.get_equity_basis()
        
        # 计算每一格的基准名义价值
        n_base = basis * self.lev * self.util / (self.levels * 4)
        m = spacing / 100
        
        # 🛡️ 不对称逻辑：判定是否开启超额对冲
        s_weight = DEFAULT_SHORT_WEIGHT
        if l_drawdown > DD_THRESHOLD:
            s_weight = DEFAULT_SHORT_WEIGHT * DEFENSIVE_SHORT_MULT
        
        for i in range(1, self.levels + 1):
            bp = cl * (1 - i * m)
            self.pending_buys.append({'price': bp, 'qty': (n_base * DEFAULT_LONG_WEIGHT)/bp})
            sp = cl * (1 + i * m)
            self.pending_sells.append({'price': sp, 'qty': (n_base * s_weight)/sp})

    def process_candle(self, ts, cl, hi, lo, last_ai, space, lookback):
        basis = self.get_equity_basis()
        f_long = sum([tp['qty']*(cl-tp['entry_px']) for tp in self.long_tps])
        l_drawdown = abs(f_long) / basis if f_long < 0 else 0
        
        if (ts - last_ai) >= 60000:
            if lookback:
                avg = statistics.mean([(x[1]-x[2])/x[0]*100 for x in lookback if x[0]>0])
                space = max(0.05, min(0.8, avg * 0.35))
            self.reset_grid(cl, space, l_drawdown)
            last_ai = ts

        # 开仓
        for e in self.pending_buys[:]:
            if lo <= e['price']:
                tp_px = e['price'] * (1 + space/100)
                self.long_tps.append({'entry_px': e['price'], 'tp_px': tp_px, 'qty': e['qty']})
                self.pending_buys.remove(e)
        for e in self.pending_sells[:]:
            if hi >= e['price']:
                tp_px = e['price'] * (1 - space/100)
                self.short_tps.append({'entry_px': e['price'], 'tp_px': tp_px, 'qty': e['qty']})
                self.pending_sells.remove(e)

        # 止盈
        for tp in self.long_tps[:]:
            if hi >= tp['tp_px']:
                self.total_profit += tp['qty'] * (tp['tp_px'] - tp['entry_px'])
                self.total_trades += 1; self.long_tps.remove(tp)
        for tp in self.short_tps[:]:
            if lo <= tp['tp_px']:
                self.total_profit += tp['qty'] * (tp['entry_px'] - tp['tp_px'])
                self.total_trades += 1; self.short_tps.remove(tp)
        
        # 实时资产净值
        f_long = sum([tp['qty']*(cl-tp['entry_px']) for tp in self.long_tps])
        f_short = sum([tp['qty']*(tp['entry_px']-cl) for tp in self.short_tps])
        total_equity = basis + f_long + f_short
        
        if total_equity <= 0: return False, 0, 0, 0
        self.pnl_history.append(total_equity)
        return True, last_ai, space, total_equity

def run():
    files = sorted([f for f in os.listdir(CSV_DIR) if f.endswith('.csv')])
    engine, last_ai, space, lookback = AsymmetricHedgeBacktester(INITIAL_CASH, LEVERAGE, GRID_LEVELS, CAPITAL_UTILIZATION), -99999999, 0.12, []
    
    print(f"🚀 开始年度'不对称对冲'大考...")
    print(f"基础配比: 多 100% / 空 60% | 防御倍率: {DEFENSIVE_SHORT_MULT}x")
    
    for day_file in files:
        with open(os.path.join(CSV_DIR, day_file), 'r') as f:
            reader = csv.reader(f)
            for row in reader:
                ts, cl, hi, lo = int(row[0]), float(row[2]), float(row[3]), float(row[4])
                ok, last_ai, space, eq = engine.process_candle(ts, cl, hi, lo, last_ai, space, lookback)
                if not ok: print(f"💀 爆仓了！日期: {day_file}"); return
                lookback.append([cl, hi, lo])
                if len(lookback) > 360: lookback.pop(0)

    final_eq = engine.pnl_history[-1]
    print("\n" + "="*50)
    print(f"🏆 年度最终大考结果")
    print("="*50)
    print(f"最终资产: ${round(final_eq, 2)}")
    print(f"总盈收率: {round(((final_eq-INITIAL_CASH)/INITIAL_CASH)*100, 2)}%")
    print(f"总成交数: {engine.total_trades} 笔")
    print("="*50)

if __name__ == "__main__":
    run()
