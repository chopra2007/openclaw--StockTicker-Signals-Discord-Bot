import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./e2e',fullyParallel:false,workers:1,timeout:45000,
  expect:{timeout:12000},reporter:[['list'],['html',{open:'never'}]],
  use:{baseURL:'https://localhost:3443',ignoreHTTPSErrors:true,trace:'retain-on-failure',screenshot:'only-on-failure'},
  webServer:{command:'node e2e/serve.mjs',url:'https://localhost:3443',ignoreHTTPSErrors:true,timeout:120000,reuseExistingServer:false},
});
