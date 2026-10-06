"""Closed admin endpoints. No roles, bot controls or arbitrary operational commands."""
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from ..authorization import require_admin,require_csrf
from ..auth import AuthError
from ..admin import AdminError
from ..contracts import PublicModel,Feature
from ..admin_contracts import FeatureState,TokenLink,MemberPage,InvitePage,AuditPage,AdminHealth

router=APIRouter(prefix='/api/v1/admin')

class FeatureWrite(PublicModel):
    enabled: bool

class EmptyWrite(PublicModel):
    pass

def call(request,name,*args):
    try: return getattr(request.app.state.admin,name)(*args)
    except AuthError: raise HTTPException(401) from None
    except AdminError as error: raise HTTPException(error.status) from None

@router.get('/members',response_model=MemberPage)
def members(request:Request,cursor:UUID|None=None,actor=Depends(require_admin)):
    return call(request,'page',actor,'members',str(cursor) if cursor else None)

@router.get('/invites',response_model=InvitePage)
def invites(request:Request,cursor:UUID|None=None,actor=Depends(require_admin)):
    return call(request,'page',actor,'invites',str(cursor) if cursor else None)

@router.get('/audit',response_model=AuditPage)
def audit(request:Request,cursor:UUID|None=None,actor=Depends(require_admin)):
    return call(request,'page',actor,'audit',str(cursor) if cursor else None)

@router.get('/health',response_model=AdminHealth)
def health(request:Request,actor=Depends(require_admin)):
    return call(request,'health_snapshot',actor)

@router.get('/features',response_model=list[FeatureState])
def features(request:Request,actor=Depends(require_admin)):
    return call(request,'features',actor)

@router.put('/features/{feature}',response_model=FeatureState,dependencies=[Depends(require_csrf)])
def set_feature(feature:Feature,body:FeatureWrite,request:Request,actor=Depends(require_admin)):
    return call(request,'set_feature',actor,feature,body.enabled)

@router.post('/invites',response_model=TokenLink,dependencies=[Depends(require_csrf)])
def invite(body:EmptyWrite,request:Request,actor=Depends(require_admin)):
    return call(request,'create_invite',actor)

@router.delete('/invites/{invite_id}',status_code=204,dependencies=[Depends(require_csrf)])
def revoke(invite_id:UUID,request:Request,actor=Depends(require_admin)):
    call(request,'revoke_invite',actor,str(invite_id));return Response(status_code=204)

@router.post('/members/{member_id}/reset-link',response_model=TokenLink,dependencies=[Depends(require_csrf)])
def reset(member_id:UUID,body:EmptyWrite,request:Request,actor=Depends(require_admin)):
    return call(request,'create_reset',actor,str(member_id))

@router.post('/members/{member_id}/{action}',status_code=204,dependencies=[Depends(require_csrf)])
def mutate(member_id:UUID,action:str,body:EmptyWrite,request:Request,actor=Depends(require_admin)):
    method={'suspend':'suspend_member','reactivate':'reactivate_member','revoke-sessions':'revoke_sessions'}.get(action)
    if method is None: raise HTTPException(404)
    call(request,method,actor,str(member_id));return Response(status_code=204)
