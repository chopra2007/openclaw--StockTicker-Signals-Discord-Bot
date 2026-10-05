'use client';
import {useEffect,useRef,useState} from 'react';
import {api,ApiError} from '@/lib/api';
import {type AdminFeatures,type AdminMembers,type AdminInvites,type AdminAudit,type AdminHealth,type AdminToken} from '@/lib/admin-contracts';
import {features,labels} from '@/lib/contracts';
import {formatPacific} from '@/lib/time';
import {AppShell} from './app-shell';
import {useSession} from './session';
import {useHistoryRead} from './history-list';
import {Button} from './ui/button';

export function AdminPanel(){
 const {member,refresh}=useSession(),allowed=member?.role==='admin';
 const [revision,setRevision]=useState(0),[tab,setTab]=useState<'members'|'invites'|'audit'>('members');
 const [cursor,setCursor]=useState<string|null>(null),[previous,setPrevious]=useState<(string|null)[]>([]);
 const access=member?.id+':'+member?.role+JSON.stringify(member?.features);
 const [busyKey,setBusyKey]=useState<string|null>(null),[error,setError]=useState('');
 const [link,setLink]=useState<{access:string;value:string;expires:number}|null>(null);
 const writeRef=useRef<AbortController|null>(null);
 useEffect(()=>()=>{writeRef.current?.abort();writeRef.current=null;},[access]);
 const listing=useHistoryRead<AdminMembers|AdminInvites|AdminAudit>(allowed?'/admin/'+tab+(cursor?'?cursor='+cursor:''):null,access+revision);
 const switches=useHistoryRead<AdminFeatures>(allowed?'/admin/features':null,access+revision);
 const health=useHistoryRead<AdminHealth>(allowed?'/admin/health':null,access+revision);
 const busy=busyKey===access;
 async function write(path:string,body:object={},tokenKind?:'join'|'reset'){
  if(!allowed||busy)return;
  writeRef.current?.abort();const controller=new AbortController();writeRef.current=controller;
  setBusyKey(access);setError('');setLink(null);
  try{
   const response=await api<AdminToken>('/admin/'+path,{method:path.startsWith('features/')?'PUT':path.startsWith('invites/')?'DELETE':'POST',body:path.startsWith('invites/')?undefined:JSON.stringify(body),signal:controller.signal});
   if(controller.signal.aborted||writeRef.current!==controller)return;
   if(tokenKind)setLink({access,value:location.origin+'/'+tokenKind+'#'+response.token,expires:response.expires_at});
   setRevision(x=>x+1);await refresh();
  }catch(e){if(!controller.signal.aborted)setError(e instanceof ApiError?e.message:'Unable to save this change.');}
  finally{if(writeRef.current===controller){setBusyKey(null);writeRef.current=null;}}
 }
 function choose(next:typeof tab){setTab(next);setCursor(null);setPrevious([]);}
 const data=health.data;
 return <AppShell><main id="main" className="page-content admin-page"><h1 tabIndex={-1}>Administration</h1>{!allowed?<p>Administrator access required.</p>:<>
 <p>Manage member access and dashboard visibility.</p>
 {error&&<p role="alert">{error}</p>}
 {link?.access===access&&<aside className="admin-link"><label>One-time link<textarea aria-label="One-time link" readOnly value={link.value}/></label><p>Expires {formatPacific(link.expires)}. Share privately with the verified recipient.</p><Button variant="outline" onClick={()=>setLink(null)}>Dismiss link</Button></aside>}
 <section aria-labelledby="feature-title"><h2 id="feature-title">Dashboard features</h2>{switches.error&&<p role="alert">{switches.error}</p>}<div className="admin-switches">{features.map(feature=><label key={feature}><input type="checkbox" checked={!!switches.data?.find(row=>row.name===feature)?.enabled} disabled={busy||!switches.data} onChange={e=>void write('features/'+feature,{enabled:e.target.checked})}/>{labels[feature]}</label>)}</div></section>
 <section aria-labelledby="accounts-title"><h2 id="accounts-title">Member access</h2><p>Verify identity outside this dashboard before issuing a password reset.</p><Button disabled={busy} onClick={()=>void write('invites',{},'join')}>Create invitation</Button>
 <div className="admin-tabs" aria-label="Administration lists">{(['members','invites','audit'] as const).map(value=><Button key={value} variant="outline" aria-pressed={tab===value} onClick={()=>choose(value)}>{value==='members'?'Members':value==='invites'?'Invitations':'Audit log'}</Button>)}</div>
 {listing.error&&<p role="alert">{listing.error}</p>}{!listing.data&&!listing.error?<p role="status">Checking access…</p>:null}
 <div className="admin-rows">{listing.data?.items.map(row=><article key={row.id} className="admin-row" data-testid={'username' in row?'admin-member':undefined}>
 {'username' in row?<><div><strong>{row.username}</strong><p>{row.role} · {row.status}</p></div><div className="admin-actions"><Button variant="outline" disabled={busy||row.id===member?.id} onClick={()=>void write('members/'+row.id+'/'+(row.status==='active'?'suspend':'reactivate'))}>{row.status==='active'?'Suspend':'Reactivate'}</Button><Button variant="outline" disabled={busy||row.id===member?.id} onClick={()=>void write('members/'+row.id+'/revoke-sessions')}>Revoke sessions</Button><Button variant="outline" disabled={busy||row.id===member?.id} onClick={()=>void write('members/'+row.id+'/reset-link',{},'reset')}>Reset password</Button></div></>:
 'consumed' in row?<><div><strong>Invitation</strong><p>{row.id}</p><p>{row.consumed?'Redeemed':row.revoked?'Revoked':'Unredeemed'} · Expires {formatPacific(row.expires_at)}</p></div><Button variant="outline" disabled={busy||row.consumed||row.revoked} onClick={()=>void write('invites/'+row.id)}>Revoke invitation</Button></>:
 <div><strong>{row.action.replaceAll('_',' ')} · {row.result}</strong><p>{formatPacific(row.occurred_at)}</p><p>Actor: {row.actor_id??'Local operator'} · Target: {row.target_id??'Unavailable'}</p></div>}
 </article>)}</div>{listing.data?.items.length===0&&<p>No records.</p>}
 <div className="admin-actions"><Button variant="outline" disabled={!previous.length} onClick={()=>{setCursor(previous.at(-1)??null);setPrevious(x=>x.slice(0,-1));}}>Previous page</Button><Button variant="outline" disabled={!listing.data?.next_cursor} onClick={()=>{setPrevious(x=>[...x,cursor]);setCursor(listing.data?.next_cursor??null);}}>Next page</Button></div>
 </section>
 <section aria-labelledby="health-title"><h2 id="health-title">Operational visibility</h2><p>Local observations only. Responsiveness does not prove compute progress.</p>{health.error&&<p role="alert">{health.error}</p>}{data&&<>
 <div className="admin-health">{(['api','frontend','supervisor','compute'] as const).map(key=><article key={key} data-testid={'health-'+key}><h3>{key==='api'?'API':key[0].toUpperCase()+key.slice(1)}</h3><strong>{data[key].status}</strong><p>{data[key].state??'No state observation'}</p><p>Observed: {formatPacific(data[key].observed_at)}</p>{key==='compute'&&<p>Last completion: {formatPacific(data[key].progress_at)}</p>}</article>)}</div>
 <p>Queue: {data.queue.queued} pending · {data.queue.running} running · {data.queue.draining} draining. Oldest wait: {data.queue.oldest_age_seconds===null?'Unavailable':Math.floor(data.queue.oldest_age_seconds)+' seconds'}.</p>
 <h3>AI usage · past 24 hours</h3><p>{data.usage.runs} runs · {data.usage.known_usage_runs} with known token usage. Input tokens: {data.usage.input_tokens??'Unavailable'} · Output tokens: {data.usage.output_tokens??'Unavailable'} · Cost: {data.usage.cost===null?'Unavailable':'$'+data.usage.cost.toFixed(4)}.</p>
 <h3>Source projection freshness</h3>{data.sources.map(source=><p key={source.source}>{source.source.replaceAll('_',' ')}: {source.stale?'unavailable or stale':'current'} · Last successful check: {formatPacific(source.succeeded_at)}</p>)}
 <h3>Sanitized failures · past 24 hours</h3>{data.failures.length?data.failures.map(row=><p key={row.code}>{row.code.replaceAll('_',' ')}: {row.count}</p>):<p>No recorded failures.</p>}
 </>}</section>
 </>}</main></AppShell>;
}
