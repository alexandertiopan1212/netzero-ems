from datetime import datetime

UNIT_MAP = {
    'W': 'Watt',
    'V': 'Volt',
    'A': 'Ampere',
    'kWh': 'kWh',
    '%': '%',
    'Hz': 'Hertz',
    'VA': 'VA'
}

def epoch_to_datetime(ts: int) -> datetime:
    """Convert UNIX epoch (seconds) to datetime"""
    return datetime.fromtimestamp(ts)

def flatten_records(device_data_list: list) -> list:
    """
    Transform JSON['deviceDataList'] into list of tuples ready for DB insertion.
    """
    records = []
    for dev in device_data_list:
        sn = dev['deviceSn']
        ts = epoch_to_datetime(dev['collectionTime'])
        for d in dev['dataList']:
            key = d.get('key') or 'Unknown'
            try:
                val = float(d.get('value', 0))
            except:
                val = 0.0
            unit = d.get('unit','')
            records.append((sn, ts, key, val, unit))
    return records