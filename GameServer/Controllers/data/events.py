import datetime


def is_weekend_event_active(now: datetime.datetime = None):
    """Return whether the weekend experience event is active."""
    today = now or datetime.datetime.now()
    return today.weekday() >= 5 or (today.month == 12 and today.day == 8)


def is_christmas_event_active(now: datetime.datetime = None):
    """Return whether the Christmas event is active."""
    today = now or datetime.datetime.now()
    return today.month == 12 and 1 <= today.day <= 7
