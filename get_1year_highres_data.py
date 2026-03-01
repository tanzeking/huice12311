import urllib.request
import json
import os
import datetime
import zipfile
import csv
import concurrent.futures

# ⚙️ 配置区
SYMBOL = "BTCUSDT"
DAYS_TO_DOWNLOAD = 365  # 下载 1 年数据
AGGREGATE_SECONDS = 10  # 💡 既然要做超高频，我们合成为 10s (比 1m 精度高 6 倍，且不卡顿)
DATA_DIR = "data_raw_1s"
OUTPUT_FILE = "data/btc_10s_1year.json"

def process_day(date_str):
    zip_name = f"{SYMBOL}-1s-{date_str}.zip"
    csv_name = f"{SYMBOL}-1s-{date_str}.csv"
    url = f"https://data.binance.vision/data/spot/daily/klines/{SYMBOL}/1s/{zip_name}"
    zip_path = os.path.join(DATA_DIR, zip_name)
    done_mark = os.path.join(DATA_DIR, f"done_{date_str}.txt")
    
    if os.path.exists(done_mark):
        return []

    try:
        if not os.path.exists(zip_path):
            urllib.request.urlretrieve(url, zip_path)
        
        aggregated_data = []
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(DATA_DIR)
        
        csv_path = os.path.join(DATA_DIR, csv_name)
        with open(csv_path, 'r') as f:
            reader = csv.reader(f)
            buffer = []
            for row in reader:
                buffer.append(row)
                if len(buffer) == AGGREGATE_SECONDS:
                    ts = int(buffer[0][0])
                    if ts > 10**13: ts = ts // 1000 
                    o = float(buffer[0][1])
                    h = max([float(r[2]) for r in buffer])
                    l = min([float(r[3]) for r in buffer])
                    cl = float(buffer[-1][4])
                    v = sum([float(r[5]) for r in buffer])
                    aggregated_data.append([ts, o, cl, h, l, v])
                    buffer = []
        
        if os.path.exists(csv_path): os.remove(csv_path)
        if os.path.exists(zip_path): os.remove(zip_path) # 删除原始压缩包省空间
        
        with open(done_mark, 'w') as f: f.write("done")
        return aggregated_data
    except Exception:
        return []

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)
    
    today = datetime.datetime.now()
    dates = [(today - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, DAYS_TO_DOWNLOAD + 1)]
    
    all_data = []
    
    print(f"📡 启动 1年 (365天) 超高频数据下载任务...")
    print(f"⚙️ 模式: 1s 原始数据 -> 自动合成 {AGGREGATE_SECONDS}s K线")
    print(f"📦 预计生成 K线数: {365 * 86400 / AGGREGATE_SECONDS:,.0f} 根")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_date = {executor.submit(process_day, date): date for date in dates}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_date)):
            res = future.result()
            if res:
                all_data.extend(res)
            if (i+1) % 10 == 0:
                print(f"  ✅ 已处理 {i+1}/365 天...")

    # 排序并保存
    print("⏳ 正在进行最后的数据排序和打包...")
    all_data.sort(key=lambda x: x[0])
    
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(all_data, f)
    
    print(f"🎉 任务完成！")
    print(f"📂 最终回测文件: {OUTPUT_FILE}")
    print(f"📊 总数据点: {len(all_data):,}")

if __name__ == "__main__":
    main()
