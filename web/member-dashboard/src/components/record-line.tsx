'use client';
import Link from 'next/link';
import {usePoll} from '@/lib/use-market';
import type {RecordPage} from '@/lib/contracts';
/** One line on Overview: how the bot's alerts did a day later, with a link to the full record. */
export function RecordLine(){const {data}=usePoll<RecordPage>('/record?rows=0',600000);const h=data?.horizons.find(x=>x.key==='1d');if(!data||!h)return null;
 return <p className="record-line">{h.count>=20?<>Of {h.count.toLocaleString('en-US')} alerts in the last {data.days} days, {h.up.toLocaleString('en-US')} ({Math.round(h.up/h.count*100)}%) were higher a day later. </>:null}<Link href="/record">Track record <span aria-hidden="true">›</span></Link></p>}
