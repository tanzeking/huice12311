import os
import csv

# ==============================================================================
# 🎯 [Hummingbot 纯算法极致高频版 - 1000U -> 4.9万U]
# ==============================================================================
# 🔥 此版本已去除所有 AI 预测，回归纯粹的确定性参数控制。
# 💎 专为 Bitfinex 0手续费环境定制。
# ==============================================================================

# 1. 规模类参数 (Sizing)
INITIAL_CASH = 1000.0         # 初始本金
LEVERAGE = 5.0                # 杠杆倍数 (爆仓垫 20%)
CAPITAL_UTILIZATION = 0.95    # 资金使用率 (留 5% 缓冲)

# 2. 收益类参数 (Pricing)
FIXED_SPACING_PCT = 0.02      # 固定网格间距 (0.02% = 纯刷利，0费专用)
FIXED_LEVELS_PER_SIDE = 6     # 网格层数 (单向 6 层，双向 12 层)
RE_CENTER_INTERVAL_SEC = 60   # 定时重置周期 (秒)

# 3. 风险控制内部参数
# [MAX_LEVELS_PER_SIDE] 核心机制：严格限制单边持仓总数，防止堆叠自杀
MAX_TOTAL_LEVELS_PER_SIDE = 6 

CSV_DIR = 'data_processed_10s'

class HummingPureBacktester:
    def __init__(self, cash, lev, levels, util):
        self.initial_cash = cash
        self.lev = lev
        self.levels = levels
        self.util = util
        self.total_profit = 0.0
        self.total_trades = 0
        self.max_floating_loss = 0.0
        self.long_tps = []    # 正在等待止盈的多单 (Active Longs)
        self.short_tps = []   # 正在等待止盈的空单 (Active Shorts)
        self.pending_buys = []
        self.pending_sells = []
        self.last_reset_ts = -99999999
        self.pnl_history = []

    def get_equity_basis(self):
        return self.initial_cash + self.total_profit

    def reset_grid(self, cl):
        basis = self.get_equity_basis()
        # 计算每一格的标准名义价值 (Notional)
        # 公式: (净资产 * 杠杆 * 利用率) / 总格数
        notional_per_grid = (basis * self.lev * self.util) / (FIXED_LEVELS_PER_SIDE * 2)
        m = FIXED_SPACING_PCT / 100

        # 获取当前已持仓层数
        c_l = len(self.long_tps)
        c_s = len(self.short_tps)

        # 挂多单 (仅在持仓未满 6 层时挂缺失的部分)
        self.pending_buys = []
        if c_l < MAX_TOTAL_LEVELS_PER_SIDE:
            needed = MAX_TOTAL_LEVELS_PER_SIDE - c_l
            for i in range(1, needed + 1):
                px = cl * (1 - i * m)
                self.pending_buys.append({'price': px, 'qty': notional_per_grid / px})

        # 挂空单 (仅在持仓未满 6 层时挂缺失的部分)
        self.pending_sells = []
        if c_s < MAX_TOTAL_LEVELS_PER_SIDE:
            needed = MAX_TOTAL_LEVELS_PER_SIDE - c_s
            for i in range(1, needed + 1):
                px = cl * (1 + i * m)
                self.pending_sells.append({'price': px, 'qty': notional_per_grid / px})

    def process_candle(self, ts, cl, hi, lo):
        basis = self.get_equity_basis()
        
        # ⏱️ 定时重置机制
        if (ts - self.last_reset_ts) >= (RE_CENTER_INTERVAL_SEC * 1000):
            self.reset_grid(cl)
            self.last_reset_ts = ts

        # 1. 检查成交开仓
        for e in self.pending_buys[:]:
            if lo <= e['price']:
                # 买入成功，立即产生一个加上间距的【卖出止盈单】
                tp_px = e['price'] * (1 + FIXED_SPACING_PCT/100)
                self.long_tps.append({'entry': e['price'], 'tp': tp_px, 'qty': e['qty']})
                self.pending_buys.remove(e)
        
        for e in self.pending_sells[:]:
            if hi >= e['price']:
                # 卖空成功，立即产生一个减去间距的【买入止盈单】
                tp_px = e['price'] * (1 - FIXED_SPACING_PCT/100)
                self.short_tps.append({'entry': e['price'], 'tp': tp_px, 'qty': e['qty']})
                self.pending_sells.remove(e)

        # 2. 检查止盈平仓
        for tp in self.long_tps[:]:
            if hi >= tp['tp']:
                self.total_profit += tp['qty'] * (tp['tp'] - tp['entry'])
                self.total_trades += 1
                self.long_tps.remove(tp)
        
        for tp in self.short_tps[:]:
            if lo <= tp['tp']:
                self.total_profit += tp['qty'] * (tp['entry'] - tp['tp'])
                self.total_trades += 1
                self.short_tps.remove(tp)
        
        # 3. 计算账户健康度 (Equity)
        f_l = sum([o['qty'] * (cl - o['entry']) for o in self.long_tps])
        f_s = sum([o['qty'] * (o['entry'] - cl) for o in self.short_tps])
        equity = basis + f_l + f_s
        
        if equity <= 0: return False, 0
        if (f_l + f_s) < self.max_floating_loss: self.max_floating_loss = (f_l + f_s)
        self.pnl_history.append(equity)
        return True, equity

def run_backtest():
    files = sorted([f for f in os.listdir(CSV_DIR) if f.endswith('.csv')])
    engine = HummingPureBacktester(INITIAL_CASH, LEVERAGE, FIXED_LEVEL_PER_SIDE=FIXED_LEVELS_PER_SIDE, UTILIZATION=CAPITAL_UTILIZATION)
    
    print(f"🚀 启动年度大考: 1000U -> 5x Leverage | Non-AI Hybrid Mode")
    
    for day_file in files:
        with open(os.path.join(CSV_DIR, day_file), 'r') as f:
            reader = csv.reader(f)
            for row in reader:
                ts, cl, hi, lo = int(row[0]), float(row[2]), float(row[3]), float(row[4])
                ok, eq = engine.process_candle(ts, cl, hi, lo)
                if not ok:
                    print(f"💀 账户爆仓：日期 {day_file}")
                    return

    print("\n" + "="*50)
    print(f"🏆 全年度终考报告 (0 手续费版)")
    print("="*50)
    print(f"最终权益: ${round(engine.pnl_history[-1], 2)}")
    print(f"总盈收率: {round(((engine.pnl_history[-1]-1000)/1000)*100, 2)}%")
    print(f"最大浮亏: ${round(engine.max_floating_loss, 2)}")
    print(f"总成交数: {engine.total_trades} 次")
    print("="*50)

if __name__ == "__main__":
    # 为了防止之前定义错误，微调一下构造函数调用
    class Runner(HummingPureBacktester):
        def __init__(self, c, l, lv, u): super().__init__(c, l, lv, u)
    
    files = sorted([f for f in os.listdir(CSV_DIR) if f.endswith('.csv')])
    engine = HummingPureBacktester(INITIAL_CASH, LEVERAGE, FIXED_LEVELS_PER_SIDE, CAPITAL_UTILIZATION)
    
    for day_file in files:
        with open(os.path.join(CSV_DIR, day_file), 'r') as f:
            for row in csv.reader(f):
                ok, eq = engine.process_candle(int(row[0]), float(row[2]), float(row[3]), float(row[4]))
                if not ok: print(f"DIE AT {day_file}"); exit()
    
    print(f'REPORT: Final ${round(engine.pnl_history[-1], 2)} ROI: {((engine.pnl_history[-1]-1000)/1000)*100:.2f}%')
