import {test as base,expect,type Page,type APIRequestContext} from '@playwright/test';
// One synthetic backend is shared by the serial suite. Isolate its auth ledger
// at case boundaries while retaining the real limits throughout each test.
export const test=base.extend<{authBoundary:void}>({authBoundary:[async({request},use)=>{
  // The HTTPS proxy can become ready before its Python child. Read-only probe;
  // do not replay auth writes or hide non-startup failures.
  await expect.poll(async()=>{
    const response=await request.get('/api/v1/auth/csrf');
    expect([200,503]).toContain(response.status());return response.status();
  }).toBe(200);
  await control(request,{action:'auth_test_boundary'});await use();
},{auto:true}]});
export const password='synthetic password only';
export async function control(request:APIRequestContext,body:object){const r=await request.post('/__fixture/control',{data:body});expect(r.ok()).toBeTruthy();return r.json();}
export async function join(page:Page,request:APIRequestContext){
  const {token}=await control(request,{action:'invite'});const username='member_'+Math.random().toString(36).slice(2,10);
  await page.goto('/join#'+token);await page.getByLabel('Username',{exact:true}).fill(username);
  await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Create account'}).click();
  await expect(page.getByRole('heading',{name:'Sign in'})).toBeVisible();
  await page.getByLabel('Username',{exact:true}).fill(username);await page.getByLabel('Password',{exact:true}).fill(password);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.getByRole('heading',{name:'Market overview'})).toBeVisible();
  return username;
}
export async function research(page:Page,ticker='SPY') {await page.getByRole('searchbox',{name:'Ticker'}).fill(ticker);await page.getByRole('button',{name:'Research',exact:true}).click();await expect(page.getByRole('heading',{name:`${ticker} research`,exact:true})).toBeVisible();}
