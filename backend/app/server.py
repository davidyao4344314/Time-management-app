"""FastAPI application assembly; feature routers own the HTTP handlers."""
from fastapi import FastAPI

from backend.app.api import activities, ai, calendar, exams, imports, conversations, files, actions

app = FastAPI()
app.include_router(ai.router)
app.include_router(imports.router)
app.include_router(exams.router)
app.include_router(activities.router)
app.include_router(calendar.router)
app.include_router(conversations.router)
app.include_router(files.router)
app.include_router(actions.router)
