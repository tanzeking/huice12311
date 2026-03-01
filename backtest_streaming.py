# -*- coding: utf-8 -*-
"""
Streaming Backtest Engine - High Precision (10s bars)
"""
import os
import csv
import json
import statistics

# Configuration
INITIAL_CASH = 10.0
LEVERAGE = 30
GRID_LEVELS = 6
CAPITAL_UTILIZATION = 0.9
AI_UPDATE_INTERVAL_MIN = 50
AI_VOLATILITY_MULT = 0.35
MIN_SPACING_PCT = 0.05
MAX_SPACING_PCT = 0.80
PROTECTION_ENABLED = True
STOP_LOSS_PCT = 1.5  # Updated to 1.5% as requested
SPIKE_COOLDOWN_MIN = 15
VOL_SURGE_THRESHOLD = 3.0
SURGE_SPACING_MULT = 2.0
CSV_DIR = "data_processed_10s"

class StreamingGridBacktester:
    def __init__(self, cash, lev, levels, util):
        self.initial_cash = cash
        self.lev = lev
        self.base_levels = levels
        self.levels = levels
        self.util = util
        self.total_profit = 0.0
        self.total_trades = 0
        self.max_floating_loss = 0.0
        self.pnl_history = []
        self.active_tps = []
        self.pending_entries = []
        self.cooldown_until = 0
        self.fill_history = []
        
    def get_order_notional(self):
        total_buying_power = (self.initial_cash + self.total_profit) * self.lev * self.util
        return total_buying_power / (self.levels * 2)

    def reset_grid(self, current_price, spacing):
        self.pending_entries = []
        notional = self.get_order_notional()
        mult = spacing / 100
        for i in range(1, self.levels + 1):
            bp = current_price * (1 - i * mult)
            tp = current_price * (1 + i * mult)
            self.pending_entries.append({'side': 'buy', 'price': bp, 'qty': notional/bp})
            self.pending_entries.append({'side': 'sell', 'price': tp, 'qty': notional/tp})

    def process_candle(self, ts, o, cl, hi, lo, last_ai_time, current_spacing, lookback_data):
        if (ts - last_ai_time) >= (AI_UPDATE_INTERVAL_MIN * 60 * 1000):
            equity_now = self.initial_cash + self.total_profit
            self.levels = 15 if equity_now >= 300 else (10 if equity_now >= 100 else self.base_levels)
            if lookback_data:
                # lookback_data contains [cl, hi, lo] -> index 0, 1, 2
                avg_amp = statistics.mean([(x[1]-x[2])/x[0]*100 for x in lookback_data if x[0] > 0])
                new_spacing = max(MIN_SPACING_PCT, min(MAX_SPACING_PCT, avg_amp * AI_VOLATILITY_MULT))
            else:
                new_spacing = 0.12
            if PROTECTION_ENABLED and lookback_data:
                avg_amp = statistics.mean([(x[1]-x[2])/x[0]*100 for x in lookback_data if x[0] > 0])
                if (hi - lo) / cl * 100 > avg_amp * VOL_SURGE_THRESHOLD:
                    new_spacing *= SURGE_SPACING_MULT
            if ts >= self.cooldown_until:
                self.reset_grid(cl, new_spacing)
            current_spacing, last_ai_time = new_spacing, ts
        for entry in self.pending_entries[:]:
            if (entry['side'] == 'buy' and lo <= entry['price']) or (entry['side'] == 'sell' and hi >= entry['price']):
                side, px, qty = entry['side'], entry['price'], entry['qty']
                tp_px = px * (1 + current_spacing/100) if side == 'buy' else px * (1 - current_spacing/100)
                self.active_tps.append({'side': 'sell' if side == 'buy' else 'buy', 'entry_px': px, 'tp_px': tp_px, 'qty': qty})
                if entry in self.pending_entries: self.pending_entries.remove(entry)
                if PROTECTION_ENABLED:
                    self.fill_history.append(ts)
                    self.fill_history = [t for t in self.fill_history if ts - t <= 5 * 60 * 1000]
                    if len(self.fill_history) >= 3:
                        self.cooldown_until = ts + SPIKE_COOLDOWN_MIN * 60 * 1000
                        self.pending_entries = []
                        break
        for tp in self.active_tps[:]:
            is_tp = (tp['side'] == 'buy' and lo <= tp['tp_px']) or (tp['side'] == 'sell' and hi >= tp['tp_px'])
            pnl_pct = (cl - tp['entry_px']) / tp['entry_px'] * 100 if tp['side'] == 'sell' else (tp['entry_px'] - cl) / tp['entry_px'] * 100
            if is_tp:
                self.total_profit += tp['qty'] * abs(tp['tp_px'] - tp['entry_px'])
                self.total_trades += 1
                self.active_tps.remove(tp)
            elif pnl_pct <= -STOP_LOSS_PCT:
                self.total_profit -= tp['qty'] * (tp['entry_px'] * (STOP_LOSS_PCT/100))
                self.active_tps.remove(tp)
        fpnl = sum([tp['qty']*(cl-tp['entry_px']) if tp['side']=='sell' else tp['qty']*(tp['entry_px']-cl) for tp in self.active_tps])
        self.max_floating_loss = min(self.max_floating_loss, fpnl)
        total_equity = self.initial_cash + self.total_profit + fpnl
        if total_equity <= 0: return False, 0, 0, 0
        self.pnl_history.append(total_equity)
        return True, last_ai_time, current_spacing, total_equity

def run():
    if not os.path.exists(CSV_DIR):
        print("Data directory not found.")
        return
    files = sorted([f for f in os.listdir(CSV_DIR) if f.endswith(".csv")])
    if not files:
        print("No CSV files found.")
        return
    engine, last_ai, spacing, lookback = StreamingGridBacktester(INITIAL_CASH, LEVERAGE, GRID_LEVELS, CAPITAL_UTILIZATION), -99999999, 0.12, []
    print(f"Starting test with {len(files)} days of 10s data...")
    for day_file in files:
        with open(os.path.join(CSV_DIR, day_file), 'r') as f:
            for row in csv.reader(f):
                ts, o, cl, hi, lo, v = int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
                ok, last_ai, spacing, eq = engine.process_candle(ts, o, cl, hi, lo, last_ai, spacing, lookback)
                if not ok:
                    print(f"Crashed on {day_file} (Liquidation)")
                    return
                lookback.append([cl, hi, lo])
                if len(lookback) > 360: lookback.pop(0)
    print("\n" + "="*50)
    print(f"REPORT: 1.5% SL, 30x LEV, {len(files)} Days")
    print("="*50)
    if engine.pnl_history:
        print(f"Final Equity: ${engine.pnl_history[-1]:.2f}")
        print(f"Profit: ${engine.total_profit:.2f}")
        print(f"ROI: {((engine.pnl_history[-1]-INITIAL_CASH)/INITIAL_CASH)*100:.2f}%")
        print(f"Max Floating Loss: ${engine.max_floating_loss:.2f}")
        print(f"Total Success Trades: {engine.total_trades}")
    print("="*50)

if __name__ == "__main__":
    run()
