// Render the actual component using TypeScript's React transform, not Playwright's JSX transform.
const load=module.require.bind(module);
const fs=load('node:fs'),path=load('node:path'),Module=load('node:module'),ts=load('typescript');
const original=Module._resolveFilename;
Module._resolveFilename=function(id,parent,...rest){
 if(id.startsWith('@/'))id=path.resolve(__dirname,'../src',id.slice(2));
 return original.call(this,id,parent,...rest);
};
for(const extension of ['.ts','.tsx'])require.extensions[extension]=(module,filename)=>{
 const output=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true,target:ts.ScriptTarget.ES2022}});
 module._compile(output.outputText,filename);
};
const React=load('react'),{renderToStaticMarkup}=load('react-dom/server');
const {Sec,AnalysisPart}=load('../src/components/research-section.tsx');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(renderToStaticMarkup(input.component==='news'?React.createElement(AnalysisPart,{result:input.result,part:'news',price:null}):React.createElement(Sec,{p:input,message:null})));
