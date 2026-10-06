import {expect} from '@playwright/test';
import {test,join,research} from './helpers';
import {formatPacific,formatExpiry} from '../src/lib/time';
import {researchSchema,feedSchema} from '../src/lib/contracts';
test('Pacific spring and autumn clock transitions and date-only expiry',()=>{
 expect(formatPacific(Date.parse('2026-03-08T09:59:00Z')/1000)).toContain('1:59:00 AM PST');
 expect(formatPacific(Date.parse('2026-03-08T10:00:00Z')/1000)).toContain('3:00:00 AM PDT');
 expect(formatPacific(Date.parse('2026-11-01T08:59:00Z')/1000)).toContain('1:59:00 AM PDT');
 expect(formatPacific(Date.parse('2026-11-01T09:00:00Z')/1000)).toContain('1:00:00 AM PST');
 expect(formatExpiry('2026-10-09')).toBe('2026-10-09');expect(formatPacific(null)).toBe('Unavailable');
});
test('strict public decoders reject extra private fields and invented sequence',()=>{
 expect(researchSchema.safeParse({id:'a',report_id:'b',ticker:'SPY',sections:{},lineage:{}}).success).toBe(false);
 expect(feedSchema.safeParse({records:[{operation:'delete',id:'a',sequence:1}],cursor:'opaque',snapshot:true,has_more:false,sources:[]}).success).toBe(false);
});
for(const width of [390,768,1440])test(`keyboard, semantic status and layout at ${width}`,async({page,request})=>{
 await page.setViewportSize({width,height:1000});await join(page,request);
 await expect(page.getByRole('heading',{level:1})).toBeFocused();
 await page.keyboard.press('Tab');await expect(page.getByRole('link',{name:'SPY',exact:true}).first()).toBeFocused();
 await page.screenshot({path:`.e2e/screenshots/home-${width}.png`,fullPage:true});
 await research(page);await expect(page.getByTestId('em_weekly-status')).toHaveText('Completed');
 await expect(page.getByRole('heading',{level:1})).toBeFocused();
 await expect(page.getByAltText('Daily expected move chart; numerical ranges follow')).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:`.e2e/screenshots/report-${width}.png`,fullPage:true});
 if(width===1440){await page.evaluate(()=>{document.documentElement.style.zoom='2';});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:'.e2e/screenshots/report-200-percent.png',fullPage:true});}
});
