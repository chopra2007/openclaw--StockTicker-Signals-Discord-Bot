import {test,expect} from '@playwright/test';
import {control,join,research,password} from './helpers';
test('review: abandoned delayed refresh cannot navigate back and retains server charge',async({page,request})=>{
 await join(page,request);await research(page);await expect(page.getByTestId('analysis-status')).toHaveText('Completed');
 await control(request,{action:'refresh_ready',ticker:'SPY'});const before=await control(request,{action:'stats'});
 let release:()=>void=()=>{};const gate=new Promise<void>(resolve=>{release=resolve;});
 let received:()=>void=()=>{};const accepted=new Promise<void>(resolve=>{received=resolve;});
 let delivered:()=>void=()=>{};const done=new Promise<void>(resolve=>{delivered=resolve;});
 await page.route('**/api/v1/research',async route=>{
   const response=await route.fetch();expect(response.status()).toBe(200);received();await gate;
   try{await route.fulfill({response});}catch{/* The departed browser may already have aborted. */}finally{delivered();}
 });
 await page.getByRole('button',{name:'Refresh research'}).click();await accepted;
 await page.getByRole('link',{name:'Overview',exact:true}).click();await expect(page.getByRole('heading',{name:'Your market workspace'})).toBeVisible();
 release();await done;
 // Allow the released response and any resulting router transition to settle.
 await page.waitForTimeout(500);await expect(page).toHaveURL('https://localhost:3443/');
 const after=await control(request,{action:'stats'});expect(after.jobs).toBe(before.jobs+5);expect(after.compute_charges).toBe(before.compute_charges+1);
});
test('review: session transport failure offers retry and recovers',async({page,request})=>{
 await join(page,request);let fail=true;await page.route('**/api/v1/me',async route=>{if(fail)await route.abort('connectionfailed');else await route.continue();});
 await page.goto('/');await expect(page.locator('p[role=alert]')).toContainText('Unable to check your session');
 await expect(page.getByRole('button',{name:'Try again'})).toBeVisible();await expect(page.getByText('Checking your session…')).toHaveCount(0);
 fail=false;await page.getByRole('button',{name:'Try again'}).click();await expect(page.getByRole('heading',{name:'Your market workspace'})).toBeVisible();
});
test('invite fragment is removed before any fetch, secure login and reset',async({page,request,context})=>{
  const hashes:string[]=[];await page.addInitScript(()=>{const native=window.fetch;window.fetch=(...args)=>{(window as unknown as {fetchHashes:string[]}).fetchHashes??=[];(window as unknown as {fetchHashes:string[]}).fetchHashes.push(location.hash);return native(...args);};});
  const username=await join(page,request);hashes.push(...await page.evaluate(()=>(window as unknown as {fetchHashes:string[]}).fetchHashes));expect(hashes.every(x=>x==='')).toBeTruthy();
  const cookie=(await context.cookies()).find(x=>x.name==='__Host-member_session');expect(cookie).toMatchObject({secure:true,httpOnly:true,sameSite:'Lax',path:'/'});
  const {token}=await control(request,{action:'reset',username});await page.goto('/reset#'+token);await page.getByLabel('Password',{exact:true}).fill(password+' new');await page.getByRole('button',{name:'Reset password'}).click();await expect(page.getByRole('heading',{name:'Sign in'})).toBeVisible();
  expect(await page.evaluate(()=>Object.keys(localStorage).length+Object.keys(sessionStorage).length)).toBe(0);
});
test('one search runs sections independently; cached result, owned chart and explicit refresh',async({page,request})=>{
  await join(page,request);let posts=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/v1/research'))posts++;});
  await research(page);await expect(page.getByRole('heading',{name:'SEC Filings',exact:true})).toBeVisible();
  await expect(page.getByTestId('em_weekly-status')).toHaveText('Completed');expect(posts).toBe(1);
  await expect(page.getByRole('heading',{name:'Daily Expected Move',exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'Weekly Expected Move',exact:true})).toBeVisible();
  await expect(page.getByAltText('Daily expected move chart; numerical ranges follow')).toBeVisible();
  await expect(page.getByText('Synthetic Exchange · demonstration data').first()).toBeVisible();
  await expect(page.getByText('2026-10-09',{exact:false}).first()).toBeVisible();
  expect(await page.evaluate(()=>typeof (window as unknown as {unsafe:unknown}).unsafe)).toBe('undefined');
  const stats=await control(request,{action:'stats'});await research(page);await expect(page.getByTestId('analysis-status')).toHaveText('Completed');expect(await control(request,{action:'stats'})).toEqual(stats);
  await page.getByRole('button',{name:'Refresh research'}).click();await expect(page.locator('p[role=alert]')).toContainText('try again later');
});
test('failure is independent and invalid or unknown symbols create no work',async({page,request})=>{
  await join(page,request);await research(page,'QQQ');await expect(page.getByTestId('options-status')).toHaveText('Failed');await expect(page.getByTestId('em_weekly-status')).toHaveText('Completed');
  const stats=await control(request,{action:'stats'});for(const ticker of ['BAD!','ZZZZ']){await page.getByRole('searchbox',{name:'Ticker'}).fill(ticker);await page.getByRole('button',{name:'Research ticker'}).click();await expect(page.locator('p[role=alert]')).toContainText('Invalid or unsupported ticker');}expect(await control(request,{action:'stats'})).toEqual(stats);
});
test('direct ticker routes never start research or assistant and private results stay private',async({page,request})=>{
  await page.goto('/ticker/SPY?request=unknown');await expect(page.getByRole('heading',{name:'Sign in'})).toBeVisible();await join(page,request);
  const stats=await control(request,{action:'stats'});const unsafe:string[]=[];page.on('request',r=>{if(r.method()==='POST')unsafe.push(r.url());});
  await page.goto('/ticker/SPY');await expect(page.getByText('Use Research ticker to start all enabled sections.')).toBeVisible();expect(unsafe).toEqual([]);expect(await control(request,{action:'stats'})).toEqual(stats);
  await page.goto('/ticker/SPY?request=not-owned');await expect(page.locator('p[role=alert]')).toContainText('not found');
});
test('terminal access checks withdraw source payloads and charts; expiry clears everything',async({page,request})=>{
  await join(page,request);await research(page);await expect(page.getByTestId('em_weekly-status')).toHaveText('Completed');
  const stats=await control(request,{action:'stats'});await control(request,{action:'grant',allowed:false});await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await expect(page.getByText('Synthetic breadth is improving',{exact:false})).toHaveCount(0);await expect(page.locator('img')).toHaveCount(0);expect(await control(request,{action:'stats'})).toEqual(stats);
  await control(request,{action:'grant',allowed:true});await control(request,{action:'expire'});await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.getByRole('heading',{name:'Sign in'})).toBeVisible();expect(await page.locator('main').textContent()).not.toContain('Synthetic breadth');
});
test('terminal job polling stops, active access continues and hidden tabs pause',async({page,request})=>{
 await page.clock.install();
 await join(page,request);await research(page,'AAPL');await expect(page.getByTestId('analysis-status')).toHaveText('Completed');await expect(page.getByTestId('em_weekly-status')).toHaveText('Completed');
 let reads=0;page.on('request',r=>{if(r.method()==='GET'&&r.url().includes('/api/v1/research/'))reads++;});
 await page.clock.fastForward(2000);expect(reads).toBe(0);await page.clock.fastForward(13001);await expect.poll(()=>reads).toBe(1);
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});await page.clock.fastForward(30000);expect(reads).toBe(1);
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'));});await expect.poll(()=>reads).toBe(2);
});
test('cached POST result appears immediately while access GET is in flight',async({page,request})=>{
 await join(page,request);await research(page);await expect(page.getByTestId('analysis-status')).toHaveText('Completed');await page.goto('/');
 let release:()=>void=()=>{};const gate=new Promise<void>(resolve=>{release=resolve;});
 await page.route('**/api/v1/research/*',async route=>{await gate;await route.continue();});
 try{await research(page);await expect(page.getByTestId('analysis-status')).toHaveText('Completed',{timeout:1000});}finally{release();}
});
test('feed empty delta updates freshness and an invalid opaque cursor resets snapshot',async({page,request})=>{
 await control(request,{action:'freshness',fresh:true});await join(page,request);await expect(page.locator('#feed article').first()).toBeVisible();
 await control(request,{action:'freshness',fresh:false});await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.locator('#feed article').first()).toContainText('Stale');
 let corrupted=false;await page.route('**/api/v1/feed?*',async route=>{if(!corrupted){corrupted=true;await route.continue({url:'https://localhost:3443/api/v1/feed?cursor=tampered'});}else await route.continue();});
 let reset=0;page.on('response',r=>{if(r.url().includes('/api/v1/feed')&&r.status()===409)reset++;});await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect.poll(()=>reset).toBe(1);await expect(page.locator('#feed article').first()).toBeVisible();
});
test('CSRF failure does not replay a write and disabled feed clears both API and navigation',async({page,request})=>{
 await join(page,request);const before=await control(request,{action:'stats'});let writes=0;
 await page.route('**/api/v1/research',async route=>{writes++;await route.continue({headers:{...route.request().headers(),'x-csrf-token':'invalid'}});});
 await page.getByRole('searchbox',{name:'Ticker'}).fill('SPY');await page.getByRole('button',{name:'Research ticker'}).click();await expect(page.locator('p[role=alert]')).toContainText('Access is unavailable');expect(writes).toBe(1);expect(await control(request,{action:'stats'})).toEqual(before);
 await control(request,{action:'feature',feature:'feed',enabled:false});expect((await page.context().request.get('/api/v1/feed')).status()).toBe(403);await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.locator('#feed')).toHaveCount(0);await expect(page.getByRole('link',{name:'Research feed',exact:true})).toHaveCount(0);await control(request,{action:'feature',feature:'feed',enabled:true});
});
test('feature loss clears sections and navigation; feed revision and tombstone are applied',async({page,request})=>{
  await join(page,request);await expect(page.locator('#feed').getByText('Synthetic research: momentum is improving.').first()).toBeVisible();
  await control(request,{action:'publish',version:'v2',excerpt:'Corrected synthetic research.'});await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.locator('#feed').getByText('Corrected synthetic research.').first()).toBeVisible();await expect(page.getByText('Synthetic research: momentum is improving.')).toHaveCount(0);
  await research(page);await expect(page.getByTestId('sec-status')).toHaveText('Completed');await control(request,{action:'feature',feature:'sec',enabled:false});await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.getByText('SEC Filings is disabled.')).toBeVisible();await expect(page.getByText('Synthetic filing summary',{exact:false})).toHaveCount(0);
  await control(request,{action:'feature',feature:'sec',enabled:true});
  await page.goto('/');await control(request,{action:'delete'});await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.locator('#feed').getByText('Corrected synthetic research.')).toHaveCount(0);
});

