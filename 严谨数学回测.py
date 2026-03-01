"""
================================================================================
严谨数学回测 v36：十倍火力版 (10x 有效杠杆 / 非对称间距 0.1%v0.2% / 防重叠)
================================================================================

核心修复:
  1. 【十倍火力】：本金利用率 1.0。目标：用 $1000 本金驱动约 $10,000 的总名义价值。
  2. 【间距进化】：顺势 0.1% (密集收割) / 逆势 0.2% (深海防御)。
================================================================================
"""

import os
import csv
import io
import zipfile
import collections
from datetime import datetime

# ==============================================================================
# 策略参数配置
# ==============================================================================
INITIAL_CASH = 1000.0        # 初始本金 1000 USDT
LEV_CENTER = 30.0            # 离现价最近的第1层：30倍重锤
LEV_HIGH = 20.0              # 随后各层顺势杠杆：20倍
LEV_LOW = 10.0               # 随后各层逆势杠杆：10倍
CAPITAL_UTILIZATION = 0.1      # 降至 0.1，即 $1000 本金铺设约 $1000 总网格价值
GAP_TREND = 0.1              # 顺势网格基础间距 (密集收割)
GAP_COUNTER = 0.2            # 逆势网格基础间距 (宽幅防御)
UNIT_GAP_PCT = 0.1           # (已废弃，由上下变量替代)
TREND_TP_PCT = 0.8           # 顺势单止盈：0.8%
COUNTER_TP_PCT = 0.3         # 逆势单止盈：0.3%
LEVELS_PER_SIDE = 10         # 单向层数：10 层
MART_TREND = 1.5              # 顺势马丁倍率
MART_COUNTER = 1.2            # 逆势马丁倍率
RE_CENTER_US = 1800000000    # 重新铺网周期：30分钟 (大幅降价低噪音，让马丁抄底更彻底)
DATA_DIR = 'data_1s'

# 🏦 交易所真实手续费率
FEE_RATE_MAKER = 0.0           # 对应截图 $0.0 费率
FEE_RATE_TAKER = 0.0           # 对应截图 $0.0 费率

# 🚀 橡胶防御网格 (Rubber Grid) 独有参数
RUBBER_THRESHOLD_PCT = 3.0   
RUBBER_MULTIPLIER = 10       
LOOKBACK_US = 3600000000     
SILENCE_DURATION_US = 3600000000 # 硬止损后沉默1小时
MA_WINDOW_TICKS = 7200       # 2小时均线周期 (7200秒)
MAINTENANCE_MARGIN_RATE = 0.005 # 维持保证金率 0.5% (交易所标准线)
MMR = MAINTENANCE_MARGIN_RATE
HARD_SL_PCT = 0.2             # 硬止损比例 (20%)

