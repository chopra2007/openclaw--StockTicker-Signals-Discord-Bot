"""Auth-only routes; no administration/recovery over HTTP."""
from typing import Literal
import hmac
import secrets
import threading
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from ..auth import AuthError, digest
from ..authorization import SESSION_COOKIE, require_csrf, require_member
from ..contracts import PublicModel

router = APIRouter(prefix='/api/v1')


class Credentials(PublicModel):
    username: str = Field(min_length=1,max_length=128)
    password: str = Field(min_length=1,max_length=128,repr=False)


class Redeem(Credentials):
    token: str = Field(min_length=1,max_length=128,repr=False)


class Reset(PublicModel):
    token: str = Field(min_length=1,max_length=128,repr=False)
    password: str = Field(min_length=1,max_length=128,repr=False)


class MemberView(PublicModel):
    id: str
    username: str
    role: Literal['member','admin']


class LoginView(PublicModel):
    member: MemberView
    csrf_token: str


class CsrfView(PublicModel):
    token: str


class AnonymousCsrf:
    """Bounded synchronizer challenges. Restart invalidates anonymous forms safely."""
    def __init__(self):
        self._values = {}
        self._lock = threading.Lock()

    def issue(self, now):
        cookie, token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self._lock:
            self._values = {key:value for key,value in self._values.items() if value[1]>now}
            if len(self._values)>=4096:
                raise AuthError()
            self._values[digest(cookie)] = (digest(token),now+900)
        return cookie, token

    def check(self,cookie,token,now):
        with self._lock:
            row = self._values.get(digest(cookie))
            if row is None or row[1]<=now or not hmac.compare_digest(row[0],digest(token)):
                raise AuthError()


def member_view(member):
    return MemberView(id=member.id,username=member.username,role=member.role)


@router.get('/auth/csrf',response_model=CsrfView)
def csrf(request:Request,response:Response):
    now = request.app.state.clock()
    session = request.cookies.get(SESSION_COOKIE)
    if session:
        try:
            return CsrfView(token=request.app.state.auth.session_csrf(session,now))
        except AuthError:
            response.delete_cookie(SESSION_COOKIE,path='/',secure=True,httponly=True,samesite='lax')
    cookie, token = request.app.state.anonymous_csrf.issue(now)
    response.set_cookie('__Host-member_csrf',cookie,max_age=900,path='/',secure=True,httponly=True,samesite='lax')
    return CsrfView(token=token)


@router.post('/auth/redeem',status_code=201,response_model=MemberView,dependencies=[Depends(require_csrf)])
def redeem(body:Redeem,request:Request):
    try:
        request.app.state.auth.reserve_public_write(request.client.host if request.client else 'unknown',request.app.state.clock())
        return member_view(request.app.state.auth.redeem_invite(body.token,body.username,body.password,request.app.state.clock()))
    except AuthError:
        raise HTTPException(400) from None


@router.post('/auth/login',response_model=LoginView,dependencies=[Depends(require_csrf)])
def login(body:Credentials,request:Request,response:Response):
    try:
        # Address comes from the ASGI server, never untrusted forwarded headers.
        issued = request.app.state.auth.login(body.username,body.password,request.app.state.clock(),request.client.host if request.client else 'unknown')
    except AuthError:
        raise HTTPException(401) from None
    response.set_cookie(SESSION_COOKIE,issued.token,max_age=43200,path='/',secure=True,httponly=True,samesite='lax')
    response.delete_cookie('__Host-member_csrf',path='/',secure=True,httponly=True,samesite='lax')
    return LoginView(member=member_view(issued.member),csrf_token=issued.csrf_token)


@router.post('/auth/reset',status_code=204,dependencies=[Depends(require_csrf)])
def reset(body:Reset,request:Request,response:Response):
    try:
        request.app.state.auth.reserve_public_write(request.client.host if request.client else 'unknown',request.app.state.clock())
        request.app.state.auth.reset_password(body.token,body.password,request.app.state.clock())
    except AuthError:
        raise HTTPException(400) from None
    response.delete_cookie(SESSION_COOKIE,path='/',secure=True,httponly=True,samesite='lax')


@router.get('/me',response_model=MemberView)
def me(request:Request,principal=Depends(require_member)):
    with request.app.state.store.transaction() as con:
        request.app.state.auth.revalidate(principal,request.app.state.clock(),con=con)
        row = con.execute('SELECT id,username,role FROM members WHERE id=?',(principal.member_id,)).fetchone()
    return MemberView(id=row[0],username=row[1],role=row[2])


@router.post('/auth/logout',status_code=204)
def logout(request:Request,response:Response,principal=Depends(require_csrf)):
    if principal is None:
        raise HTTPException(401)
    try:
        request.app.state.auth.logout(principal,request.app.state.clock())
    except AuthError:
        raise HTTPException(401) from None
    response.delete_cookie(SESSION_COOKIE,path='/',secure=True,httponly=True,samesite='lax')
