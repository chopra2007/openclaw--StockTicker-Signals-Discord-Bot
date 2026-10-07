"""Market strip, watchlist and track record. Reads only the dashboard database: no Schwab or bot access."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from ..auth import AuthError
from ..authorization import require_csrf, require_member
from ..contracts import QuotesPage, RecordPage, StripPage, WatchlistPage
from .. import market_board, track_record
from ..features import require_features

router = APIRouter(prefix='/api/v1')


def member_read(request, principal, read):
    """Revalidate the session, then read inside one transaction. `read(con, now)` may raise HTTPException."""
    now = request.app.state.clock()
    try:
        with request.app.state.store.transaction() as con:
            request.app.state.auth.revalidate(principal, now, con=con)
            return read(con, now)
    except AuthError:
        raise HTTPException(401) from None


def schwab_visible(request):
    """The owner's Schwab permission can switch every Schwab number off. Asked before the read: it opens its own transaction."""
    return market_board.schwab_allowed(request.app.state.source_policy, 'display_raw', request.app.state.clock())


@router.get('/market/strip', response_model=StripPage)
def strip(request: Request, principal=Depends(require_member)):
    visible = schwab_visible(request)
    def read(con, now):
        if not visible: raise HTTPException(503)
        return market_board.strip(con, now)
    return member_read(request, principal, read)


@router.get('/market/quotes', response_model=QuotesPage)
def quotes(request: Request, symbols: str = Query(max_length=1200), principal=Depends(require_member)):
    visible = schwab_visible(request)
    def read(con, now):
        if not visible: return dict(quotes=[])
        return market_board.quotes(con, principal.member_id, symbols.upper().split(','), now)
    return member_read(request, principal, read)


@router.get('/watchlist', response_model=WatchlistPage)
def watchlist(request: Request, principal=Depends(require_member)):
    visible = schwab_visible(request)
    def read(con, now):
        page = market_board.watchlist(con, principal.member_id, now)
        if not visible:
            page['items'] = [dict(symbol=i['symbol'], added_at=i['added_at'], new_alert=i['new_alert']) for i in page['items']]
        return page
    return member_read(request, principal, read)


def change_watchlist(request, principal, ticker, write):
    ticker = ticker.upper()
    if not market_board.TICKER.match(ticker): raise HTTPException(422)
    def read(con, now):
        try: write(con, principal.member_id, ticker, now)
        except market_board.WatchlistFull: raise HTTPException(409) from None
    member_read(request, principal, read)


@router.put('/watchlist/{ticker}', response_model=WatchlistPage, dependencies=[Depends(require_csrf)])
def watch(ticker: str, request: Request, principal=Depends(require_member)):
    change_watchlist(request, principal, ticker, market_board.watch)
    return watchlist(request, principal)


@router.delete('/watchlist/{ticker}', status_code=204, dependencies=[Depends(require_csrf)])
def unwatch(ticker: str, request: Request, principal=Depends(require_member)):
    change_watchlist(request, principal, ticker, lambda con, member, tkr, now: market_board.unwatch(con, member, tkr))
    return Response(status_code=204)


@router.get('/record', response_model=RecordPage)
def record(request: Request, rows: int = Query(50, ge=0, le=50), principal=Depends(require_member)):
    visible = schwab_visible(request)
    def read(con, now):
        if not require_features(con, ['setups']): raise HTTPException(403)
        return track_record.summary(con, now, rows, with_spy=visible)
    return member_read(request, principal, read)
