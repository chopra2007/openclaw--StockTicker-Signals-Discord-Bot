import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import type {SectionResult} from '../src/lib/contracts';

type SecPayload=Extract<NonNullable<SectionResult['payload']>,{kind:'sec'}>;
test('routine filings are hidden and distinct buyer/seller totals and trade numbers are clear',async({page})=>{
 const filings=Array.from({length:10},(_,i)=>({accession:`filing-${i}`,form:'4',filed_at:1700000000+i*86400,title:'Insider trade',
  summary:i===8?'Buyer (Director) bought 100 shares for $2M on the open market.':i===7?'Seller (Director) sold 41,674 shares for $20.8M on the open market.':i===9?'Example (Director): routine gift, not an open-market trade.':'Example (Director): routine award/grant, not an open-market trade.',
  url:`https://www.sec.gov/Archives/example-${i}`,detail_status:'ok' as const}));
 const p:SecPayload={kind:'sec',coverage:'complete',filings,insiders:filings.map((f,i)=>({accession:f.accession,summary:'Reported.',
  conviction:i===8||i===7?'conviction':'routine',transaction_value:i===8||i===7?{value:i===8?2e6:20.8e6,unit:'USD',method:'shares times price'}:null})),warning:null};
 await page.setContent(execFileSync(process.execPath,['e2e/render-sec.cjs'],{input:JSON.stringify(p),encoding:'utf8'}));
 await page.addStyleTag({content:readFileSync('src/app/globals.css','utf8').replace('@import "tailwindcss";','')});
 const rows=page.locator('.filings li');
 await expect(rows).toHaveCount(2);
 expect(await rows.locator('a').evaluateAll(links=>links.map(a=>a.getAttribute('href')))).toEqual(
  [8,7].map(i=>`https://www.sec.gov/Archives/example-${i}`));
 await expect(rows.nth(0).locator('.filing-side.buy')).toHaveCSS('color','rgb(48, 209, 88)');
 await expect(rows.nth(1).locator('.filing-side.sell')).toHaveCSS('color','rgb(255, 105, 97)');
 await expect(page.locator('.rp-insider-line')).toHaveText('1 insider bought $2M; 1 insider sold $20.8M in the last 90 days.');
 await expect(rows.nth(1).locator('strong')).toHaveText(['41,674','$20.8M']);
 await expect(page.getByRole('button')).toHaveCount(0);
});

test('desktop text permits five lines and mobile has an expand-all control',async({page})=>{
 const result={payload:{kind:'analysis',summary:'**TL;DR:** Example.\n\n## Catalysts\n- **Event:** '+('Company announcement explains the event and its consequences. '.repeat(12))+'\n\n## Outlook\n- **Next year:** Example.'},evidence:[]};
 await page.setViewportSize({width:1200,height:900});
 await page.setContent(execFileSync(process.execPath,['e2e/render-sec.cjs'],{input:JSON.stringify({component:'call',result}),encoding:'utf8'}));
 await page.addStyleTag({content:readFileSync('src/app/globals.css','utf8').replace('@import "tailwindcss";','')});
 await expect(page.locator('.rp-clamp').first()).toHaveCSS('-webkit-line-clamp','5');
 await expect(page.getByRole('button',{name:'Expand all'})).toBeHidden();
 await page.setViewportSize({width:390,height:844});
 await expect(page.locator('.rp-clamp').first()).toHaveCSS('-webkit-line-clamp','2');
 await expect(page.getByRole('button',{name:'Expand all'})).toBeVisible();
});

test('repeat filings count one seller and mixed transactions preserve each amount',async({page})=>{
 const metric=(value:number)=>({value,unit:'USD',method:'shares times price'});
 const p:SecPayload={kind:'sec',coverage:'complete',warning:null,filings:[0,1].map(i=>({accession:`f-${i}`,form:'4',filed_at:1700000000+i,title:'Insider trade',summary:'Seller (Director) sold 100 shares for $1M on the open market.',url:null,detail_status:'ok'})),
 insiders:[0,1].map(i=>({accession:`f-${i}`,summary:'Reported.',conviction:'conviction',reporter_name:'Seller',transaction_value:metric(1e6),sold_value:metric(1e6),bought_value:null}))};
 const render=()=>page.setContent(execFileSync(process.execPath,['e2e/render-sec.cjs'],{input:JSON.stringify(p),encoding:'utf8'}));
 await render();
 await expect(page.locator('.rp-insider-line')).toHaveText('1 insider sold $2M in the last 90 days.');
 p.insiders[0].bought_value=metric(3e6);
 await render();
 await expect(page.locator('.rp-insider-line')).toHaveText('1 insider bought $3M; 1 insider sold $2M in the last 90 days.');
});

test('saved news excludes option quote pages and stories older than 30 days',async({page})=>{
 const now=Date.now()/1000;
 const evidence=['Microsoft announces a decision AI model','MSFT Oct 2026 467.500 put (MSFT261009P00467500) stock price, news, quote and history','Microsoft launches new hardware','Microsoft old headline'].map((excerpt,i)=>({id:`news-${i}`,source_id:'synthetic',source_version:'v1',observed_at:now-(i===2?20:i===3?31:1)*86400,url:'https://example.com/article',excerpt,research_only:true}));
 const result={payload:{kind:'analysis',summary:''},evidence};
 await page.setContent(execFileSync(process.execPath,['e2e/render-sec.cjs'],{input:JSON.stringify({component:'news',result}),encoding:'utf8'}));
 await expect(page.locator('.rp-news li')).toHaveCount(2);
 await expect(page.locator('.rp-news')).toContainText('decision AI model');
 await expect(page.locator('.rp-news')).toContainText('new hardware');
});
