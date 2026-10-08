import {expect} from '@playwright/test';
import {test,join} from './helpers';

const now=Date.now()/1000;
const card=(ticker:string,direction='bullish',age=1)=>({id:ticker,ticker,direction,text:'Observed source note for '+ticker,url:null,score:72,price:10,observed_at:now-age*3600,group:null,plan:{direction:'long',entry_low:10,entry_high:12,stop:9,targets:[15],computed_at:now-3600}});
const cards=[card('ALPHA'),card('BETA','bearish',5),card('MISSING')];
async function open(page:import('@playwright/test').Page,request:import('@playwright/test').APIRequestContext){
 await join(page,request);
 await page.route('**/api/v1/setups/latest',route=>route.fulfill({json:{cards}}));
 await page.route('**/api/v1/alerts/latest',route=>route.fulfill({json:{cards:[]}}));
 await page.route('**/api/v1/market/quotes?**',route=>route.fulfill({json:{quotes:[{symbol:'ALPHA',price:42.18,change:2,change_pct:5,quote_time:now},{symbol:'BETA',price:1200,change:-20,change_pct:-2,quote_time:now}]}}));
 await page.goto('/screener');
 await expect(page.getByRole('heading',{name:'Screener',exact:true})).toBeVisible();
 await expect(page.getByText('3 of 3 symbols matched',{exact:true})).toBeVisible();
}

test('account closes outside and with Escape',async({page,request})=>{
 await open(page,request);const menu=page.locator('.member-menu');
 await menu.locator('summary').click();await expect(menu).toHaveAttribute('open','');
 await page.getByRole('heading',{name:'Screener',exact:true}).click();await expect(menu).not.toHaveAttribute('open','');
 await menu.locator('summary').click();await page.keyboard.press('Escape');await expect(menu).not.toHaveAttribute('open','');
});

