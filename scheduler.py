import time
from api_client import fetch_latest
from db import init_db, upsert_device_meta, insert_device_data
from utils import flatten_records, epoch_to_datetime
from datetime import datetime

# Daftar SN device
DEVICE_LIST = ["2303058755", "2210274681"]

# Inisialisasi DB
init_db()

# Interval polling (detik)
INTERVAL = 300  # 5 menit

def job():
    """Fetch data dan simpan ke DB sekali jalan."""
    try:
        result = fetch_latest(DEVICE_LIST)
        if result.get('success'):
            devs = result.get('deviceDataList', [])
            for d in devs:
                sn = d['deviceSn']
                st = d['deviceState']
                updated = epoch_to_datetime(d['collectionTime'])
                upsert_device_meta(sn, d['deviceType'], st, updated)
            records = flatten_records(devs)
            insert_device_data(records)
            print(f"[{datetime.now()}] Fetched and saved {len(records)} records.")
        else:
            print(f"Fetch failed: {result}")
    except Exception as e:
        print(f"Error during fetch: {e}")


def main():
    print(f"Scheduler started: polling every {INTERVAL//60} minutes.")
    try:
        while True:
            job()
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("Scheduler stopped by user.")


if __name__ == "__main__":
    main()