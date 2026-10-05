"""Private read/delete history routes, with CSRF on every mutation."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from ..auth import AuthError
from ..authorization import require_csrf, require_member
from ..contracts import ConversationPage, ReportPage, SavedConversation, SavedReport
from ..history import HistoryError

router = APIRouter(prefix='/api/v1')


def invoke(request, method, *args, **kwargs):
    try:
        return getattr(request.app.state.history,method)(*args,**kwargs)
    except AuthError:
        raise HTTPException(401) from None
    except HistoryError as error:
        raise HTTPException(error.status) from None


@router.get('/reports', response_model=ReportPage)
def reports(request: Request, principal=Depends(require_member), cursor: str | None=Query(None,max_length=4096), limit: int=Query(50,ge=1,le=100)):
    return invoke(request,'list_reports',principal,cursor,limit)


@router.get('/reports/{report_id}', response_model=SavedReport)
def report(report_id: str, request: Request, principal=Depends(require_member)):
    return invoke(request,'get_report',principal,report_id)


@router.delete('/reports/{report_id}', status_code=204, dependencies=[Depends(require_csrf)])
def delete_report(report_id: str, request: Request, principal=Depends(require_member)):
    invoke(request,'delete_report',principal,report_id)
    return Response(status_code=204)


@router.get('/conversations', response_model=ConversationPage)
def conversations(request: Request, principal=Depends(require_member), cursor: str | None=Query(None,max_length=4096), limit: int=Query(50,ge=1,le=100)):
    return invoke(request,'list_conversations',principal,cursor,limit)


@router.get('/conversations/{conversation_id}', response_model=SavedConversation)
def conversation(conversation_id: str, request: Request, principal=Depends(require_member), cursor: str | None=Query(None,max_length=4096), limit: int=Query(50,ge=1,le=100)):
    return invoke(request,'get_conversation',principal,conversation_id,cursor,limit)


@router.delete('/conversations/{conversation_id}', status_code=204, dependencies=[Depends(require_csrf)])
def delete_conversation(conversation_id: str, request: Request, principal=Depends(require_member)):
    invoke(request,'delete_conversation',principal,conversation_id)
    return Response(status_code=204)
