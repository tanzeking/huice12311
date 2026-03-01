import urllib.request
import json
import os
import datetime
import zipfile
import csv
import concurrent.futures

def download_one_day(date_str, symbol, data_dir):
    zip_name = f"{symbol}-1s-{date_str}.zip"
    csv_name = f"{symbol}-1s-{date_str}.csv"
    url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1s/{zip_name}"
    zip_path = os.path.join(data_dir, zip_name)
    
    if os.path.exists(os.path.join(data_dir, f"done_{date_str}.txt")):
        return []

    try:
        if not os.path.exists(zip_path):
            # print(f"  Downloading {date_str}...")
            urllib.request.urlretrieve(url, zip_path)
        
        day_data = []
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(data_dir)
        
        csv_path = os.path.join(data_dir, csv_name)
        with open(csv_path, 'r') as f:
            reader = csv.reader(f)
            for row in reader:
                ts = int(row[0])
                if ts > 10**13: ts = ts // 1000 
                o = float(row[1])
                h = float(row[2])
                l = float(row[3])
                cl = float(row[4])
                v = float(row[5])
                day_data.append([ts, o, cl, h, l, v])
        
        os.remove(csv_path)
        # Mark as done to avoid re-downloading if interrupted
        with open(os.path.join(data_dir, f"done_{date_str}.txt"), 'w') as f:
            f.write("done")
        return day_data
    except Exception as e:
        # print(f"  ⚠️ Skipping {date_str}: {e}")
        return []

def download_90_days():
    symbol = "BTCUSDT"
    data_dir = "data_1s"
    os.makedirs(data_dir, exist_ok=True)
    
    today = datetime.datetime.now()
    dates = [(today - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 91)]
    
    all_1s_data = []
    
    print(f"🚀 Starting 90-day (3 Months) 1s data download for {symbol}...")
    print(f"📡 This involve 90 files and ~7.7 million rows. Please wait...")

    # Use ThreadPool to speed up downloading
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_date = {executor.submit(download_one_day, date, symbol, data_dir): date for date in dates}
        for future in concurrent.futures.as_completed(future_to_date):
            res = future.result()
            if res:
                all_1s_data.extend(res)
                print(f"  ✅ Added {future_to_date[future]} ({len(res)} rows)")

    # Sort and save
    all_1s_data.sort(key=lambda x: x[0])
    
    output_path = "data/btc_1s_3months.json"
    os.makedirs("data", exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(all_1s_data, f)
    
    print(f"🎉 SUCCESS! Total rows: {len(all_1s_data)}")
    print(f"📂 Cached JSON saved to {output_path}")

if __name__ == "__main__":
    download_90_days()