class GridBot:
    def __init__(self):
        self.cash = INITIAL_CASH
        self.rpnl = 0.0
        self.total_fees = 0.0
        self.longs = []
        self.shorts = []
        self.pb = []
        self.ps = []
        self.last = -1e18
        self.trades = 0
        self.hist = []
        self.max_l = 0
        self.max_s = 0
        self.first_price = None
        
        self.min_long_tp = float('inf')
        self.max_short_tp = 0
        
        self.watermark = INITIAL_CASH
        self.clear_count = 0  # 盘活次数
        self.sl_count = 0     # 止损次数
        self.last_grid_equity = INITIAL_CASH # v29: 记录本轮网格启动时的权益
        
        self.cur_hr_start = -1e18
        self.cur_hr_max = 0
        self.prev_hr_max = 0
        self.rubber_active = False
        self.rubber_count = 0
        self.silence_until = -1e18 # 触发硬止损后的冷冻静默期时间戳
        
        # v11 单向之眼均线追踪
        self.prices_q = collections.deque(maxlen=MA_WINDOW_TICKS)
        self.prices_sum = 0.0
        self.trend_ma = 0.0
        self.trade_count = 0
        self.center_p = 0.0          # 当前活跃网格的中心价格

    def available_balance(self):
        """
        在动态杠杆下，冻结保证金需基于各订单的自身杠杆分开计算
        """
        basis = self.cash + self.rpnl
        held_long_margin = sum(p['q'] * p['e'] / p.get('lev', 10.0) for p in self.longs)
        held_short_margin = sum(p['q'] * p['e'] / p.get('lev', 10.0) for p in self.shorts)
        pending_buy_margin = sum(o['n'] / o.get('lev', 10.0) for o in self.pb)
        pending_sell_margin = sum(o['n'] / o.get('lev', 10.0) for o in self.ps)
        
        frozen = held_long_margin + held_short_margin + pending_buy_margin + pending_sell_margin
        return basis - frozen

    def equity(self, cl):
        basis = self.cash + self.rpnl
        ul = sum(p['q'] * (cl - p['e']) for p in self.longs)
        us = sum(p['q'] * (p['e'] - cl) for p in self.shorts)
        return basis + ul + us

    def audit_trail(self, cl):
        """提供极度详尽的资产与持仓审计"""
        eq = self.equity(cl)
        l_notional = sum(p['q'] * cl for p in self.longs)
        s_notional = sum(p['q'] * cl for p in self.shorts)
        total_notional = l_notional + s_notional
        mm = total_notional * MMR
        
        # 估算强平价格 (简化版全仓强平逻辑)
        liq_l = 0
        if l_notional > s_notional:
            # 多头主导，计算跌到哪里会爆
            # (eq - mm) 是还能亏损的空间
            liq_l = cl * (1 - (eq - mm) / (l_notional - s_notional)) if (l_notional - s_notional) > 0 else 0

        print(f"\n  🔍 [资产审计 @{cl}]")
        print(f"     权益: ${round(eq,2)} | 现金: ${round(self.cash+self.rpnl,2)} | 浮盈: ${round(eq-(self.cash+self.rpnl),2)}")
        print(f"     持仓: 多 ${round(l_notional,1)} ({len(self.longs)}单) | 空 ${round(s_notional,1)} ({len(self.shorts)}单)")
        print(f"     风险: 维持保证金: ${round(mm,2)} | 估算多单强平价: {round(liq_l,1) if liq_l >0 else '安全'}")
        print(f"     挂单: 多 {len(self.pb)}层 | 空 {len(self.ps)}层 | 可用保证金: ${round(self.available_balance(),2)}")


    def reset(self, cl):
        self.pb = []
        self.ps = []
        self.min_long_tp = float('inf')
        self.max_short_tp = 0
        self.center_p = cl
        avail = self.available_balance()
        usable_margin = avail * CAPITAL_UTILIZATION
        if usable_margin < 10.0:
            print("  ⚠️ [资金不足] 可用保证金不足 10U，无法铺设新网格")
            return

        
        if self.trend_ma == 0.0 or cl >= self.trend_ma:
            l_trend_lev, s_trend_lev = LEV_HIGH, LEV_LOW
            l_mart, s_mart = MART_TREND, MART_COUNTER # 多顺空逆
        else:
            l_trend_lev, s_trend_lev = LEV_LOW, LEV_HIGH
            l_mart, s_mart = MART_COUNTER, MART_TREND # 多逆空顺
            
        def calc_denom(trend_lev, mart_val):
            return sum((mart_val ** (i - 1)) / (LEV_CENTER if i == 1 else trend_lev) for i in range(1, LEVELS_PER_SIDE + 1))

        def calc_denom(trend_lev, mart_val):
            return sum((mart_val ** (i - 1)) / (LEV_CENTER if i == 1 else trend_lev) for i in range(1, LEVELS_PER_SIDE + 1))

        # v31: 采用全局基准，确保多空第一层金额相等
        total_denom = calc_denom(l_trend_lev, l_mart) + calc_denom(s_trend_lev, s_mart)
        global_base_notional = usable_margin / total_denom
        
        long_base_notional = global_base_notional
        short_base_notional = global_base_notional
        
        if getattr(self, 'debug_printed', 0) < 1:
            print(f"\n  📊 【非对称马丁审计 (顺势:{l_mart}x | 逆势:{s_mart}x)】")
            print(f"     📊 【起步对齐】多空第一层下单: ${round(global_base_notional, 1)}")
            print(f"     [网格深度] 第10层将达到中心偏离约 5.5%")
            print(f"     多单权重: {round(calc_denom(l_trend_lev, l_mart), 1)} | 空单权重: {round(calc_denom(s_trend_lev, s_mart), 1)}")
            print(f"     [多单] 系数:{l_mart}x | [空单] 系数:{s_mart}x")
        
        
        # v35: 非对称间距分配
        if cl >= self.trend_ma:
            l_gap_base, s_gap_base = GAP_TREND, GAP_COUNTER
        else:
            l_gap_base, s_gap_base = GAP_COUNTER, GAP_TREND

        l_u_gap = l_gap_base * RUBBER_MULTIPLIER if self.rubber_active else l_gap_base
        s_u_gap = s_gap_base * RUBBER_MULTIPLIER if self.rubber_active else s_gap_base
        
        # v20：非对称顺势止盈感应
        if cl >= self.trend_ma: # 多头趋势
            l_tp_ratio = 1 + (TREND_TP_PCT / 100)
            s_tp_ratio = 1 + (COUNTER_TP_PCT / 100)
        else: # 空头趋势
            l_tp_ratio = 1 + (COUNTER_TP_PCT / 100)
            s_tp_ratio = 1 + (TREND_TP_PCT / 100)

        # v35：【非对称间距】计算 - 买单
        curr_p = cl
        for i in range(1, LEVELS_PER_SIDE + 1):
            cur_lev = LEV_CENTER if i == 1 else l_trend_lev
            qty_notional = long_base_notional * (l_mart ** (i - 1))
            if qty_notional < 1.0: continue
            
            step_gap = (l_u_gap * i) / 100
            px = curr_p / (1 + step_gap)
            curr_p = px 
            
            self.pb.append({'p': px, 'q': qty_notional/px, 'n': qty_notional, 'tp': px * l_tp_ratio, 'lev': cur_lev})
            
            if getattr(self, 'debug_printed', 0) < 1:
                cum_dist = abs(1 - px/cl) * 100
                print(f"  [多单层{i:2d}] 价:{round(px,1):8} | 间距:{round(l_u_gap*i,2)}% | 累距:{cum_dist:.2f}% | 份:${round(qty_notional,1)}")

        # v35：【非对称间距】计算 - 卖单
        curr_p = cl
        for i in range(1, LEVELS_PER_SIDE + 1):
            cur_lev = LEV_CENTER if i == 1 else s_trend_lev
            qty_notional = short_base_notional * (s_mart ** (i - 1))
            if qty_notional < 1.0: continue
            
            step_gap = (s_u_gap * i) / 100
            px = curr_p * (1 + step_gap)
            curr_p = px
            
            self.ps.append({'p': px, 'q': qty_notional/px, 'n': qty_notional, 'tp': px / s_tp_ratio, 'lev': cur_lev})
            
            if getattr(self, 'debug_printed', 0) < 1:
                cum_dist = abs(px/cl - 1) * 100
                print(f"  [空单层{i:2d}] 价:{round(px,1):8} | 间距:{round(s_u_gap*i,2)}% | 累距:{cum_dist:.2f}% | 份:${round(qty_notional,1)}")
        
        if getattr(self, 'debug_printed', 0) < 1:
            self.debug_printed = 1

    def _refill_side(self, cl, side):
        """v22/v23 核心核心：单向补全挂单而不偏移中枢"""
        usable_margin = self.available_balance() * CAPITAL_UTILIZATION
        if usable_margin < 10.0: return # 资金枯竭，不再尝试补齐
        
        # v36: 十倍火力非对称补齐
        if self.trend_ma == 0.0 or cl >= self.trend_ma:
            l_trend_lev, s_trend_lev = LEV_HIGH, LEV_LOW
            l_mart, s_mart = MART_TREND, MART_COUNTER
            l_gap_base, s_gap_base = GAP_TREND, GAP_COUNTER
            l_tp_ratio, s_tp_ratio = (1+TREND_TP_PCT/100), (1+COUNTER_TP_PCT/100)
        else:
            l_trend_lev, s_trend_lev = LEV_LOW, LEV_HIGH
            l_mart, s_mart = MART_COUNTER, MART_TREND
            l_gap_base, s_gap_base = GAP_COUNTER, GAP_TREND
            l_tp_ratio, s_tp_ratio = (1+COUNTER_TP_PCT/100), (1+TREND_TP_PCT/100)
            
        l_u_gap = l_gap_base * RUBBER_MULTIPLIER if self.rubber_active else l_gap_base
        s_u_gap = s_gap_base * RUBBER_MULTIPLIER if self.rubber_active else s_gap_base

        def calc_denom(trend_lev, mart_val):
            return sum((mart_val ** (i - 1)) / (LEV_CENTER if i == 1 else trend_lev) for i in range(1, LEVELS_PER_SIDE + 1))

        if side == 'long':
            base_notional = (usable_margin / 2.0) / calc_denom(l_trend_lev, l_mart)
            curr_p = self.center_p
            for i in range(1, LEVELS_PER_SIDE + 1):
                px = curr_p / (1 + (l_u_gap * i) / 100)
                curr_p = px
                if any(abs(px - p['e'])/p['e'] < 0.0005 for p in self.longs): continue
                
                cur_lev = LEV_CENTER if i == 1 else l_trend_lev
                qty_notional = base_notional * (l_mart ** (i - 1))
                if qty_notional < 1.0: continue
                self.pb.append({'p': px, 'q': qty_notional/px, 'n': qty_notional, 'tp': px * l_tp_ratio, 'lev': cur_lev})
        else:
            base_notional = (usable_margin / 2.0) / calc_denom(s_trend_lev, s_mart)
            curr_p = self.center_p
            for i in range(1, LEVELS_PER_SIDE + 1):
                px = curr_p * (1 + (s_u_gap * i) / 100)
                curr_p = px
                if any(abs(px - p['e'])/p['e'] < 0.0005 for p in self.shorts): continue
                
                cur_lev = LEV_CENTER if i == 1 else s_trend_lev
                qty_notional = base_notional * (s_mart ** (i - 1))
                if qty_notional < 1.0: continue
                self.ps.append({'p': px, 'q': qty_notional/px, 'n': qty_notional, 'tp': px / s_tp_ratio, 'lev': cur_lev})

    def tick(self, ts, cl, hi, lo):
        if self.first_price is None:
            self.first_price = cl
            dt_str = datetime.fromtimestamp(ts/1e6).strftime('%Y-%m-%d %H:%M')
            print(f"\n  [开始回测] 起始时间: {dt_str} | 起始价格: {cl}")

        # v12 更新 2小时均线
        if len(self.prices_q) == MA_WINDOW_TICKS:
            self.prices_sum -= self.prices_q.popleft()
        self.prices_q.append(cl)
        self.prices_sum += cl
        self.trend_ma = self.prices_sum / len(self.prices_q)

        if ts - self.cur_hr_start >= LOOKBACK_US:
            self.prev_hr_max = self.cur_hr_max
            self.cur_hr_max = hi
            self.cur_hr_start = ts
        elif hi > self.cur_hr_max:
            self.cur_hr_max = hi
            
        recent_high = max(self.cur_hr_max, self.prev_hr_max)
        drop_pct = (recent_high - cl) / recent_high * 100 if recent_high > 0 else 0
        self.rubber_active = drop_pct >= RUBBER_THRESHOLD_PCT

        # 2. 初始开局判断
        if self.center_p == 0 and ts >= getattr(self, 'silence_until', -1e18):
            self.reset(cl)
            self.last = ts
            
        if self.pb and lo <= self.pb[0]['p']:  
            new_pb = []
            for o in self.pb:
                if lo <= o['p']:
                    tp = o['tp']
                    self.longs.append({'e': o['p'], 'q': o['q'], 'tp': tp, 'lev': o.get('lev', 10.0)})
                    # 扣除入场Maker手续费
                    fee = o['q'] * o['p'] * FEE_RATE_MAKER
                    self.rpnl -= fee
                    self.total_fees += fee
                    
                    if self.trade_count < 50:
                        print(f"  [成交开仓] 多单成交 | 价格:{round(o['p'],2)} | 数量:{round(o['q'],4)} | 下单价值:${round(o['n'],2)}")
                    
                    if tp < self.min_long_tp:
                        self.min_long_tp = tp
                else:
                    new_pb.append(o)
            self.pb = new_pb

        if self.ps and hi >= self.ps[0]['p']:  
            new_ps = []
            for o in self.ps:
                if hi >= o['p']:
                    tp = o['tp']
                    self.shorts.append({'e': o['p'], 'q': o['q'], 'tp': tp, 'lev': o.get('lev', 10.0)})
                    # 扣除入场Maker手续费
                    fee = o['q'] * o['p'] * FEE_RATE_MAKER
                    self.rpnl -= fee
                    self.total_fees += fee
                    
                    if self.trade_count < 50:
                        print(f"  [成交开仓] 空单成交 | 价格:{round(o['p'],2)} | 数量:{round(o['q'],4)} | 下单价值:${round(o['n'],2)}")
                        
                    if tp > self.max_short_tp:
                        self.max_short_tp = tp
                else:
                    new_ps.append(o)
            self.ps = new_ps

        if hi >= self.min_long_tp:
            new_longs = []
            self.min_long_tp = float('inf')
            for p in self.longs:
                if hi >= p['tp']:
                    gross_pnl = p['q'] * (p['tp'] - p['e'])
                    fee = p['q'] * p['tp'] * FEE_RATE_MAKER
                    self.rpnl += gross_pnl - fee
                    self.total_fees += fee
                    self.trades += 1
                    self.trade_count = getattr(self, 'trade_count', 0) + 1
                    
                    if self.trade_count <= 50:
                        print(f"  [止盈平仓] 多单止盈 | 卖出价:{round(p['tp'],2)} | 成本价:{round(p['e'],2)} | 净利:${round(gross_pnl-fee,2)} | 净值:${round(self.equity(cl),2)}")
                else:
                    new_longs.append(p)
                    if p['tp'] < self.min_long_tp:
                        self.min_long_tp = p['tp']
            self.longs = new_longs

        if lo <= self.max_short_tp:
            new_shorts = []
            self.max_short_tp = 0
            for p in self.shorts:
                if lo <= p['tp']:
                    gross_pnl = p['q'] * (p['e'] - p['tp'])
                    fee = p['q'] * p['tp'] * FEE_RATE_MAKER
                    self.rpnl += gross_pnl - fee
                    self.total_fees += fee
                    self.trades += 1
                    self.trade_count = getattr(self, 'trade_count', 0) + 1
                    
                    if self.trade_count <= 50:
                        print(f"  [止盈平仓] 空单止盈 | 买入价:{round(p['tp'],2)} | 成本价:{round(p['e'],2)} | 净利:${round(gross_pnl-fee,2)} | 净值:${round(self.equity(cl),2)}")
                else:
                    new_shorts.append(p)
                    if p['tp'] > self.max_short_tp:
                        self.max_short_tp = p['tp']
            self.shorts = new_shorts

        nl = len(self.longs)
        ns = len(self.shorts)
        if nl > self.max_l: self.max_l = nl
        if ns > self.max_s: self.max_s = ns

        eq = self.equity(cl)
        
        # 1. 爆仓判定 (全仓爆仓逻辑：权益 < 维持保证金)
        l_val = sum(p['q'] * cl for p in self.longs)
        s_val = sum(p['q'] * cl for p in self.shorts)
        if eq < (l_val + s_val) * MMR:
            print(f"  💣 [强制强平] 净值不足以支撑维持保证金! 正在清算...")
            self.audit_trail(cl)
            return False, 0.0 # 爆仓归零

        # 2. 硬止损检查 (基于本轮启动本金的 20% 绝对跌幅)
        if eq <= self.last_grid_equity * (1 - HARD_SL_PCT):
            print(f"\n  🚨 [硬止损触发 (20%)] | 强平损益:${round(eq - self.last_grid_equity, 2)} | 剩余权益:${round(eq,2)}")
            self.audit_trail(cl)
            # v29: 割肉平仓，保留剩余现金
            self.cash = eq
            self.longs, self.shorts = [], []
            self.pb, self.ps = [], []
            self.min_long_tp, self.max_short_tp = float('inf'), 0
            self.center_p = 0
            self.last_grid_equity = eq
            self.sl_count += 1
            self.silence_until = ts + SILENCE_DURATION_US
            self.last = ts 
            return True, eq

        # 3. 胜利盘活 (基于本轮本金盈利 10%)
        if eq >= self.last_grid_equity * 1.10:
            print(f"\n  💰 [全仓盘活] 盈利达到10%! | 变现:${round(eq - self.last_grid_equity, 2)} | 当前权益:${round(eq,2)}")
            self.audit_trail(cl)
            # v29 修正：利润必须彻底落袋，变为下一轮的滚雪球本金
            self.cash = eq 
            self.longs, self.shorts = [], []
            self.pb, self.ps = [], []
            self.min_long_tp, self.max_short_tp = float('inf'), 0
            self.center_p = 0
            self.last_grid_equity = eq
            self.clear_count += 1
            self.last = ts
            return True, eq

        # v22/v23：【双向无限补给逻辑 - 移至末尾防止死循环】
        if self.center_p > 0 and ts >= getattr(self, 'silence_until', -1e18):
            if not self.pb: self._refill_side(cl, 'long')
            if not self.ps: self._refill_side(cl, 'short')

        self.hist.append(eq)
        return True, eq