test('assistant: explicit send, persisted reopen, private access and delete',async({page,request,browser})=>{
 await join(page,request);await page.getByRole('link',{name:'Market Assistant',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Market Assistant',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'New conversation'}).click();await page.getByLabel('Your question').fill('Explain SPY');
 await page.getByRole('button',{name:'Send question'}).click();
 await expect(page.getByText('Observation: synthetic momentum is improving. Interpretation: more evidence is needed.')).toBeVisible();
 const conversations=await page.request.get('/api/v1/conversations');const id=(await conversations.json()).items[0].id;
 const other=await browser.newContext({ignoreHTTPSErrors:true,baseURL:'https://localhost:3443'});await join(await other.newPage(),request);
 expect((await other.request.get('/api/v1/conversations/'+id)).status()).toBe(404);await other.close();
 await page.reload();await page.getByRole('button',{name:'Market research',exact:true}).click();
 await expect(page.getByText('Observation: synthetic momentum is improving. Interpretation: more evidence is needed.')).toBeVisible();
 for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();await page.screenshot({path:`.e2e/screenshots/assistant-${width}.png`,fullPage:true});}
 await page.getByRole('button',{name:'Delete conversation',exact:true}).click();await expect(page.getByText('Observation: synthetic momentum is improving. Interpretation: more evidence is needed.')).toHaveCount(0);
 await expect.poll(async()=>(await page.request.get('/api/v1/conversations/'+id)).status()).toBe(404);
});

test('assistant: unavailable retry and terminal access refresh without new calls',async({page,request})=>{
 await page.clock.install();await join(page,request);await control(request,{action:'assistant',enabled:false});
 await page.goto('/assistant?ticker=SPY');await expect(page.getByText('Selected ticker:')).toContainText('SPY');
 await page.getByRole('button',{name:'New conversation'}).click();await page.getByLabel('Your question').fill('Explain SPY');await page.getByRole('button',{name:'Send question'}).click();
 await expect(page.getByText('Market Assistant is unavailable.')).toBeVisible();await control(request,{action:'assistant',enabled:true});
 await page.getByRole('button',{name:'Retry question'}).click();await page.clock.fastForward(1001);
 await expect(page.getByText('Observation: synthetic momentum is improving. Interpretation: more evidence is needed.')).toBeVisible();
 const before=await control(request,{action:'stats'});await control(request,{action:'grant',allowed:false});
 await page.clock.fastForward(15001);await expect(page.getByText('Observation: synthetic momentum is improving. Interpretation: more evidence is needed.')).toHaveCount(0);
 expect(await control(request,{action:'stats'})).toEqual(before);await control(request,{action:'grant',allowed:true});
});
