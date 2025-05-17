from dataclasses import dataclass
from datetime import datetime

@dataclass
class DeviceMeta:
    device_sn: str
    device_type: str
    last_state: int
    last_update: datetime

@dataclass
class DeviceData:
    device_sn: str
    timestamp: datetime
    key: str
    value: float
    unit: str