def main():
    zips = sorted([f for f in os.listdir(DATA_DIR) if f.endswith('.zip')])
    bot = GridBot()

    print("=" * 70)
    print("  🚀 v31: 马丁合一版 (起步对齐 / 时间可视化 / 价格累距)")
    print("=" * 70)
    print(f"  初始本金:   {INITIAL_CASH} U | 中心杠杆: {LEV_CENTER}x | 趋势倍率: {LEV_HIGH}x/{LEV_LOW}x")
    print(f"  单向层数:   {LEVELS_PER_SIDE} 层 | 马丁倍率: 顺{MART_TREND} / 逆{MART_COUNTER}")
    print(f"  止损比例:   本轮权益跌幅 {HARD_SL_PCT*100}% | 止盈 0.8%(顺)/0.3%(逆)")
    print("=" * 70)

    last_price = 0
    for i, zf in enumerate(zips):
        with zipfile.ZipFile(os.path.join(DATA_DIR, zf)) as z:
            fn = z.namelist()[0]
            with z.open(fn) as f:
                for row in csv.reader(io.TextIOWrapper(f)):
                    try:
                        ts = int(row[0])
                        cl = float(row[2])
                        hi = float(row[3])
                        lo = float(row[4])
                    except:
                        continue
                    alive, eq = bot.tick(ts, cl, hi, lo)
                    last_price = cl
                    if not alive:
                        print(f"  ❌ 账户爆仓于 {zf} (净值归零)。")
                        return

        if (i + 1) % 10 == 0:
            eq = bot.hist[-1] if bot.hist else bot.cash
            bah = INITIAL_CASH * (last_price / bot.first_price)
            avail = bot.available_balance()
            
            grid_roi = (eq/INITIAL_CASH - 1) * 100
            bah_roi = (bah/INITIAL_CASH - 1) * 100
            print(f"第 {i+1} 天: 净值=${round(eq,1)} ({round(grid_roi,1)}%) | 死拿=${round(bah,1)} ({round(bah_roi,1)}%)")
            print(f"         > 多仓={len(bot.longs)} / 空仓={len(bot.shorts)} | 盘活={bot.clear_count}次 | 止损={bot.sl_count}次")
            print(f"         > 可用保证金=${round(avail,0)}\n")

    eq = bot.hist[-1] if bot.hist else bot.cash
    bah = INITIAL_CASH * (last_price / bot.first_price)
    avail = bot.available_balance()
    grid_roi = (eq/INITIAL_CASH - 1) * 100
    bah_roi = (bah/INITIAL_CASH - 1) * 100
    
    print("=" * 70)
    print("  🏆 v19 最终战绩 (历经90天)")
    print("=" * 70)
    print(f"  BTC走势:      ${round(bot.first_price,2)} -> ${round(last_price,2)} (跌幅 {round((last_price/bot.first_price-1)*100,2)}%)")
    print("-" * 70)
    print(f"  📈 【v33 实战回归版 最终战绩】")
    print(f"  总权益:       ${round(eq,2)}")
    print(f"  总收益率 ROI: {round(grid_roi,2)}%")
    print(f"  累计被扣除的手续费: ${round(bot.total_fees,2)} (磨损极其巨大)")
    print(f"  累计止盈笔数: {bot.trades}次")
    print(f"  大赚盘活清仓: {bot.clear_count} 次 (赚10%切仓)")
    print(f"  触发断腕止损: {bot.sl_count} 次 (亏20%割肉)")
    print("-" * 70)
    
    diff = grid_roi - bah_roi
    if diff > 0:
        print(f"  🔥 网格 跑赢 现货无脑持有 【{round(diff,2)}%】！")
    else:
        print(f"  ❄️ 网格 跑输现货持仓 【{round(abs(diff),2)}%】。")
    print("=" * 70)

if __name__ == "__main__":
    main()
