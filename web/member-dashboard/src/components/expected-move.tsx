'use client';
import {useEffect,useState} from 'react';
import Image from 'next/image';
import type {MovePayload,SectionResult} from '@/lib/contracts';
import {clearAccess} from '@/lib/api';
import {formatDay} from '@/lib/time';
import {money} from '@/lib/format';
function OwnedChart({id,horizon}:{id:string;horizon:string}){const [url,setUrl]=useState<string|null>(null);useEffect(()=>{const abort=new AbortController();let objectUrl:string|undefined;void(async()=>{try{const response=await fetch('/api/v1/assets/'+encodeURIComponent(id),{credentials:'same-origin',cache:'no-store',signal:abort.signal});if(response.status===401)clearAccess();if(!response.ok||response.headers.get('content-type')?.split(';')[0]!=='image/png')return;const blob=await response.blob();if(!abort.signal.aborted&&blob.size<=2_000_000){objectUrl=URL.createObjectURL(blob);setUrl(objectUrl);}}catch{}})();return()=>{abort.abort();if(objectUrl)URL.revokeObjectURL(objectUrl);};},[id]);return url?<Image unoptimized src={url} alt={`${horizon} expected move chart`} width={760} height={170}/>:null}
/** One clear line: ±move, the range, and the expiry it is measured to. */
export function ExpectedMove({payload}:{payload:MovePayload}){const main=payload.ranges[0];const spot=payload.spot?.value;const move=main?.expected_move?.value;
 const pct=spot&&move?(100*move/spot).toFixed(1)+'%':null;
 return <><div className="move-line"><span className="move-big">±{money(move)}</span>{pct&&<span className="move-pct">{pct}</span>}</div>
 <p className="move-range">{money(main?.lower?.value)} – {money(main?.upper?.value)}{payload.expiry?<>, by {formatDay(payload.expiry)}</>:null}</p>
 {payload.chart_asset_id&&<OwnedChart key={payload.chart_asset_id} id={payload.chart_asset_id} horizon={payload.horizon==='daily'?'Daily':'Weekly'}/>}</>}
/** Today's and this week's expected move as ONE group, one row per expiry date, so each date shows once.
 *  Rows come from whichever section completed; the loading skeleton shows only while one is still queued or running. */
export function ExpectedMoveGroup({daily,weekly}:{daily?:SectionResult;weekly?:SectionResult}){
 const moves=[daily,weekly].flatMap(r=>r?.payload?.kind==='move'&&r.payload.ranges[0]?.expected_move?.value!=null?[r.payload]:[]);
 const rows=moves.filter((m,i)=>!m.expiry||moves.findIndex(o=>o.expiry===m.expiry)===i);
 if(rows.length===0)return [daily,weekly].some(r=>r&&['queued','running'].includes(r.status))?<div className="skeleton-list"><span/></div>:<p className="quiet">Expected move isn’t available right now.</p>;
 return <ul className="rp-rows">{rows.map(m=>{const main=m.ranges[0],spot=m.spot?.value,move=main.expected_move!.value!;const pct=spot?(100*move/spot).toFixed(1)+'%':null;
  return <li key={m.horizon}><div className="rp-row"><span className="rp-label">{m.expiry?'By '+formatDay(m.expiry):m.horizon==='daily'?'Next close':'This week'}</span><span className="rp-val">±{money(move)}{pct&&<small> ({pct})</small>}</span></div>
  <p className="rp-why">{money(main.lower?.value)} – {money(main.upper?.value)}</p></li>;})}</ul>}
