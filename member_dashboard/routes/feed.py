"""No work creation, source reads or model calls on a feed poll."""
from fastapi import APIRouter,Depends,Request,Query,HTTPException
from fastapi.responses import JSONResponse
from ..authorization import require_member
from ..auth import AuthError
from ..contracts import FeedPage,LatestPage
from ..publication import FeedError

router=APIRouter(prefix='/api/v1')


def read(request,principal,feature,cursor,limit):
    service=request.app.state.feed
    if service is None: raise HTTPException(503)
    try: return service.read_feed(principal,feature,cursor,limit)
    except AuthError: raise HTTPException(401) from None
    except FeedError as error:
        return JSONResponse(status_code=error.status,content={'error':error.code,'message':
            'Discard cached cards and request a new snapshot.' if error.code=='snapshot_reset' else 'Request unavailable.'})


@router.get('/feed',response_model=FeedPage)
def feed(request:Request,cursor:str | None=None,limit:int=Query(default=50,ge=1,le=100),principal=Depends(require_member)):
    return read(request,principal,'feed',cursor,limit)


@router.get('/setups',response_model=FeedPage)
def setups(request:Request,cursor:str | None=None,limit:int=Query(default=50,ge=1,le=100),principal=Depends(require_member)):
    return read(request,principal,'setups',cursor,limit)


def latest(request,principal,feature,source=None):
    service=request.app.state.feed
    if service is None: raise HTTPException(503)
    try: return service.latest(principal,feature,source=source)
    except AuthError: raise HTTPException(401) from None
    except FeedError as error:
        return JSONResponse(status_code=error.status,content={'error':error.code,'message':'Request unavailable.'})


@router.get('/feed/latest',response_model=LatestPage)
def feed_latest(request:Request,principal=Depends(require_member)):
    return latest(request,principal,'feed')


@router.get('/setups/latest',response_model=LatestPage)
def setups_latest(request:Request,principal=Depends(require_member)):
    return latest(request,principal,'setups')


@router.get('/alerts/latest',response_model=LatestPage)
def alerts_latest(request:Request,principal=Depends(require_member)):
    """The bot's #alerts posts: several analysts on one ticker (shown with analyst calls' access)."""
    from ..market_reader import SourceName
    return latest(request,principal,'feed',SourceName.SWARM)
