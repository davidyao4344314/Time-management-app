"""FastAPI application assembly; feature routers own the HTTP handlers."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api import activities, ai, calendar, exams, imports, conversations, files, actions

from backend.app.database import initialize_database
from backend.app.conversations import storage as chat_storage
from backend.app.ai.actions import storage as action_storage
from backend.app.ai.context.adaptive import store as routing_store
from backend.app.files import storage as file_storage
from backend.app.api import study_sessions
from backend.app.planner import study_sessions as session_storage


def initialize_application_database():
    initialize_database((
        ("002_conversations", chat_storage.migrate),
        ("003_chat_summaries", chat_storage.migrate_summaries),
        ("004_memory_exports", chat_storage.migrate_memory_exports),
        ("005_routing_evidence", routing_store.migrate),
        ("006_imported_files", file_storage.migrate),
        ("007_action_proposals", action_storage.migrate),
        ("008_study_sessions", session_storage.migrate),
    ))


@asynccontextmanager
async def lifespan(_app):
    initialize_application_database()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(ai.router)
app.include_router(imports.router)
app.include_router(exams.router)
app.include_router(activities.router)
app.include_router(calendar.router)
app.include_router(conversations.router)
app.include_router(files.router)
app.include_router(actions.router)
app.include_router(study_sessions.router)
