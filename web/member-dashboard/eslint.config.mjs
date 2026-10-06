import {defineConfig,globalIgnores} from 'eslint/config';
import next from 'eslint-config-next/core-web-vitals';
import ts from 'eslint-config-next/typescript';
import {fixupConfigRules} from '@eslint/compat';
export default defineConfig([...fixupConfigRules([...next,...ts]),globalIgnores(['.next/**','.e2e/**','test-results/**','playwright-report/**','next-env.d.ts'])]);
