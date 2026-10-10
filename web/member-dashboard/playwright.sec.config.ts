import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./e2e',testMatch:'sec-filings.spec.tsx',workers:1,reporter:'list',use:{headless:true}});
