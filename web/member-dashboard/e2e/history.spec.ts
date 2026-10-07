import {expect} from '@playwright/test';
import {test,join,research,control} from './helpers';

test('history: pending saved report refreshes promptly without submitting work',async({page,request})=>{
 await join(page,request);await research(page);
 for(const name of ['analysis','options','em_daily','em_weekly','sec'])await expect(page.getByTestId(name+'-status')).toHaveText('Completed');
 await page.clock.install();let reads=0;const posts:string[]=[];
 await page.route('**/api/v1/reports/*',async route=>{
  const response=await route.fetch();const data=await response.json();reads++;
  if(reads===1){data.finalized=false;data.availability='pending';data.sections.analysis={...data.sections.analysis,status:'running',payload:null};}
  await route.fulfill({response,json:data});
 });
 page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
 await page.goto('/history');await page.getByRole('button',{name:/Open saved report/}).first().click();
 await expect(page.getByText(/Not finalized/)).toBeVisible();await expect(page.getByTestId('analysis-status')).toHaveText('Running');
 await page.clock.fastForward(1001);await expect.poll(()=>reads).toBe(2);
 await expect(page.getByTestId('analysis-status')).toHaveText('Completed');await expect(page.getByText(/· Finished/)).toBeVisible();
 expect(posts).toEqual([]);
});

test('history: reopen original, delete owned report and clear selected content',async({page,request})=>{
 await join(page,request);await research(page);
 for(const name of ['analysis','options','em_daily','em_weekly','sec'])await expect(page.getByTestId(name+'-status')).toHaveText('Completed');
 const original=await page.locator('#analysis').textContent();const stats=await control(request,{action:'stats'});
 await page.getByRole('link',{name:'History',exact:true}).click();await expect(page.getByRole('heading',{name:'History',exact:true,level:1})).toBeVisible();
 await page.getByRole('button',{name:/Open saved report/}).first().click();await expect(page.getByTestId('analysis-status')).toHaveText('Completed');
 expect(await page.locator('#analysis').textContent()).toBe(original);expect(await control(request,{action:'stats'})).toEqual(stats);
 await expect(page.getByAltText('Daily expected move chart; numerical ranges follow')).toBeVisible();
 for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();if(width===1440){const content=await page.locator('.report-column').boundingBox(),sidebar=await page.locator('.report-sidebar').boundingBox();expect(content!.width).toBeGreaterThan(sidebar!.width);}await page.screenshot({path:`.e2e/screenshots/history-${width}.png`,fullPage:true});}
 await page.getByRole('button',{name:'Delete report',exact:true}).click();await page.getByRole('button',{name:'Yes, delete',exact:true}).click();
 await expect(page.getByText(/^No saved reports yet\./)).toBeVisible();await expect(page.locator('#analysis')).toHaveCount(0);await expect(page.locator('img')).toHaveCount(0);
 await page.reload();await expect(page.getByText(/^No saved reports yet\./)).toBeVisible();
});

test('history: active access refresh withdraws sections and pauses while hidden',async({page,request})=>{
 await page.clock.install();await join(page,request);await research(page);await expect(page.getByTestId('em_weekly-status')).toHaveText('Completed');
 await page.goto('/history');await page.getByRole('button',{name:/Open saved report/}).first().click();await expect(page.getByTestId('analysis-status')).toHaveText('Completed');
 let reads=0;page.on('request',r=>{if(r.method()==='GET'&&/\/api\/v1\/reports\//.test(r.url()))reads++;});
 await page.clock.fastForward(15001);await expect.poll(()=>reads).toBe(1);
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});
 await page.clock.fastForward(30000);expect(reads).toBe(1);
 await control(request,{action:'grant',allowed:false});
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});window.dispatchEvent(new Event('focus'));});
 await expect(page.locator('#analysis')).not.toContainText('Synthetic breadth');await expect(page.locator('img')).toHaveCount(0);
 await control(request,{action:'grant',allowed:true});
});

test('history: private conversation reopen and delete without starting assistant',async({page,request})=>{
 const username=await join(page,request);await control(request,{action:'conversation',username});
 const posts:string[]=[];page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
 await page.goto('/history');await page.getByRole('button',{name:'Chats',exact:true}).click();
 await page.getByRole('button',{name:/Open conversation/}).click();await expect(page.getByText('My saved question')).toBeVisible();
 await page.getByRole('button',{name:'Delete chat',exact:true}).click();await page.getByRole('button',{name:'Yes, delete',exact:true}).click();await expect(page.getByText(/^No chats yet\./)).toBeVisible();
 await expect(page.getByText('My saved question')).toHaveCount(0);expect(posts).toEqual([]);
});

test('history: cross-account IDs and deleted reports fail closed',async({page,request,browser})=>{
 await join(page,request);await research(page);await expect(page.getByTestId('em_weekly-status')).toHaveText('Completed');
 const reports=await page.request.get('/api/v1/reports');expect(reports.status()).toBe(200);const id=(await reports.json()).items[0].id;
 const other=await browser.newContext({ignoreHTTPSErrors:true,baseURL:'https://localhost:3443'});const otherPage=await other.newPage();
 await join(otherPage,request);expect((await other.request.get('/api/v1/reports/'+id)).status()).toBe(404);
 await page.goto('/history');await page.getByRole('button',{name:/Open saved report/}).first().click();await expect(page.getByTestId('analysis-status')).toHaveText('Completed');
 await page.getByRole('button',{name:'Delete report',exact:true}).click();await page.getByRole('button',{name:'Yes, delete',exact:true}).click();await expect(page.getByText(/^No saved reports yet\./)).toBeVisible();
 expect((await page.request.get('/api/v1/reports/'+id)).status()).toBe(404);await other.close();
});
