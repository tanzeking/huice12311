import urllib.request
import json
import os
import datetime
import zipfile
import csv
import concurrent.futures

# ⚙️ 配置区
SYMBOL = "BTCUSDT"
DAYS_TO_DOWNLOAD = 365  
AGGREGATE_SECONDS = 10  
DATA_DIR = "data_raw_1s"
CSV_DIR = "data_processed_10s"

def process_day(date_str):
    zip_name = f"{SYMBOL}-1s-{date_str}.zip"
    csv_name = f"{SYMBOL}-1s-{date_str}.csv"
    output_csv = os.path.join(CSV_DIR, f"{date_str}.csv")
    url = f"https://data.binance.vision/data/spot/daily/klines/{SYMBOL}/1s/{zip_name}"
    zip_path = os.path.join(DATA_DIR, zip_name)
    
    if os.path.exists(output_csv):
        return True

    try:
        if not os.path.exists(zip_path):
            urllib.request.urlretrieve(url, zip_path)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(DATA_DIR)
        
        raw_csv_path = os.path.join(DATA_DIR, csv_name)
        with open(raw_csv_path, 'r') as f_in, open(output_csv, 'w', newline='') as f_out:
            reader = csv.reader(f_in)
            writer = csv.writer(f_out)
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
                    # 保存格式: timestamp, open, close, high, low, volume
                    writer.writerow([ts, o, cl, h, l, v])
                    buffer = []
        
        if os.path.exists(raw_csv_path): os.remove(raw_csv_path)
        if os.path.exists(zip_path): os.remove(zip_path)
        return True
    except Exception:
        return False

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(CSV_DIR, exist_ok=True)
    
    today = datetime.datetime.now()
    dates = [(today - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, DAYS_TO_DOWNLOAD + 1)]
    
    print(f"📡 正在以'流式存储'方式重建 1年 (365天) 10s 数据...")
    print(f"📂 每一天将独立存为一个 CSV，解决内存不足问题。")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_date = {executor.submit(process_day, date): date for date in dates}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_date)):
            res = future.result()
            if (i+1) % 50 == 0:
                print(f"  ✅ 已完成 {i+1}/365 天...")

    print(f"🎉 数据重建完成！所有 10s K线已存入 {CSV_DIR} 文件夹。")

if __name__ == "__main__":
    main()
