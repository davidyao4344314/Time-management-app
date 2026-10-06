"""Owner-scoped chat HTTP adapter. Never trust a supplied owner ID."""
from uuid import uuid4
from sqlite3 import Error as SQLiteError

from fastapi import APIRouter, HTTPException, Query, Request, Response

from backend.app.conversations import service
from backend.app.api import action_runtime
from backend.app.conversations.contracts import CreateConversation, SendMessage, ConversationSettings, ConversationNotFound, ConversationConflict
from backend.app.ai.agent.contracts import InvalidProposalError
from openai import OpenAIError
from pydantic import ValidationError
from backend.app.infrastructure.identity import sign_owner, valid_owner

router = APIRouter(prefix='/conversations')


def resolve_owner(request, response):
    owner = request.cookies.get('ai_owner')
    if not valid_owner(owner, request.cookies.get('ai_owner_signature')):
        # Preserve only a verified legacy browser identity; never claim others.
        legacy = request.cookies.get('ai_agent_session')
        owner = legacy if valid_owner(legacy, request.cookies.get('ai_agent_session_signature')) else uuid4().hex
        for name, value in (('ai_owner', owner), ('ai_owner_signature', sign_owner(owner))):
            response.set_cookie(name, value, httponly=True, samesite='lax', path='/',
                                secure=request.url.scheme == 'https')
    legacy = request.cookies.get('ai_agent_session')
    if legacy == owner and valid_owner(legacy, request.cookies.get('ai_agent_session_signature')):
        call_service(service.link_verified_legacy_chat,owner,legacy)
    return owner


def call_service(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ConversationNotFound:
        raise HTTPException(404, 'Conversation not found.') from None
    except ConversationConflict as error:
        raise HTTPException(409, str(error)) from None
    except (SQLiteError, OSError):
        raise HTTPException(500, 'Could not access local conversation storage.') from None
    except OpenAIError:
        raise HTTPException(502, 'The AI request failed. Check model access, key and network.') from None
    except (InvalidProposalError, ValidationError):
        raise HTTPException(502, 'The AI response was incomplete or invalid.') from None
    except RuntimeError:
        raise HTTPException(502, 'Could not complete the AI request. Your saved messages are preserved.') from None


@router.post('')
def create_conversation(body: CreateConversation, request: Request, response: Response):
    return call_service(service.create_chat, resolve_owner(request, response), body.title)


@router.get('')
def list_conversations(request: Request, response: Response):
    return {'conversations': call_service(service.list_chats, resolve_owner(request, response))}


@router.get('/{conversation_id}/messages')
def read_conversation(conversation_id: str, request: Request, response: Response,
                      before: int | None = Query(default=None, ge=1), limit: int = Query(default=50, ge=1, le=100)):
    return call_service(service.read_chat, resolve_owner(request, response), conversation_id, before=before, limit=limit)


@router.post('/{conversation_id}/messages')
def send_message(conversation_id: str, body: SendMessage, request: Request, response: Response):
    owner = resolve_owner(request, response)
    response.headers["Cache-Control"] = "no-store"
    return call_service(service.send_message, owner, conversation_id, body.request_id, body.message,
                        register_actions=lambda proposals: [action_runtime.service.register(owner, proposal)
                                                           for proposal in proposals])


@router.patch('/{conversation_id}/settings')
def update_settings(conversation_id: str, body: ConversationSettings, request: Request, response: Response):
    return call_service(service.update_memory_sharing, resolve_owner(request,response),conversation_id,body.memory_sharing_enabled)


@router.post('/{conversation_id}/memory/export')
def export_memory(conversation_id: str, request: Request, response: Response):
    return call_service(service.retry_memory_export,resolve_owner(request,response),conversation_id)


@router.post('/{conversation_id}/summary')
def summarize_chat(conversation_id: str, request: Request, response: Response):
    return call_service(service.summarize_chat,resolve_owner(request,response),conversation_id)
