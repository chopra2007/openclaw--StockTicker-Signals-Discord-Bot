import {AssistantPanel} from '@/components/assistant-panel';
export default async function Page({searchParams}:{searchParams:Promise<{ticker?:string}>}){
 const {ticker}=await searchParams;
 return <AssistantPanel ticker={ticker&&/^[A-Z][A-Z0-9.\-]{0,15}$/.test(ticker)?ticker:null}/>;
}
