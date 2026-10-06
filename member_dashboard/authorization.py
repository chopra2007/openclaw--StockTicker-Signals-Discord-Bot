"""Live session/account guards; client roles never enter the principal."""
from fastapi import HTTPException, Request
from .auth import AuthError

SESSION_COOKIE = '__Host-member_session'


def require_member(request: Request):
    try:
        principal = request.app.state.auth.principal(request.cookies.get(SESSION_COOKIE,''), request.app.state.clock())
    except AuthError:
        raise HTTPException(401) from None
    return principal


def require_admin(request: Request):
    principal = require_member(request)
    if principal.role != 'admin':
        raise HTTPException(403)
    return principal


def require_csrf(request: Request):
    if request.headers.get('origin') != request.app.state.settings.origin:
        raise HTTPException(403)
    csrf = request.headers.get('x-csrf-token', '')
    if not csrf or len(csrf)>128:
        raise HTTPException(403)
    session = request.cookies.get(SESSION_COOKIE)
    try:
        if session:
            try:
                request.app.state.auth.principal(session,request.app.state.clock(),touch=False)
            except AuthError:
                pass
            else:
                return request.app.state.auth.check_session_csrf(session,csrf,request.app.state.clock())
        request.app.state.anonymous_csrf.check(request.cookies.get('__Host-member_csrf',''),csrf,request.app.state.clock())
    except AuthError:
        raise HTTPException(403) from None
