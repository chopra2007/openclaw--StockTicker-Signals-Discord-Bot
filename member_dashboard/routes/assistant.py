"""Explicit CSRF-protected submissions; GET only reads persisted status."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from ..auth import AuthError
from ..authorization import require_csrf, require_member
from ..contracts import PublicModel, AssistantRun, ConversationRef
from ..history import HistoryError

router=APIRouter(prefix='/api/v1/conversations')


class CreateConversation(PublicModel):
    title: str = Field(min_length=1,max_length=256)


class SubmitMessage(PublicModel):
    message: str = Field(min_length=1,max_length=4000)
    ticker_context: str | None = Field(default=None,max_length=16)


def invoke(request,method,*args):
    try: return getattr(request.app.state.assistant,method)(*args)
    except AuthError: raise HTTPException(401) from None
    except HistoryError as error: raise HTTPException(error.status) from None


@router.post('',response_model=ConversationRef,dependencies=[Depends(require_csrf)])
def create(body:CreateConversation,request:Request,principal=Depends(require_member)):
    return invoke(request,'create_conversation',principal,body.title)


@router.post('/{conversation_id}/messages',response_model=AssistantRun,dependencies=[Depends(require_csrf)])
def submit(conversation_id:str,body:SubmitMessage,request:Request,principal=Depends(require_member)):
    return invoke(request,'submit',principal,conversation_id,body.message,body.ticker_context)


@router.get('/{conversation_id}/runs/{run_id}',response_model=AssistantRun)
def status(conversation_id:str,run_id:str,request:Request,principal=Depends(require_member)):
    return invoke(request,'get_run',principal,conversation_id,run_id)
