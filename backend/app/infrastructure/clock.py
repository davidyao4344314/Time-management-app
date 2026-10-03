"""One application timezone for schedule facts and historical date references."""
from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL_TIMEZONE = ZoneInfo('Pacific/Auckland')


def local_now():
    return datetime.now(LOCAL_TIMEZONE)


def observation_clock():
    now = local_now()
    return {'as_of': now.isoformat(timespec='seconds'), 'date': now.date().isoformat(),
            'time': now.strftime('%H:%M'), 'timezone': str(LOCAL_TIMEZONE)}
