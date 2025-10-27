"""
Timezone Helper - Centralized EST/EDT Timezone Handling

All timestamps in the system should be displayed in US Eastern Time.
This module provides helper functions for consistent timezone handling.
"""

import pytz
from datetime import datetime, date
from typing import Optional, Union

# US Eastern timezone (automatically handles EST/EDT)
EASTERN = pytz.timezone('US/Eastern')
UTC = pytz.UTC


def now_eastern() -> datetime:
    """
    Get current time in Eastern timezone

    Returns:
        datetime: Current time in US/Eastern (EST or EDT depending on DST)
    """
    return datetime.now(EASTERN)


def to_eastern(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Convert a datetime to Eastern timezone

    Args:
        dt: Datetime object (naive or timezone-aware)

    Returns:
        datetime: Datetime converted to US/Eastern, or None if input is None
    """
    if dt is None:
        return None

    # If naive datetime, assume it's UTC
    if dt.tzinfo is None:
        dt = UTC.localize(dt)

    # Convert to Eastern
    return dt.astimezone(EASTERN)


def format_eastern(dt: Optional[datetime], format_str: str = "%Y-%m-%d %I:%M %p EST") -> str:
    """
    Format a datetime in Eastern timezone

    Args:
        dt: Datetime object
        format_str: strftime format string (default: "2025-10-20 03:45 PM EST")

    Returns:
        str: Formatted datetime string, or "N/A" if input is None
    """
    if dt is None:
        return "N/A"

    eastern_dt = to_eastern(dt)

    # Determine if currently EST or EDT
    if eastern_dt.dst():
        # Daylight saving time active (EDT)
        return eastern_dt.strftime(format_str).replace('EST', 'EDT')
    else:
        # Standard time (EST)
        return eastern_dt.strftime(format_str)


def format_relative_time(dt: Optional[datetime]) -> str:
    """
    Format time relative to now (e.g., "5 minutes ago", "2 hours ago")

    Args:
        dt: Datetime object

    Returns:
        str: Relative time string
    """
    if dt is None:
        return "N/A"

    eastern_dt = to_eastern(dt)
    now = now_eastern()

    diff = now - eastern_dt
    seconds = diff.total_seconds()

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        return format_eastern(dt, "%b %d, %Y")


def format_news_timestamp(dt: Optional[datetime]) -> str:
    """
    Format timestamp for news feed display
    Shows relative time if recent, otherwise shows date

    Args:
        dt: Datetime object

    Returns:
        str: Formatted timestamp for news display
    """
    if dt is None:
        return "N/A"

    eastern_dt = to_eastern(dt)
    now = now_eastern()

    diff = now - eastern_dt
    hours_ago = diff.total_seconds() / 3600

    if hours_ago < 24:
        # Recent: show relative time + exact time
        relative = format_relative_time(dt)
        exact = format_eastern(dt, "%I:%M %p")
        return f"{relative} ({exact})"
    elif hours_ago < 168:  # Within a week
        # This week: show day + time
        return format_eastern(dt, "%a %I:%M %p EST")
    else:
        # Older: show date + time
        return format_eastern(dt, "%b %d %I:%M %p EST")


# Convenience functions for common formats
def format_short_date(dt: Optional[Union[datetime, date]]) -> str:
    """
    Format: Oct 20
    Accepts both datetime and date objects
    """
    if dt is None:
        return "N/A"

    # If it's a date object (not datetime), convert to datetime at noon Eastern
    if isinstance(dt, date) and not isinstance(dt, datetime):
        from datetime import time
        dt = datetime.combine(dt, time(12, 0, 0))
        dt = EASTERN.localize(dt)

    return format_eastern(dt, "%b %d")


def format_long_date(dt: Optional[Union[datetime, date]]) -> str:
    """
    Format: October 20, 2025
    Accepts both datetime and date objects
    """
    if dt is None:
        return "N/A"

    # If it's a date object (not datetime), convert to datetime at noon Eastern
    # (using noon prevents timezone conversion from shifting to previous day)
    if isinstance(dt, date) and not isinstance(dt, datetime):
        from datetime import time
        dt = datetime.combine(dt, time(12, 0, 0))  # Noon
        dt = EASTERN.localize(dt)  # Localize to Eastern timezone

    return format_eastern(dt, "%B %d, %Y")


def format_datetime(dt: Optional[datetime]) -> str:
    """Format: Oct 20, 2025 3:45 PM EST"""
    return format_eastern(dt, "%b %d, %Y %I:%M %p EST")


def format_time_only(dt: Optional[datetime]) -> str:
    """Format: 3:45 PM EST"""
    return format_eastern(dt, "%I:%M %p EST")


# Example usage
if __name__ == "__main__":
    # Test functions
    now = now_eastern()
    print(f"Current time (Eastern): {format_datetime(now)}")
    print(f"Short date: {format_short_date(now)}")
    print(f"Long date: {format_long_date(now)}")
    print(f"Time only: {format_time_only(now)}")
    print(f"News format: {format_news_timestamp(now)}")
    print(f"Relative: {format_relative_time(now)}")
