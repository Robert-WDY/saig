const fs = require("node:fs");
const { setTimeout: sleep } = require("node:timers/promises");
const assert = require("node:assert/strict");
const { join, resolve } = require("node:path");
const profile = process.argv[2];
const out = process.argv[3];
const base = process.env.SAIG_TEST_URL || "http://127.0.0.1:18943/";
fs.mkdirSync(out, { recursive: true });

async function wait(fn, limit = 90000) {
  const start = Date.now();
  while (Date.now() - start < limit) {
    const value = await fn();
    if (value) return value;
    await sleep(125);
  }
  throw new Error("Timed out");
}

async function main() {
  const port = (await wait(() => {
    try {return fs.readFileSync(join(profile,"DevToolsActivePort"),"utf8").trim();} catch{return null;}
  },10000)).split(/\r?\n/)[0];
  const pages = await (await fetch("http://127.0.0.1:"+port+"/json/list")).json();
  const ws = new WebSocket(pages.find(t=>t.type==="page").webSocketDebuggerUrl);
  const pending = new Map();
  const exceptions = [];
  let id = 0;
  ws.onmessage = event => {
    const msg = JSON.parse(event.data);
    if (msg.method === "Runtime.exceptionThrown") exceptions.push(msg.params.exceptionDetails.text);
    if (pending.has(msg.id)) {
      const cb = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) cb.reject(msg.error); else cb.resolve(msg.result);
    }
  };
  await new Promise((resolve, reject) => {ws.onopen=resolve; ws.onerror=reject;});
  function cdp(method,params={}) {
    return new Promise((resolve,reject)=>{
      const key=++id;
      pending.set(key,{resolve,reject});
      ws.send(JSON.stringify({id:key,method,params}));
    });
  }
  async function js(expression) {
    const value=await cdp("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true,userGesture:true});
    if(value.exceptionDetails)throw new Error(value.exceptionDetails.exception?.description || value.exceptionDetails.text);
    return value.result.value;
  }
  async function size(width,height,mobile=false) {
    await cdp("Emulation.setDeviceMetricsOverride",{width,height,deviceScaleFactor:1,mobile});
  }
  async function shot(name) {
    const pic=await cdp("Page.captureScreenshot",{format:"png",captureBeyondViewport:false});
    fs.writeFileSync(join(out,name+".png"),Buffer.from(pic.data,"base64"));
  }
  try {
    await cdp("Runtime.enable");
    await cdp("Page.enable");
    await cdp("Page.addScriptToEvaluateOnNewDocument",{source:"Crypto.prototype.randomUUID=undefined;Array.prototype.findLast=undefined;Object.hasOwn=undefined;AbortSignal.timeout=undefined;"});
    if(process.env.SAIG_LEGACY) await cdp("Page.addScriptToEvaluateOnNewDocument",{source:"HTMLDialogElement.prototype.showModal=undefined;window.confirm=()=>true;"});
    await size(1440,960);
    await cdp("Page.navigate",{url:base});
    await wait(()=>js("document.querySelector('.connection.online') && document.querySelector('.hero img').naturalWidth"),20000);
    const desktop=await js("({width:document.documentElement.clientWidth, scroll:document.documentElement.scrollWidth, title:document.title})");
    assert.equal(desktop.width,desktop.scroll);
    await shot("01-首页");

    const results=[];
    async function turn(selector,fill=false) {
      const count=await js("document.querySelectorAll('.message.assistant').length");
      const started=Date.now();
      await js("Array.from(document.querySelectorAll(" + JSON.stringify(selector[0]) + ")).find(el => el.textContent.includes(" + JSON.stringify(selector[1]) + ")).click()");
      if(fill)await js("document.querySelector('#composer').requestSubmit()");
      await wait(()=>js("document.querySelectorAll('.message.assistant').length>"+count+" || !!document.querySelector('.message.error')"));
      const error=await js("document.querySelector('.message.error')?.innerText");
      assert.ok(!error,error);
      const result=await js("JSON.parse(sessionStorage.getItem('saig-visitor-workspace-v1')).messages.at(-1).result");
      const response={question:selector[1],elapsed_ms:Date.now()-started,answer:result.answer,
                      sources:result.citations?.map(c=>c.id),deliverables:result.deliverables?.map(d=>[d.kind,d.status,d.replanned_days])};
      results.push(response);
      await js("document.querySelectorAll('.message.assistant')[document.querySelectorAll('.message.assistant').length-1].scrollIntoView({block:'center'})");
      await sleep(450);
      await shot("answer-"+results.length);
      fs.writeFileSync(join(out,"浏览器验收.json"),JSON.stringify({desktop,results,exceptions},null,2),"utf8");
      console.log(response.question,response.elapsed_ms,response.sources,response.deliverables ?? "");
      return result;
    }
    const introduction=await turn([".starter","认识武汉"]);
    assert.match(introduction.answer,/热干面|豆皮|面窝/);
    for (const district of ["汉口","汉阳","武昌"]) assert.ok(introduction.answer.includes(district));
    const plans=await turn(["#followups button","规划并比较行程"],true);
    assert.equal(plans.deliverables.filter(d=>d.kind==="plan"&&d.status==="passed").length,2);
    assert.ok(plans.deliverables.some(d=>d.kind==="compare"&&d.status==="passed"));
    const revision=await turn(["#followups button","调整两日游"],true);
    const changed=revision.deliverables.find(d=>d.kind==="revise"&&d.status==="passed");
    assert.deepEqual(changed.replanned_days,[2]);
    assert.equal(changed.cards["2"].contract.destination,"汉口站");
    assert.ok(revision.deliverables.some(d=>d.kind==="compare"&&d.status==="passed"));
    assert.match(await js("document.querySelector('#plans').innerText"),/本轮更新第 2 天/);
    assert.match(await js("document.querySelector('#plans').innerText"),/汉口站/);
    assert.match(await js("document.querySelector('#plans').innerText"),/\d+ 站 → \d+ 站/);
    const show = revision.deliverables.find(d=>d.kind==="show"&&d.status==="passed");
    if (show) {
      await js("Array.from(document.querySelectorAll('.delivery')).reverse().find(el=>el.textContent.includes(" + JSON.stringify(show.title) + ")).click()");
      assert.equal(await js("document.querySelector('.plan.selected .plan-header').id"),"plan-toggle-"+show.inputs[0]);
    }
    await js("Array.from(document.querySelectorAll('.delivery')).reverse().find(el=>el.textContent.includes(" + JSON.stringify(changed.title) + ")).click()");
    assert.equal(await js("document.querySelector('.plan.selected .plan-header').id"),"plan-toggle-"+changed.option_id);
    await js("window.scrollTo(0,0)");
    await sleep(400);
    await shot("02-调整行程");
    await js("document.querySelector('#comparison-tab').click()");
    assert.match(await js("document.querySelector('#comparison').innerText"),/汉口站/);
    await shot("03-方案比较");
    await cdp("Browser.setDownloadBehavior",{behavior:"allow",downloadPath:resolve(out)});
    await js("document.querySelector('#save-comparison').click()");
    await wait(()=>fs.existsSync(join(out,"武汉接线台-路线对比.png")),12000);
    const poster=fs.readFileSync(join(out,"武汉接线台-路线对比.png"));
    assert.equal(poster.toString("ascii",1,4),"PNG");
    assert.equal(poster.readUInt32BE(16),1080);
    const community=await turn(["#followups button","问数命"],true);
    assert.match(community.answer,/智民里/);
    assert.match(community.answer,/真实订单|项目实战/);
    const contest=await turn(["#followups button","问 SAIG"],true);
    assert.match(contest.answer,/项目简介/);
    assert.match(contest.answer,/演示视频/);
    assert.match(contest.answer,/超级个体|Super Person Unit/);

    const mapUrl=await js("document.querySelector('#jump-map').href");
    assert.match(mapUrl,/\/routes\?/);
    assert.match(mapUrl,/day=2/);
    await cdp("Page.navigate",{url:mapUrl});
    await wait(()=>js("document.querySelectorAll('.map-pin').length===4"),15000);
    assert.match(await js("document.querySelector('#day-title').textContent"),/第 2 天/);
    assert.match(await js("document.querySelector('#route-stops').innerText"),/汉口站/);
    const day2=changed.cards["2"];
    const limit=day2.contract.end-day2.contract.buffer;
    const ceiling=Math.ceil(day2.audit.arrival/10)*10;
    const expected=ceiling<=limit?ceiling:day2.audit.arrival;
    const display=String(Math.floor(expected/60)).padStart(2,"0")+":"+String(expected%60).padStart(2,"0");
    assert.ok((await js("document.querySelector('#route-stops').innerText")).includes("预计 "+display+" 到"));
    await wait(()=>js("document.querySelector('.leaflet-image-layer')?.naturalWidth > 0"),20000).catch(()=>null);
    await sleep(400);
    const mapTiles=await js("document.querySelectorAll('.leaflet-tile-loaded').length");
    await shot("06-路线地图");
    await cdp("Network.enable");
    await cdp("Network.setBlockedURLs",{urls:["*://tile.openstreetmap.org/*"]});
    await js("document.querySelector('#play-route').click()");
    for(let frame=0;frame<12;frame++){ await shot("play-"+String(frame).padStart(2,"0")); await sleep(180); }
    await wait(()=>js("document.querySelector('#route-progress').textContent==='路线播放完成'"),12000);
    assert.match(await js("document.querySelector('.route-stop.active').innerText"),/汉口站/);
    await js("document.querySelector('.route-stop.active button').click()");
    assert.match(await js("document.querySelector('.leaflet-popup-content').innerText"),/汉口站/);
    await js("Array.from(document.querySelectorAll('#route-days button')).find(el=>el.textContent.includes('1')).click()");
    assert.match(await js("document.querySelector('#day-title').textContent"),/第 1 天/);
    const navItems = await js("Array.from(document.querySelectorAll('nav a'),a=>a.textContent)");
    const normalMap = await js("document.querySelector('#route-map').clientHeight");
    const center=await js("(()=>{const r=document.querySelector('#route-map').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,z:map.getZoom()}})()");
    await cdp("Input.dispatchMouseEvent",{type:"mouseWheel",x:center.x,y:center.y,deltaX:0,deltaY:-170});
    await wait(()=>js("map.getZoom()>"+center.z),3500);
    await js("document.querySelector('#expand-map').click()");
    await wait(()=>js("document.querySelector('#route-map').clientHeight>"+normalMap),3000);
    await shot("08-展开大图");
    await cdp("Input.dispatchKeyEvent",{type:"keyDown",key:"Escape"});
    await wait(()=>js("!document.body.classList.contains('map-expanded')"));
    await js("Array.from(document.querySelectorAll('#route-days button')).find(el=>el.textContent.includes('2')).click()");
    const readState="JSON.parse(sessionStorage.getItem('saig-visitor-workspace-v1'))";
    const targetId=await js("document.querySelector('#route-plan').value");
    const planExpr=readState+".plans.find(p=>p.id==="+JSON.stringify(targetId)+")";
    const beforeEdit=await js(planExpr);
    const removedStop=await js("document.querySelector('.route-stop:has(.stop-edit) strong').textContent");
    await js("document.querySelector('.route-stop .stop-edit').click();document.querySelector('#apply-stops').click()");
    await wait(()=>js("!saving && !removed.size"),10000);
    const afterDelete=await js(planExpr);
    assert.deepEqual(afterDelete.cards['1'],beforeEdit.cards['1']);
    assert.deepEqual(afterDelete.cards['2'].order,beforeEdit.cards['2'].order.filter(n=>n!==removedStop));
    await js("document.querySelector('#place-picker').value="+JSON.stringify(removedStop)+"; document.querySelector('#place-picker').dispatchEvent(new Event('change'));document.querySelector('#add-stop').click();document.querySelector('#apply-stops').click()");
    await wait(()=>js("!saving && !added.size"),10000);
    const afterAdd=await js(planExpr);
    assert.ok(afterAdd.cards['2'].order.includes(removedStop));
    assert.deepEqual(afterAdd.cards['1'],beforeEdit.cards['1']);
    assert.ok(afterAdd.cards['2'].audit.arrival<=limit);
    await shot("09-地图重排");
    await size(390,844,true);
    await sleep(220);
    const mapMobile=await js("({width:innerWidth,scroll:document.documentElement.scrollWidth})");
    assert.equal(mapMobile.width,mapMobile.scroll);
    assert.ok(await js("rows.filter(row=>row.coords).every(row=>map.getBounds().contains(row.coords))"));
    await shot("07-手机地图");
    await cdp("Page.navigate",{url:base});
    await wait(()=>js("document.querySelectorAll('.message.assistant').length===7"),10000);

    assert.deepEqual(await js("Array.from(document.querySelectorAll('nav a'),a=>a.textContent)"),navItems);
    assert.equal(await js("selectedPlan"),targetId);
    assert.equal(await js("openDay"),"2");
    await size(390,844,true);
    await js("window.scrollTo(0,0)");
    await sleep(350);
    const mobile=await js("({width:innerWidth,scroll:document.documentElement.scrollWidth})");
    assert.equal(mobile.width,mobile.scroll);
    await js("document.querySelector('#workspace').scrollIntoView({block:'start'})");
    await sleep(450);
    await shot("04-手机行程板");
    await js("document.querySelector('#reset').click()");
    if (await js("typeof document.querySelector('#reset-dialog').showModal === 'function'"))
      await js("document.querySelector('#reset-dialog button[value=reset]').click()");
    await wait(()=>js("!document.querySelector('#welcome').hidden"));
    assert.equal(await js("document.querySelectorAll('.message').length"),0);
    await js("window.scrollTo(0,0)");
    await sleep(400);
    await shot("05-手机首页");
    assert.deepEqual(exceptions,[]);
    fs.writeFileSync(join(out,"浏览器验收.json"),JSON.stringify({desktop,mobile,mapMobile,mapTiles,mapEdit:{normalMap,removedStop,before:beforeEdit.cards["2"].order,afterDelete:afterDelete.cards["2"].order,afterAdd:afterAdd.cards["2"].order},results,exceptions,reset:true,passed:true},null,2),"utf8");
  } finally {
    try {await cdp("Browser.close");} catch {}
    ws.close();
  }
}
main().catch(error=>{console.error(error); process.exitCode=1;});
