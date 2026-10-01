"""FastAPI application assembly; feature routers own the HTTP handlers."""
from fastapi import FastAPI

from backend.app.api import activities, ai, calendar, exams, imports

app = FastAPI()
app.include_router(ai.router)
app.include_router(imports.router)
app.include_router(exams.router)
app.include_router(activities.router)
app.include_router(calendar.router)
