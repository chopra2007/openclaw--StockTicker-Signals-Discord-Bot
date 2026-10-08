import {expect} from '@playwright/test';
import {test,join} from './helpers';
test('bearish rise is adverse and missing horizons explain their state on mobile',async({page,request})=>{
 await page.setViewportSize({width:390,height:844});await join(page,request);
 const stamp=Date.now()/1000-86400;
 await page.route('**/api/v1/record',route=>route.fulfill({json:{total:1,days:90,horizons:[],recent:[{ticker:'MU',alerted_at:stamp,price:100,closed_1h:false,direction:'bearish',move_1h:10,move_1d:null,move_5d:null,status_1h:'recorded',status_1d:'unavailable',status_5d:'pending',favorable_1h:false,favorable_1d:null,favorable_5d:null}]}}));
 await page.goto('/record');await expect(page.getByRole('row').filter({hasText:'MU'})).toContainText('Adverse');
 await expect(page.getByRole('row').filter({hasText:'MU'})).toContainText('+10.0%');
 await expect(page.getByRole('row').filter({hasText:'MU'})).toContainText('Unavailable');
 await expect(page.getByRole('row').filter({hasText:'MU'})).toContainText('Pending');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('small nonzero moves keep their sign instead of rounding to zero',async({page,request})=>{
 await join(page,request);
 await page.route('**/api/v1/record',route=>route.fulfill({json:{total:1,days:90,horizons:[],recent:[{ticker:'MU',alerted_at:Date.now()/1000-7200,price:100,closed_1h:false,direction:'bearish',move_1h:0.03,move_1d:null,move_5d:null,status_1h:'recorded',status_1d:'pending',status_5d:'pending',favorable_1h:false,favorable_1d:null,favorable_5d:null}]}}));
 await page.goto('/record');await expect(page.getByRole('row').filter({hasText:'MU'})).toContainText('+0.03%');
 await expect(page.getByRole('row').filter({hasText:'MU'})).toContainText('Adverse');
});
