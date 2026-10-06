"""Research writes enqueue durable work only. Reads never execute providers."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from ..auth import AuthError
from ..authorization import require_csrf, require_member
from ..contracts import PublicModel, ResearchRequest
from ..jobs import ResearchError

router = APIRouter(prefix='/api/v1')


class ResearchSubmission(PublicModel):
    ticker: str = Field(min_length=1, max_length=16)
    refresh: bool = False


@router.post('/research', response_model=ResearchRequest, dependencies=[Depends(require_csrf)])
def submit(body: ResearchSubmission, request: Request, principal=Depends(require_member)):
    try:
        return request.app.state.research.request_research(principal, body.ticker, body.refresh, request.app.state.clock())
    except AuthError:
        raise HTTPException(401) from None
    except ResearchError as error:
        raise HTTPException(error.status, detail=error.code) from None


@router.get('/research/{request_id}', response_model=ResearchRequest)
def read(request_id: str, request: Request, principal=Depends(require_member)):
    try:
        value = request.app.state.research.get_request(principal, request_id, request.app.state.clock())
    except AuthError:
        raise HTTPException(401) from None
    if value is None:
        raise HTTPException(404)
    return value
