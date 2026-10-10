"""No work creation, source reads or model calls on a feed poll."""
import sqlite3
from fastapi import APIRouter,Request,Query,HTTPException
from fastapi.responses import JSONResponse
from ..authorization import SESSION_COOKIE,require_member
from ..auth import AuthError
from ..contracts import FeedPage,LatestPage
from ..publication import FeedError

router=APIRouter(prefix='/api/v1')


def read(request,feature,cursor,limit):
    service=request.app.state.feed
    if service is None:
        require_member(request)
        raise HTTPException(503)
    # Authentication and delivery share the admitted transaction. An independent
    # dependency would contend with queued reads before they can be admitted.
    try: return service.read_feed(request.cookies.get(SESSION_COOKIE,''),feature,cursor,limit)
    except AuthError: raise HTTPException(401) from None
    except (sqlite3.Error,TimeoutError):
        return JSONResponse(status_code=503,content={'error':'unavailable','message':'Request unavailable.'})
    except FeedError as error:
        return JSONResponse(status_code=error.status,content={'error':error.code,'message':
            'Discard cached cards and request a new snapshot.' if error.code=='snapshot_reset' else 'Request unavailable.'})


@router.get('/feed',response_model=FeedPage)
def feed(request:Request,cursor:str | None=None,limit:int=Query(default=50,ge=1,le=100)):
    return read(request,'feed',cursor,limit)


@router.get('/setups',response_model=FeedPage)
def setups(request:Request,cursor:str | None=None,limit:int=Query(default=50,ge=1,le=100)):
    return read(request,'setups',cursor,limit)


def latest(request,feature,source=None):
    service=request.app.state.feed
    if service is None:
        require_member(request)
        raise HTTPException(503)
    try: return service.latest(request.cookies.get(SESSION_COOKIE,''),feature,source=source)
    except AuthError: raise HTTPException(401) from None
    except (sqlite3.Error,TimeoutError):
        return JSONResponse(status_code=503,content={'error':'unavailable','message':'Request unavailable.'})
    except FeedError as error:
        return JSONResponse(status_code=error.status,content={'error':error.code,'message':'Request unavailable.'})


@router.get('/feed/latest',response_model=LatestPage)
def feed_latest(request:Request):
    return latest(request,'feed')


@router.get('/setups/latest',response_model=LatestPage)
def setups_latest(request:Request):
    return latest(request,'setups')


@router.get('/alerts/latest',response_model=LatestPage)
def alerts_latest(request:Request):
    """The bot's #alerts posts: several analysts on one ticker (shown with analyst calls' access)."""
    from ..market_reader import SourceName
    return latest(request,'feed',SourceName.SWARM)
