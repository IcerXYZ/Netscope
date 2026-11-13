// Bounded Node VM checks of repository rendering functions, not browser automation.
// Usage: node test_netscope_frontend.cjs PATH_TO_NETSCOPE
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(path.join(process.argv[2], 'static/app.js'), 'utf8');
const prefix = source.slice(0, source.indexOf('const defaults='));
async function run(data) {
  const elements = new Map(), warnings = [], texts = [];
  const element = () => ({classList:{add(){},remove(){},toggle(){}},append(){},replaceChildren(){},style:{},
    set textContent(v){ this.text = v; texts.push(v); }, get textContent(){return this.text;}});
  const fetch = async () => ({ok:true,status:200,json:async()=>data});
  const sandbox = {window:{fetch,location:{replace(){}}}, fetch,
    document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},createElement:element},
    console:{warn(...a){warnings.push(a.map(String).join(' '));}}, setTimeout,clearTimeout};
  vm.createContext(sandbox); vm.runInContext(prefix, sandbox);
  await vm.runInContext('loadCluster()', sandbox);
  return {elements,warnings,texts};
}
(async()=>{
  const normal = {online:1,total:1,nodes:[{online:true,name:'normal',data:{interfaces:[]}}]};
  assert.equal((await run(normal)).warnings.length,0);
  const malformed = {online:1,total:1,nodes:[{online:true,name:'node',data:{interfaces:'not-an-array'}}]};
  const result = await run(malformed);
  assert.equal(result.warnings.length,0);
  assert.equal(result.elements.get('cluster-count').text,'0 / 1 ONLINE');
  const marker = '<img src=x onerror=alert(1)>';
  const safe = await run({online:1,total:1,nodes:[{online:true,name:marker,data:{interfaces:[]}}]});
  assert(safe.texts.includes(marker));
  assert.equal(safe.warnings.length,0);
  assert.throws(()=>JSON.parse('{"cpu_percent":NaN}'),SyntaxError);
  console.log('4 checks passed: valid fleet renders; malformed agent isolated; name assigned as text; NaN invalid in browser JSON.');
})().catch(e=>{console.error(e);process.exitCode=1;});
