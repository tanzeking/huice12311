import urllib.request
import json
import os
import datetime
import zipfile
import csv

def download_and_aggregate_30s():
    symbol = "BTCUSDT"
    data_dir = "data_high_res"
    os.makedirs(data_dir, exist_ok=True)
    
    # We'll take the last 30 days
    today = datetime.datetime.now()
    all_30s_data = []
    
    print(f"🚀 Starting 30-day 1s -> 30s aggregation for {symbol}...")
    
    for i in range(1, 31):
        target_date = today - datetime.timedelta(days=i)
        date_str = target_date.strftime("%Y-%m-%d")
        zip_name = f"{symbol}-1s-{date_str}.zip"
        csv_name = f"{symbol}-1s-{date_str}.csv"
        url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1s/{zip_name}"
        
        zip_path = os.path.join(data_dir, zip_name)
        
        try:
            if not os.path.exists(zip_path):
                print(f"  Downloading {date_str}...")
                urllib.request.urlretrieve(url, zip_path)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(data_dir)
            
            csv_path = os.path.join(data_dir, csv_name)
            
            # Aggregate 1s into 30s
            with open(csv_path, 'r') as f:
                reader = csv.reader(f)
                temp_bucket = []
                for row in reader:
                    # Binance 1s CSV format: open_time, o, h, l, c, v, close_time, ...
                    # Col 0: ts, 1:o, 2:h, 3:l, 4:c, 5:v
                    temp_bucket.append(row)
                    if len(temp_bucket) == 30:
                        ts = int(temp_bucket[0][0])
                        # Handle Binance timestamps which can be long
                        if ts > 10**13: ts = ts // 1000 # Convert to ms if it was micro/nano
                        
                        o = float(temp_bucket[0][1])
                        h = max([float(r[2]) for r in temp_bucket])
                        l = min([float(r[3]) for r in temp_bucket])
                        cl = float(temp_bucket[-1][4])
                        v = sum([float(r[5]) for r in temp_bucket])
                        
                        # Format: [ts, open, close, high, low, volume]
                        all_30s_data.append([ts, o, cl, h, l, v])
                        temp_bucket = []
            
            os.remove(csv_path) # Clean up CSV to save space
            
        except Exception as e:
            print(f"  ⚠️ Skipping {date_str} (possible data not available yet): {e}")
            continue

    # Sort and save
    all_30s_data.sort(key=lambda x: x[0])
    
    output_path = "data/btc_30s_1month.json"
    os.makedirs("data", exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(all_30s_data, f)
    
    print(f"✅ Finished! Aggregated {len(all_30s_data)} 30-second candles.")
    print(f"📂 Saved to {output_path}")

if __name__ == "__main__":
    download_and_aggregate_30s()
