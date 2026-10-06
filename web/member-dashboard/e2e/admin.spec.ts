import {expect} from '@playwright/test';
import {test,join,password} from './helpers';

test('admin: real role boundary, switches, account recovery and safe monitoring',async({page,request,browser})=>{
 const username=await join(page,request);
 await expect(page.getByRole('link',{name:'Admin',exact:true})).toHaveCount(0);
 await page.goto('/admin');await expect(page.getByText('Administrator access required.')).toBeVisible();
 expect((await page.request.get('/api/v1/admin/members')).status()).toBe(403);
 const context=await browser.newContext({ignoreHTTPSErrors:true,baseURL:'https://localhost:3443'});const owner=await context.newPage();const adminRequests:string[]=[];owner.on('request',r=>{if(r.url().includes('/api/v1/admin/'))adminRequests.push(r.method()+' '+new URL(r.url()).pathname);});
 await owner.goto('/login');await owner.getByLabel('Username',{exact:true}).fill('fixture_admin');await owner.getByLabel('Password',{exact:true}).fill(password);await owner.getByRole('button',{name:'Sign in',exact:true}).click();
 await owner.getByRole('link',{name:'Admin',exact:true}).click();await expect(owner.getByRole('heading',{name:'Administration',exact:true})).toBeVisible();
 await expect(owner.getByText('Verify identity outside this dashboard before issuing a password reset.')).toBeVisible();
 const self=owner.getByTestId('admin-member').filter({hasText:'fixture_admin'});await expect(self.getByRole('button',{name:'Suspend',exact:true})).toBeDisabled();
 await owner.getByRole('checkbox',{name:'Options Activity'}).click();await expect(owner.getByRole('checkbox',{name:'Options Activity'})).not.toBeChecked();
 await page.goto('/');await expect.poll(async()=> (await page.request.get('/api/v1/me')).json().then(x=>x.features.options.enabled)).toBe(false);
 await owner.getByRole('checkbox',{name:'Options Activity'}).click();
 await owner.getByRole('button',{name:'Create invitation'}).click();await expect(owner.getByLabel('One-time link')).toHaveValue(/\/join#/);
 const invite=(await owner.getByLabel('One-time link').inputValue()).split('#')[1];await owner.getByRole('button',{name:'Dismiss link'}).click();
 await owner.getByRole('button',{name:'Invitations',exact:true}).click();await owner.getByRole('button',{name:'Revoke invitation',exact:true}).last().click();await expect(owner.getByText(/Revoked .*Expires/)).toBeVisible();await owner.getByRole('button',{name:'Audit log',exact:true}).click();await expect(owner.getByText(/invite revoked .*ok/)).toBeVisible();await owner.getByRole('button',{name:'Members',exact:true}).click();
 const target=owner.getByTestId('admin-member').filter({hasText:username});await target.getByRole('button',{name:'Reset password',exact:true}).click();await expect(owner.getByLabel('One-time link')).toHaveValue(/\/reset#/);await owner.getByRole('button',{name:'Dismiss link'}).click();
 await target.getByRole('button',{name:'Suspend',exact:true}).click();await expect(target.getByRole('button',{name:'Reactivate',exact:true})).toBeVisible();await page.bringToFront();await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.getByRole('heading',{name:'Sign in',exact:true})).toBeVisible();
 await owner.bringToFront();await target.getByRole('button',{name:'Reactivate',exact:true}).click();await expect(target.getByRole('button',{name:'Suspend',exact:true})).toBeVisible();expect((await page.request.get('/api/v1/me')).status()).toBe(401);
 await expect(owner.getByTestId('health-frontend')).toContainText('unavailable');await expect(owner.getByTestId('health-compute')).toContainText('responsive');
 const audit=await owner.request.get('/api/v1/admin/audit');expect(await audit.text()).not.toContain(invite);expect(await audit.text()).not.toContain('token_digest');
 await owner.setViewportSize({width:1440,height:1000});await owner.screenshot({path:'.e2e/screenshots/admin-1440.png',fullPage:true});await owner.setViewportSize({width:390,height:844});await owner.screenshot({path:'.e2e/screenshots/admin-390.png',fullPage:true});expect(await owner.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(adminRequests).toContain('GET /api/v1/admin/features');expect(adminRequests.filter(x=>x==='PUT /api/v1/admin/features/options')).toHaveLength(2);expect(adminRequests.some(x=>/^DELETE \/api\/v1\/admin\/invites\/[a-f0-9-]+$/.test(x))).toBe(true);expect(adminRequests.some(x=>x.startsWith('POST /api/v1/admin/features/')||x.endsWith('/revoke'))).toBe(false);
 await context.close();
});
