import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import { chromium } from "playwright";

const host = {
  timestamp: 1800000000, hostname: "central-01", primary_ip: "192.168.6.20",
  uptime: 300, interfaces: [{name:"eth0", ipv4:"192.168.6.20", is_up:true,
    rx_rate:1024, tx_rate:512, rx_total:4096, tx_total:2048, packets_recv:10, packets_sent:5}],
  network_intel:{connections:[],listeners:[],failed_logins:[],frequent_ports:[]}
};
const agent = {...host, hostname:"agent-01", primary_ip:"192.168.6.21",
  interfaces:[{...host.interfaces[0],name:"ens18",rx_rate:2048,tx_rate:1024}]};
const fleet = {nodes:[{name:"central-01",kind:"central",online:true,data:host},
  {name:"agent-01",agent_id:"agent-01",kind:"agent",online:true,data:agent},
  {name:"offline-01",agent_id:"offline-01",kind:"agent",online:false,data:agent}],online:2,total:3};
let delayCluster = 0;
const template=fs.readFileSync("templates/index.html","utf8")
  .replace(/{% if auth_enabled %}[\s\S]*?{% endif %}/g,"");
const server=http.createServer(async(req,res)=>{
  const path=new URL(req.url,"http://localhost").pathname;
  if(path==="/api/cluster"&&delayCluster)await new Promise(r=>setTimeout(r,delayCluster));
  if(path==="/api/status"||path==="/api/cluster"){
    res.setHeader("Content-Type","application/json");
    return res.end(JSON.stringify(path.endsWith("status")?host:fleet));
  }
  if(path==="/"){res.setHeader("Content-Type","text/html");return res.end(template);}
  if(["/static/app.js","/static/app.css"].includes(path)){
    res.setHeader("Content-Type",path.endsWith(".js")?"text/javascript":"text/css");
    return res.end(fs.readFileSync("."+path));
  }
  res.statusCode=404;res.end();
});
await new Promise(r=>server.listen(0,"127.0.0.1",r));
const browser=await chromium.launch({headless:true});
const page=await browser.newPage();
const errors=[];
page.on("pageerror",e=>errors.push(e.message));
const failures=[];
async function test(name,fn){
  try{await fn();console.log("PASS "+name);}
  catch(e){failures.push(name);console.error("FAIL "+name+"\n"+e.stack);}
}
try{
  await page.goto("http://127.0.0.1:"+server.address().port);
  await page.waitForFunction(()=>document.querySelector("#connection-label").textContent.includes("LIVE"));
  await test("all navigation pages open and scope stays on supported pages",async()=>{
    for(const name of ["traffic","connections","ports","security","cluster","settings","overview"]){
      await page.locator('.nav[data-page="'+name+'"]').click();
      assert.equal(await page.locator("#page-"+name).evaluate(e=>e.classList.contains("active")),true);
      assert.equal(await page.locator("#page-scope").isVisible(),["connections","ports","security"].includes(name));
    }
  });
  await test("restore defaults resets saved and visible preferences",async()=>{
    await page.locator('.nav[data-page="settings"]').click();
    await page.locator("#theme-setting").selectOption("dark");
    await page.locator("#refresh-setting").selectOption("15");
    await page.locator("#compact-setting").check({force:true});
    await page.locator("#save-settings").click();
    await page.locator("#reset-settings").click();
    assert.equal(await page.locator("#theme-setting").inputValue(),"light");
    assert.equal(await page.locator("#refresh-setting").inputValue(),"5");
    assert.equal(await page.locator("#compact-setting").isChecked(),false);
    assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem("netscope-ui")).theme),"light");
  });
  await test("server selection changes traffic but leaves overview local",async()=>{
    await page.locator('.nav[data-page="traffic"]').click();
    await page.waitForFunction(()=>document.querySelector("#traffic-source").options.length===3);
    await page.locator("#traffic-source").selectOption("agent:agent-01");
    assert.equal(await page.locator("#traffic-rx").textContent(),"2.0 KB/s");
    await page.locator('.nav[data-page="overview"]').click();
    assert.equal(await page.locator("#rx-now").textContent(),"1.0 KB/s");
  });
  await test("filtering interfaces does not append chart samples",async()=>{
    await page.locator('.nav[data-page="traffic"]').click();
    const before=await page.evaluate(()=>historyRx.length);
    await page.locator("#interface-search").fill("eth");
    assert.equal(await page.evaluate(()=>historyRx.length),before);
  });
  await test("combined total excludes offline nodes",async()=>{
    await page.locator("#traffic-source").selectOption("all");
    assert.equal(await page.locator("#traffic-rx").textContent(),"3.0 KB/s");
  });
  await test("scope selection stays on the current page",async()=>{
    await page.locator('.nav[data-page="connections"]').click();
    await page.locator("#cluster-mode").click();
    assert.equal(await page.locator("#page-connections").evaluate(e=>e.classList.contains("active")),true);
    await page.locator("#single-mode").click();
    assert.equal(await page.locator("#page-connections").evaluate(e=>e.classList.contains("active")),true);
  });
  await test("mobile menu opens and navigation works",async()=>{
    await page.setViewportSize({width:390,height:844});
    await page.locator("#menu").click();
    await page.locator('.nav[data-page="settings"]').click();
    assert.equal(await page.locator("#page-settings").evaluate(e=>e.classList.contains("active")),true);
    assert.equal(await page.locator("#sidebar").evaluate(e=>e.classList.contains("open")),false);
  });
  await test("no browser startup or navigation errors",async()=>assert.deepEqual(errors,[]));
}finally{
  await browser.close();
  await new Promise(r=>server.close(r));
}
if(failures.length)process.exitCode=1;
