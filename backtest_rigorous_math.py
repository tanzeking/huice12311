import os
import csv
import statistics

# ==============================================================================
# 🎯 [严谨数学模型：动态名额置换版]
# ==============================================================================
INITIAL_CASH = 1000.0
LEVERAGE = 5.0
GRID_LEVELS_PER_SIDE = 6
CAPITAL_UTILIZATION = 0.95
SPACING_PCT = 0.01  # 0.01% 极致高频
RE_CENTER_MS = 60000 # 1分钟重置中心

CSV_DIR = 'data_processed_10s'

class RigorousBacktester:
    def __init__(self):
        self.cash = INITIAL_CASH
        self.total_profit = 0.0        # 已实现盈亏 (Realized)
        self.long_tps = []             # 多单仓库 (Max 6)
        self.short_tps = []            # 空单仓库 (Max 6)
        self.pending_buys = []
        self.pending_sells = []
        self.last_reset = -1e15
        self.displacement_loss = 0.0   # 统计为了腾挪名额割掉的肉
        self.total_trades = 0
        self.pnl_history = []

    def get_equity(self, cl):
        # 严谨的 Equity 计算：本金 + 已实现 + 所有持仓浮动盈亏
        u_long = sum([o['qty'] * (cl - o['entry']) for o in self.long_tps])
        u_short = sum([o['qty'] * (o['entry'] - cl) for o in self.short_tps])
        return self.cash + self.total_profit + u_long + u_short

    def manage_slots_and_reset(self, cl):
        basis = self.cash + self.total_profit
        # 每格固定名义价值 = (当前本金 * 杠杆 * 利用率) / 12
        notional_per_grid = (basis * LEVERAGE * CAPITAL_UTILIZATION) / (GRID_LEVELS_PER_SIDE * 2)
        m = SPACING_PCT / 100

        # --- 多单名额置换 (Displacement) ---
        if len(self.long_tps) == GRID_LEVELS_PER_SIDE:
            # 找到最高位的死单
            highest = max(self.long_tps, key=lambda x: x['entry'])
            # 如果当前价格偏离死单超过 1% (为了效率，不设死等，只要偏离就换位)
            if cl < highest['entry'] * 0.99:
                # 割肉最高位，腾出名额
                self.total_profit += (cl - highest['entry']) * highest['qty']
                self.displacement_loss += abs((cl - highest['entry']) * highest['qty'])
                self.long_tps.remove(highest)

        # --- 空单名额置换 ---
        if len(self.short_tps) == GRID_LEVELS_PER_SIDE:
            lowest = min(self.short_tps, key=lambda x: x['entry'])
            if cl > lowest['entry'] * 1.01:
                self.total_profit += (lowest['entry'] - cl) * lowest['qty']
                self.displacement_loss += abs((lowest['entry'] - cl) * lowest['qty'])
                self.short_tps.remove(lowest)

        # 重新补齐挂单
        self.pending_buys = []
        l_needed = GRID_LEVELS_PER_SIDE - len(self.long_tps)
        for i in range(1, l_needed + 1):
            px = cl * (1 - i * m)
            self.pending_buys.append({'price': px, 'qty': notional_per_grid / px})

        self.pending_sells = []
        s_needed = GRID_LEVELS_PER_SIDE - len(self.short_tps)
        for i in range(1, s_needed + 1):
            px = cl * (1 + i * m)
            self.pending_sells.append({'price': px, 'qty': notional_per_grid / px})

    def process_candle(self, ts, cl, hi, lo):
        # 1-min 重置逻辑
        if ts - self.last_reset >= RE_CENTER_MS:
            self.manage_slots_and_reset(cl)
            self.last_reset = ts

        # 处理成交 (Taker/Maker 模拟)
        for e in self.pending_buys[:]:
            if lo <= e['price']:
                self.long_tps.append({'entry': e['price'], 'qty': e['qty'], 'tp': e['price']*(1+SPACING_PCT/100)})
                self.pending_buys.remove(e)
        for e in self.pending_sells[:]:
            if hi >= e['price']:
                self.short_tps.append({'entry': e['price'], 'qty': e['qty'], 'tp': e['price']*(1-SPACING_PCT/100)})
                self.pending_sells.remove(e)

        # 处理止盈
        for p in self.long_tps[:]:
            if hi >= p['tp']:
                self.total_profit += p['qty'] * (p['tp'] - p['entry'])
                self.total_trades += 1; self.long_tps.remove(p)
        for p in self.short_tps[:]:
            if lo <= p['tp']:
                self.total_profit += p['qty'] * (p['entry'] - p['tp'])
                self.total_trades += 1; self.short_tps.remove(p)

        # 最终 Equity
        eq = self.get_equity(cl)
        if eq <= 0: return False, 0
        self.pnl_history.append(eq)
        return True, eq

def run():
    files = sorted([f for f in os.listdir(CSV_DIR) if f.endswith('.csv')])
    engine = RigorousBacktester()
    
    print(f"🔬 启动 [严谨数学模型] 年度回归测试...")
    print(f"配置：1000U | 5x | 0.01% 高频 | 1-min 名额置换")

    for day_file in files:
        with open(os.path.join(CSV_DIR, day_file), 'r') as f:
            for row in csv.reader(f):
                ok, eq = engine.process_candle(int(row[0]), float(row[2]), float(row[3]), float(row[4]))
                if not ok:
                    print(f"DIE: {day_file}")
                    return
        # 每月打印进度
        if int(day_file[5:7]) % 1 == 0 and day_file.endswith('01.csv'):
             print(f"Day {day_file}: Equity ${round(eq, 2)} Trades: {engine.total_trades} (Loss from displacement: ${round(engine.displacement_loss, 2)})")

    print("\n" + "="*50)
    print(f"📊 严谨版年度结算报告")
    print("="*50)
    print(f"最终资金 (Equity): ${round(engine.pnl_history[-1], 2)}")
    print(f"置换割肉总损耗: ${round(engine.displacement_loss, 2)}")
    print(f"极致高频总利润: ${round(engine.total_profit + engine.displacement_loss, 2)}")
    print(f"总成交数: {engine.total_trades} 笔")
    print("="*50)

if __name__ == "__main__":
    run()
