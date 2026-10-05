import {adminSchema,adminInvites} from './admin-contracts';
import {csrfSchema,currentMemberSchema,feedSchema,loginSchema,memberSchema,researchSchema,reportPageSchema,savedReportSchema,conversationPageSchema,savedConversationSchema,conversationRef,assistantRunSchema} from './contracts';
import type {ResearchRequest} from './contracts';
let csrfToken:string|undefined;
let initial:ResearchRequest|undefined;
export function primeResearch(value:ResearchRequest){initial=value;}
export function initialResearch(id:string|null){return initial?.id===id?initial:null;}
export function discardInitialResearch(id:string|null){if(initial?.id===id)initial=undefined;}
let generation=0;
export const accessGeneration=()=>generation;
export function clearAccess(){csrfToken=undefined;initial=undefined;generation++;if(typeof window!=='undefined')window.dispatchEvent(new Event('member-clear'));}
export class ApiError extends Error {constructor(public status:number,public code:string){super(status===422?'Invalid or unsupported ticker.':status===429?'Request is limited; try again later.':status===404?'This report was not found.':status===401?'Please sign in to continue.':status===403?'Access is unavailable. Submit again after checking access.':'Unable to load this content. Please try again.');}}
export async function api<T>(path:string,init:RequestInit={}):Promise<T>{
  if(!/^\/(admin\/(?:members(?:\/[a-f0-9-]+\/(?:suspend|reactivate|revoke-sessions|reset-link))?|invites(?:\/[a-f0-9-]+)?|audit|health|features(?:\/(?:feed|setups|analysis|sec|options|em_daily|em_weekly|assistant))?)(?:\?cursor=[a-f0-9-]+)?|me|auth\/(csrf|login|redeem|reset|logout)|research(?:\/[A-Za-z0-9_-]+)?|conversations\/[A-Za-z0-9_-]+\/(?:messages|runs\/[A-Za-z0-9_-]+)|(?:reports|conversations)(?:\/[A-Za-z0-9_-]+)?(?:\?[^#]*)?|(?:feed|setups)(?:\?[^#]*)?)$/.test(path))throw new ApiError(400,'invalid_path');
  const stamp=generation, unsafe=!!init.method&&!['GET','HEAD'].includes(init.method.toUpperCase());
  if(unsafe&&!csrfToken){const challenge=await api<{token:string}>('/auth/csrf',{signal:init.signal});csrfToken=challenge.token;}
  const response=await fetch('/api/v1'+path,{...init,credentials:'same-origin',cache:'no-store',headers:{...init.headers,...(unsafe?{'Content-Type':'application/json','X-CSRF-Token':csrfToken!}:{})}});
  if(stamp!==generation)throw new DOMException('Access changed','AbortError');
  if(!response.ok){
    if(response.status===401)clearAccess();
    if(response.status===403)csrfToken=undefined;
    let code='unavailable';try{const body=await response.json();if(typeof body.error==='string'&&body.error.length<64)code=body.error;}catch{}
    throw new ApiError(response.status,code);
  }
  if(response.status===204)return undefined as T;
  const body:unknown=await response.json();
  if(stamp!==generation)throw new DOMException('Access changed','AbortError');
  const schema=path.startsWith('/admin/')?(path==='/admin/invites'&&!unsafe?adminInvites:adminSchema(path)):path==='/me'?currentMemberSchema:path==='/auth/csrf'?csrfSchema:path==='/auth/login'?loginSchema:path==='/auth/redeem'?memberSchema:path.startsWith('/research')?researchSchema:path.startsWith('/reports/')?savedReportSchema:path.startsWith('/reports')?reportPageSchema:/\/conversations\/[^/]+\/(?:messages|runs\/)/.test(path)?assistantRunSchema:path==='/conversations'&&unsafe?conversationRef:path.startsWith('/conversations/')?savedConversationSchema:path.startsWith('/conversations')?conversationPageSchema:feedSchema;
  const parsed=schema.safeParse(body);if(!parsed.success)throw new ApiError(502,'invalid_response');
  if(path==='/auth/login'){clearAccess();csrfToken=loginSchema.parse(parsed.data).csrf_token;}
  return parsed.data as T;
}
