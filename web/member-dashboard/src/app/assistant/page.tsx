import {AssistantPanel} from '@/components/assistant-panel';
export default async function Page({searchParams}:{searchParams:Promise<{ticker?:string;c?:string}>}){
 const {ticker,c}=await searchParams;
 return <AssistantPanel ticker={ticker&&/^[A-Z][A-Z0-9.\-]{0,15}$/.test(ticker)?ticker:null} conversation={c&&/^[0-9a-f-]{36}$/.test(c)?c:null}/>;
}
