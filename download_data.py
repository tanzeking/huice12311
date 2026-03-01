import urllib.request
import json
import os
import datetime
import time
import ssl

def download_bitfinex_data():
    symbol = "tBTCF0:USTF0"
    timeframe = "1m"
    limit = 10000
    all_data = []
    
    # Target: ~45,000 candles for 1 month
    # We'll fetch in 5 chunks of 10,000
    end_time = None 
    
    # Bypass SSL verification
    context = ssl._create_unverified_context()
    
    print(f"📡 Downloading 1-MONTH of 1-MINUTE data for {symbol}...")
    
    for i in range(5):
        url = f"https://api-pub.bitfinex.com/v2/candles/trade:{timeframe}:{symbol}/hist?limit={limit}&sort=-1"
        if end_time:
            url += f"&end={end_time}"
            
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        req = urllib.request.Request(url, headers=headers)
        
        try:
            with urllib.request.urlopen(req, context=context) as response:
                data = json.loads(response.read().decode())
            
            if not data:
                print(f"  No more data in chunk {i+1}")
                break
                
            all_data.extend(data)
            # The last candle's timestamp minus 1 ms becomes our new end_time
            end_time = data[-1][0] - 1 
            
            last_date = datetime.datetime.fromtimestamp(data[-1][0]/1000).strftime('%Y-%m-%d %H:%M')
            print(f"  Chunk {i+1} done. Reached: {last_date}")
            
            time.sleep(1) # Slow down to avoid rate limits
            
        except Exception as e:
            print(f"❌ Error in chunk {i+1}: {e}")
            break
            
    # Sort back to chronological order (earliest first)
    all_data.reverse()
        
    data_dir = 'data'
    os.makedirs(data_dir, exist_ok=True)
    file_path = os.path.join(data_dir, 'btc_1m_1month.json')
    with open(file_path, 'w') as f:
        json.dump(all_data, f)
        
    print(f"✅ Downloaded {len(all_data)} 1-minute candles.")
    print(f"📂 Saved to {file_path}")
    
    if all_data:
        start_ts = all_data[0][0]
        end_ts = all_data[-1][0]
        days = (end_ts - start_ts) / (1000 * 60 * 60 * 24)
        start_date = datetime.datetime.fromtimestamp(start_ts/1000).strftime('%Y-%m-%d %H:%M')
        end_date = datetime.datetime.fromtimestamp(end_ts/1000).strftime('%Y-%m-%d %H:%M')
        print(f"🕒 Total Time range: {start_date} to {end_date} ({days:.2f} days)")

if __name__ == "__main__":
    download_bitfinex_data()
