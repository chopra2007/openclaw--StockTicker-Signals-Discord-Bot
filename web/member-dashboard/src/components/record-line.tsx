'use client';
import Link from 'next/link';
import {usePoll} from '@/lib/use-market';
import type {RecordPage} from '@/lib/contracts';
/** One line on Overview: how the bot's alerts did a day later, with a link to the full record. */
export function RecordLine(){const {data}=usePoll<RecordPage>('/record?rows=0',600000);const h=data?.horizons.find(x=>x.key==='1d');if(!data||!h)return null;
 return <p className="record-line">{h.graded>=20?<>Of {h.graded.toLocaleString('en-US')} alerts with a recorded direction in the last {data.days} days, {h.favorable.toLocaleString('en-US')} ({Math.round(h.favorable/h.graded*100)}%) moved in the alert’s direction a day later. </>:null}<Link href="/record">Track record <span aria-hidden="true">›</span></Link></p>}
