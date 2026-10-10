import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import type {SectionResult} from '../src/lib/contracts';

type SecPayload=Extract<NonNullable<SectionResult['payload']>,{kind:'sec'}>;
test('collapsed filings include routine entries newest first and show buy/sell colors',async({page})=>{
 const filings=Array.from({length:10},(_,i)=>({accession:`filing-${i}`,form:'4',filed_at:1700000000+i*86400,title:'Insider trade',
  summary:i===8?'Example (Director) bought 100 shares on the open market.':i===7?'Example (Director) sold 100 shares on the open market.':'Example (Director): routine award/grant, not an open-market trade.',
  url:`https://www.sec.gov/Archives/example-${i}`,detail_status:'ok' as const}));
 const p:SecPayload={kind:'sec',coverage:'complete',filings,insiders:filings.map((f,i)=>({accession:f.accession,summary:'Reported.',
  conviction:i===8||i===7?'conviction':'routine',transaction_value:null})),warning:null};
 await page.setContent(execFileSync(process.execPath,['e2e/render-sec.cjs'],{input:JSON.stringify(p),encoding:'utf8'}));
 await page.addStyleTag({content:readFileSync('src/app/globals.css','utf8').replace('@import "tailwindcss";','')});
 const rows=page.locator('.filings li');
 await expect(rows).toHaveCount(8);
 expect(await rows.locator('a').evaluateAll(links=>links.map(a=>a.getAttribute('href')))).toEqual(
  [9,8,7,6,5,4,3,2].map(i=>`https://www.sec.gov/Archives/example-${i}`));
 await expect(rows.nth(1).locator('.filing-side.buy')).toHaveText('Buy');
 await expect(rows.nth(2).locator('.filing-side.sell')).toHaveText('Sell');
 await expect(rows.nth(1).locator('.filing-side.buy')).toHaveCSS('color','rgb(48, 209, 88)');
 await expect(rows.nth(2).locator('.filing-side.sell')).toHaveCSS('color','rgb(255, 105, 97)');
 await expect(rows.nth(0).locator('.filing-side')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Show all 10'})).toBeVisible();
});