test('combined universe keeps both sources and deduplicates symbols',async({page,request})=>{
 await open(page,request);
 await page.route('**/api/v1/alerts/latest',route=>route.fulfill({json:{cards:[card('ALPHA'),card('GROUP','bearish')]}}));
 await page.getByLabel('Universe',{exact:true}).selectOption('both');
 await expect(page.getByText('4 of 4 symbols matched',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Inspect ALPHA',exact:true})).toHaveCount(1);
 await expect(page.getByRole('button',{name:'Inspect GROUP',exact:true})).toBeVisible();
 await page.reload();await expect(page.getByLabel('Universe',{exact:true})).toHaveValue('both');
});

test('combined refresh denial wins over another source outage',async({page,request})=>{
 await open(page,request);await page.getByLabel('Universe',{exact:true}).selectOption('both');
 await expect(page.getByRole('button',{name:'Inspect ALPHA',exact:true})).toBeVisible();
 let release:()=>void=()=>{};const gate=new Promise<void>(resolve=>{release=resolve;});
 await page.route('**/api/v1/alerts/latest',async route=>{await gate;await route.fulfill({status:403,json:{}});});
 await page.route('**/api/v1/setups/latest',async route=>{await route.fulfill({status:503,json:{}});release();});
 await page.getByRole('button',{name:'Refresh data',exact:true}).click();
 await expect(page.getByRole('button',{name:'Inspect ALPHA',exact:true})).toHaveCount(0);
});

test('cached setup chart and dated original source image need no research request',async({page,request})=>{
 await open(page,request);const writes:string[]=[];page.on('request',r=>{if(r.method()==='POST')writes.push(r.url());});
 await page.route('**/api/v1/setups/latest',route=>route.fulfill({json:{cards:[{...cards[0],chart:{daily:[[now-86400,10],[now,12]],intraday:[]},chart_at:now,company:'A long company name',group:{analysts:2,span:'5 min',calls:[{analyst:'chart_author',view:'unclear',reason:'Chart attached; directional intent not stated.',posted_at:now-120,observed_at:now-60,url:'https://x.com/chart_author/status/123',image_urls:['https://pbs.twimg.com/media/chart.png']}]}}]}}));
 await page.route('https://pbs.twimg.com/media/chart.png',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'}));
 await page.getByRole('button',{name:'Refresh data',exact:true}).click();await expect(page.getByText('1 of 1 symbols matched',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Inspect ALPHA',exact:true}).click();const panel=page.getByRole('dialog');
 await expect(panel).toContainText('Cached setup daily closes');await expect(panel).toContainText('Posted');
 await expect(panel.getByRole('img',{name:'Original chart attached by @chart_author'})).toBeVisible();
 await expect(panel.getByRole('link',{name:'Original post'})).toHaveAttribute('href','https://x.com/chart_author/status/123');
 expect(writes).toEqual([]);
});
test('screen, explain and inspect without spending or losing criteria',async({page,request})=>{
 await open(page,request);const writes:string[]=[];page.on('request',r=>{if(r.method()==='POST')writes.push(r.url());});
 await page.getByLabel('Minimum price ($)').fill('10');await page.getByLabel('Maximum price ($)').fill('100');
 await page.getByRole('button',{name:'Apply filters',exact:true}).click();await expect(page.getByText('1 of 3 symbols matched',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Inspect ALPHA',exact:true}).click();const drawer=page.getByRole('dialog');
 await expect(drawer.getByRole('heading',{name:'Why it matched'})).toBeVisible();await expect(drawer).toContainText('$42.18');await expect(drawer).toContainText('$10.00–$100.00');
 await page.keyboard.press('Escape');await expect(drawer).toHaveCount(0);await expect(page.getByRole('button',{name:'Inspect ALPHA',exact:true})).toBeFocused();
 await expect(page.getByLabel('Maximum price ($)')).toHaveValue('100');expect(writes).toEqual([]);
});
test('invalid ranges, zero matches and unavailable input are distinct',async({page,request})=>{
 await open(page,request);await page.getByLabel('Minimum price ($)').fill('100');await page.getByLabel('Maximum price ($)').fill('10');await page.getByRole('button',{name:'Apply filters',exact:true}).click();
 await expect(page.locator('p[role=alert]')).toContainText('Minimum price must not exceed maximum price');await expect(page.getByText('3 of 3 symbols matched',{exact:true})).toBeVisible();
 await page.getByLabel('Minimum price ($)').fill('1');await page.getByLabel('Maximum price ($)').fill('2');await page.getByRole('button',{name:'Apply filters',exact:true}).click();
 await expect(page.getByText('No stocks meet these conditions.')).toBeVisible();await expect(page.getByText('1 symbol lacks data needed for these filters.')).toBeVisible();
 await page.getByRole('button',{name:'Reset filters',exact:true}).click();await expect(page.getByText('3 of 3 symbols matched',{exact:true})).toBeVisible();
});
test('sorting, columns, named screens and preferences survive reload',async({page,request})=>{
 await open(page,request);await page.getByRole('button',{name:'Sort by price',exact:true}).click();
 await expect(page.locator('tbody tr').first()).toContainText('ALPHA');await page.getByRole('button',{name:'Sort by price',exact:true}).click();await expect(page.locator('tbody tr').first()).toContainText('BETA');await expect(page.locator('tbody tr').last()).toContainText('MISSING');
 await page.getByLabel('Maximum price ($)').fill('100');await page.getByRole('button',{name:'Apply filters',exact:true}).click();
 await page.getByText('Save current screen',{exact:true}).click();await page.getByLabel('Screen name').fill('Affordable');await page.getByRole('button',{name:'Save screen',exact:true}).click();
 await page.getByRole('button',{name:'Columns',exact:true}).click();await page.getByLabel('Show day change').uncheck();
 await page.reload();await expect(page.getByText('1 of 3 symbols matched',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Sort by day change',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Reset filters',exact:true}).click();await page.getByLabel('Saved screens').selectOption('Affordable');await expect(page.getByText('1 of 3 symbols matched',{exact:true})).toBeVisible();
});
test('refresh failure preserves usable results with an explicit warning',async({page,request})=>{
 await open(page,request);await page.route('**/api/v1/setups/latest',route=>route.fulfill({status:503,json:{}}));await page.getByRole('button',{name:'Refresh data',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'Refresh failed'})).toBeVisible();await expect(page.getByText('3 of 3 symbols matched',{exact:true})).toBeVisible();
});
for(const width of [390,768,1440])test(`screener keyboard and formatting at ${width}`,async({page,request})=>{
 await page.setViewportSize({width,height:900});await open(page,request);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.getByRole('button',{name:'Inspect BETA',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('$1,200.00');
 await page.keyboard.press('Tab');await expect(page.getByRole('dialog')).toBeVisible();await page.screenshot({path:`.e2e/screenshots/screener-${width}.png`,fullPage:true});
 await page.keyboard.press('Escape');await expect(page.getByRole('button',{name:'Inspect BETA',exact:true})).toBeFocused();
});
test('source withdrawal closes inspection even when the subsequent quote request fails',async({page,request})=>{
 await page.clock.install();await open(page,request);await page.getByRole('button',{name:'Inspect ALPHA',exact:true}).click();
 await page.route('**/api/v1/setups/latest',route=>route.fulfill({json:{cards:[cards[1]]}}));
 await page.route('**/api/v1/market/quotes?**',route=>route.fulfill({status:503,json:{}}));
 await page.clock.fastForward(30001);await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.getByRole('button',{name:'Inspect ALPHA',exact:true})).toHaveCount(0);
});
test('quote source denial clears price inside an open inspection',async({page,request})=>{
 await page.clock.install();await open(page,request);await page.getByRole('button',{name:'Inspect ALPHA',exact:true}).click();
 await page.route('**/api/v1/market/quotes?**',route=>route.fulfill({json:{quotes:[]}}));await page.clock.fastForward(30001);
 await expect(page.getByRole('dialog')).not.toContainText('$42.18');
});
test('watchlist polling reconciles changes from another browser',async({page,request})=>{
 await page.clock.install();let watched=false;
 await page.route('**/api/v1/watchlist',route=>route.fulfill({json:{items:watched?[{symbol:'ALPHA',added_at:now,new_alert:false}]:[],limit:50}}));
 await open(page,request);await page.getByLabel('Only symbols on my watchlist').check();await page.getByRole('button',{name:'Apply filters',exact:true}).click();await expect(page.getByText('0 of 3 symbols matched',{exact:true})).toBeVisible();
 watched=true;await page.clock.fastForward(60001);await expect(page.getByText('1 of 3 symbols matched',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Remove ALPHA from watchlist'})).toBeVisible();
});
test('combined chips, column order, density, saved deletion and universe changes',async({page,request})=>{
 await open(page,request);await page.getByLabel('Maximum price ($)').fill('100');await page.getByRole('combobox',{name:'Source direction',exact:true}).selectOption('bullish');await page.getByRole('button',{name:'Apply filters',exact:true}).click();
 await page.getByRole('button',{name:'Remove Price condition',exact:true}).click();await expect(page.getByText('2 of 3 symbols matched',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Columns',exact:true}).click();await page.getByRole('button',{name:'Move day change left',exact:true}).click();await expect(page.locator('thead th').nth(1)).toContainText('Day change');await page.getByRole('button',{name:'Move day change right',exact:true}).click();
 await page.getByRole('combobox',{name:'Density',exact:true}).selectOption('comfortable');await expect(page.locator('main')).toHaveAttribute('data-density','comfortable');
 await page.getByText('Save current screen',{exact:true}).click();await page.getByLabel('Screen name').fill('Research');await page.getByRole('button',{name:'Save screen',exact:true}).click();await page.getByRole('button',{name:'Remove saved screen',exact:true}).click();await expect(page.getByLabel('Saved screens').locator('option')).toHaveCount(1);
 await page.getByLabel('Universe',{exact:true}).selectOption('alerts');await expect(page.getByText('No symbols are available in this source right now.')).toBeVisible();
 await page.getByLabel('Universe',{exact:true}).selectOption('setups');await expect(page.getByText('2 of 3 symbols matched',{exact:true})).toBeVisible();
});
test('watchlist add and remove update an active screen and failures are visible',async({page,request})=>{
 let watched=false,fail=false;
 await page.route('**/api/v1/watchlist',route=>route.fulfill({json:{items:watched?[{symbol:'ALPHA',added_at:now,new_alert:false}]:[],limit:50}}));
 await page.route('**/api/v1/watchlist/ALPHA',route=>{if(fail)return route.fulfill({status:503,json:{}});watched=route.request().method()==='PUT';return route.fulfill(route.request().method()==='DELETE'?{status:204}:{json:{items:[{symbol:'ALPHA',added_at:now,new_alert:false}],limit:50}});});
 await open(page,request);await page.getByRole('button',{name:'Add ALPHA to watchlist',exact:true}).click();await expect(page.getByRole('button',{name:'Remove ALPHA from watchlist',exact:true})).toBeVisible();
 await page.getByLabel('Only symbols on my watchlist').check();await page.getByRole('button',{name:'Apply filters',exact:true}).click();await expect(page.getByText('1 of 3 symbols matched',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Inspect ALPHA',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'Remove ALPHA from watchlist',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.getByText('0 of 3 symbols matched',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Reset filters',exact:true}).click();fail=true;await page.getByRole('button',{name:'Add ALPHA to watchlist',exact:true}).click();await expect(page.locator('.watch-error')).toContainText('Unable to load');
});
test('mobile filters are explicit and results retain priority, route heading receives focus',async({page,request})=>{
 await page.setViewportSize({width:390,height:844});await open(page,request);await expect(page.getByRole('heading',{name:'Screener',exact:true})).toBeFocused();
 await expect(page.getByRole('button',{name:'Inspect ALPHA',exact:true})).toBeInViewport();await page.getByRole('button',{name:/Edit filters/}).click();
 await page.getByLabel('Maximum price ($)').fill('100');await page.getByRole('button',{name:'Apply filters',exact:true}).click();await expect(page.getByText('1 of 3 symbols matched',{exact:true})).toBeVisible();
});
for(const theme of ['light','dark'] as const)test(`drawer resize, focus confinement and ${theme} theme`,async({page,request})=>{
 await page.emulateMedia({colorScheme:theme});await open(page,request);const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.getByRole('button',{name:'Inspect ALPHA',exact:true}).click();await expect(page.getByRole('button',{name:'Close inspection',exact:true})).toBeFocused();
 await page.keyboard.press('Shift+Tab');expect(await page.evaluate(()=>!!document.activeElement?.closest('dialog'))).toBe(true);
 await page.setViewportSize({width:390,height:600});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:`.e2e/screenshots/screener-${theme}-mobile.png`,fullPage:true});await page.keyboard.press('Escape');
 // A 720px layout exercises 200% reflow of a 1440px desktop. CSS zoom
 // does not change media query breakpoints like actual browser zoom does.
 await page.setViewportSize({width:720,height:500});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);expect(errors).toEqual([]);
});

test('saved chart ranges, pointer readout and textual data reuse only authorized GETs',async({page,request})=>{
 const daily=Array.from({length:25},(_,i)=>[now-(24-i)*86400,40+i/10]);
 const intraday=Array.from({length:8},(_,i)=>[now-(7-i)*3600,40+i/4]);
 const ref={id:'saved_alpha',ticker:'ALPHA',created_at:now-600};
 const report={...ref,version:1,saved_at:now-600,finalized:true,availability:'available',annotations:{},sections:{analysis:{section:'analysis',status:'completed',job_id:null,result_id:'result_alpha',observed_at:now-600,computed_at:now-600,valid_until:now+600,stale:false,analysis_version:'fixture',evidence:[],message:null,attributions:[],delay_seconds:0,payload:{kind:'analysis',summary:'Synthetic research',direction:'bullish',score:null,catalysts:[],conflicts:[],levels:[],risk_metrics:[],context_metrics:[],company:'A deliberately long synthetic company name for drawer formatting validation',quote:{price:42.18,change:2,change_pct:5,previous_close:40},chart:{daily,intraday}}}}};
 await page.route('**/api/v1/reports?limit=100',r=>r.fulfill({json:{items:[ref],cursor:null}}));
 await page.route('**/api/v1/reports/saved_alpha',r=>r.fulfill({json:report}));
 await open(page,request);const writes:string[]=[];page.on('request',r=>{if(r.method()==='POST')writes.push(r.url());});
 await page.getByRole('button',{name:'Inspect ALPHA',exact:true}).click();const dialog=page.getByRole('dialog');
 await expect(dialog.getByRole('group',{name:'Chart range'})).toBeVisible();
 for(const range of ['1D','5D','1M','6M','1Y']){await dialog.getByRole('button',{name:range,exact:true}).click();await expect(dialog.getByRole('button',{name:range,exact:true})).toHaveAttribute('aria-pressed','true');}
 const chart=dialog.getByRole('img');await chart.hover();await expect(dialog.locator('.rp-when')).toBeVisible();await dialog.getByRole('heading',{name:'Why it matched'}).hover();
 await dialog.getByText('Chart data (daily closes)',{exact:true}).click();await expect(dialog.locator('.chart-data tbody tr')).toHaveCount(25);expect(writes).toEqual([]);
});
