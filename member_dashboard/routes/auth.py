"""Auth-only routes; no administration/recovery over HTTP."""
from typing import Literal
from dataclasses import dataclass, field
import hmac
import secrets
import threading
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from ..auth import AuthError, digest
from ..authorization import SESSION_COOKIE, require_csrf, require_member
from ..contracts import PublicModel
from ..features import feature_mask

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


class FeatureView(PublicModel):
    enabled: bool
    version: int = Field(ge=1)


class MemberFeatures(PublicModel):
    feed: FeatureView
    setups: FeatureView
    analysis: FeatureView
    sec: FeatureView
    options: FeatureView
    em_daily: FeatureView
    em_weekly: FeatureView
    assistant: FeatureView


class CurrentMemberView(MemberView):
    features: MemberFeatures


class LoginView(PublicModel):
    member: MemberView
    csrf_token: str


class CsrfView(PublicModel):
    token: str


@dataclass(frozen=True)
class AnonymousChallenge:
    token: str = field(repr=False)
    expires_at: float
    address_digest: bytes = field(repr=False)


class AnonymousCsrf:
    """Bounded synchronizer challenges. Restart invalidates anonymous forms safely."""
    def __init__(self):
        self._values = {}
        self._issued_by_address = {}
        self._lock = threading.Lock()

    def issue(self, now, address, existing_cookie=''):
        address_key = digest(address)
        with self._lock:
            self._values = {key:value for key,value in self._values.items() if value.expires_at>now}
            self._issued_by_address = {key:[stamp for stamp in stamps if stamp>now-900]
                                       for key,stamps in self._issued_by_address.items()
                                       if any(stamp>now-900 for stamp in stamps)}
            row = self._values.get(digest(existing_cookie))
            if row is not None and hmac.compare_digest(row.address_digest,address_key):
                return existing_cookie,row.token,row.expires_at
            history = self._issued_by_address.get(address_key,[])
            # A single trusted address can occupy at most50 of4096 slots/15min,
            # even if it discards every cookie or changes forwarded headers.
            if len(history)>=50:
                raise AuthError()
            if len(self._values)>=4096:
                raise AuthError()
            cookie, token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self._values[digest(cookie)] = AnonymousChallenge(token,now+900,address_key)
            self._issued_by_address[address_key] = [*history,now]
        return cookie, token, now+900

    def check(self,cookie,token,now):
        with self._lock:
            row = self._values.get(digest(cookie))
            if row is None or row.expires_at<=now or not hmac.compare_digest(digest(row.token),digest(token)):
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
    try:
        cookie, token, expires = request.app.state.anonymous_csrf.issue(
            now,request.client.host if request.client else 'unknown',
            request.cookies.get('__Host-member_csrf',''))
    except AuthError:
        raise HTTPException(403) from None
    response.set_cookie('__Host-member_csrf',cookie,max_age=max(0,int(expires-now)),path='/',secure=True,httponly=True,samesite='lax')
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


@router.get('/me',response_model=CurrentMemberView)
def me(request:Request,principal=Depends(require_member)):
    try:
        with request.app.state.store.transaction() as con:
            request.app.state.auth.revalidate(principal,request.app.state.clock(),con=con)
            row = con.execute('SELECT id,username,role FROM members WHERE id=?',(principal.member_id,)).fetchone()
            features = MemberFeatures(**{name:FeatureView(enabled=stamp[0],version=stamp[1])
                                        for name,stamp in feature_mask(con).items()})
    except AuthError:
        raise HTTPException(401) from None
    return CurrentMemberView(id=row[0],username=row[1],role=row[2],features=features)


@router.post('/auth/logout',status_code=204)
def logout(request:Request,response:Response,principal=Depends(require_csrf)):
    if principal is None:
        raise HTTPException(401)
    try:
        request.app.state.auth.logout(principal,request.app.state.clock())
    except AuthError:
        raise HTTPException(401) from None
    response.delete_cookie(SESSION_COOKIE,path='/',secure=True,httponly=True,samesite='lax')
