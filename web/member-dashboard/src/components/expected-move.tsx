'use client';
import {useEffect,useState} from 'react';
import Image from 'next/image';
import type {MovePayload} from '@/lib/contracts';
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
