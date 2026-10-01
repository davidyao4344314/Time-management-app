from urllib.parse import urlsplit

import requests
from icalendar import Calendar


def get_ical_events(feed_url, include_description=False):
    """Download an iCal feed and return its events without saving them."""
    feed_url = feed_url.strip()
    # Subscription links may use webcal instead of https.
    if feed_url.lower().startswith("webcal://"):
        feed_url = "https://" + feed_url[len("webcal://"):]

    try:
        parsed_url = urlsplit(feed_url)
        valid = (
            parsed_url.scheme in {"http", "https"}
            and parsed_url.hostname
            and not any(character.isspace() for character in feed_url)
        )
    except ValueError:
        raise RuntimeError("The iCal subscription URL is invalid.") from None

    if not valid:
        raise RuntimeError("The iCal subscription URL is invalid.")

    try:
        response = requests.get(feed_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        # Request exceptions can contain the private subscription URL.
        raise RuntimeError("Could not download the iCal feed.") from None

    try:
        calendar = Calendar.from_ical(response.content)
        events = []

        for component in calendar.walk("VEVENT"):
            summary = component.get("summary")
            start = component.get("dtstart")
            end = component.get("dtend")
            uid = component.get("uid")

            event = {
                "name": str(summary) if summary else "Untitled event",
                "start": start.dt if start else None,
                "end": end.dt if end else None,
                "external_id": str(uid) if uid else None,
            }
            if include_description:
                description = component.get("description")
                event["description"] = str(description) if description else None
            events.append(event)
    except Exception:
        raise RuntimeError("Could not parse the iCal feed.") from None

    return events
