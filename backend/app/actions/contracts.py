"""Validate proposed activity actions; no execution or database access."""

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


WEEKDAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}


class AddActivityArguments(BaseModel):
    """The same eight fields accepted by the existing Add Activity API."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    category: str
    subject: str | None
    activity_type: Literal["one_time", "daily", "weekly"]
    date: str | None
    weekday: str | None
    start_time: str | None
    end_time: str | None

    @model_validator(mode="after")
    def validate_activity_fields(self):
        self.name = self.name.strip()
        self.category = self.category.strip()
        if self.subject is not None:
            self.subject = self.subject.strip() or None
        if not self.name or not self.category:
            raise ValueError("Activity name and category are required.")

        if self.activity_type == "one_time":
            if self.date is None or self.weekday is not None:
                raise ValueError("One-time activities need a date and no weekday.")
            try:
                if date.fromisoformat(self.date).isoformat() != self.date:
                    raise ValueError
            except ValueError:
                raise ValueError("Activity date must be YYYY-MM-DD.") from None
        elif self.activity_type == "weekly":
            if self.date is not None or self.weekday not in WEEKDAYS:
                raise ValueError("Weekly activities need a valid weekday and no date.")
        elif self.date is not None or self.weekday is not None:
            raise ValueError("Daily activities cannot have a date or weekday.")

        for value in (self.start_time, self.end_time):
            if value is not None:
                if not re.fullmatch(r"\d{2}:\d{2}", value):
                    raise ValueError("Activity times must use HH:MM.")
                try:
                    datetime.strptime(value, "%H:%M")
                except ValueError:
                    raise ValueError("Activity times must be valid clock times.") from None
        if self.start_time is not None and self.end_time is not None:
            if self.start_time >= self.end_time:
                raise ValueError("End time must be later than start time.")
        return self


class AddActivityAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tool: Literal["add_activity"]
    arguments: AddActivityArguments
