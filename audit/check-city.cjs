const {browser}=require("./browser.cjs");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const {join}=require("node:path");
browser(async({cdp,js,size,shot,exceptions,base,out,wait,sleep})=>{
  const go=path=>cdp("Page.navigate",{url:new URL(path,base).href});
  const click=sel=>js("document.querySelector("+JSON.stringify(sel)+").click()");
  const visible=()=>wait(()=>js("document.querySelectorAll('.atlas-pin').length>0"));
  const current=()=>js("JSON.parse(sessionStorage.getItem('saig-visitor-workspace-v1')).plans[0]");
  async function pin(name) {
    const sel=".atlas-pin[aria-label='"+name+"']";
    const pos=await js("(()=>{const r=document.querySelector("+JSON.stringify(sel)+").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+18}})()");
    for(const type of ["mousePressed","mouseReleased"])await cdp("Input.dispatchMouseEvent",{type,...pos,button:"left",clickCount:1});
    await wait(()=>js("document.querySelector('#detail h2').textContent==="+JSON.stringify(name)),3000);
  }
  await size(1440,940);await go("/city");await visible();
  await wait(()=>js("[...document.querySelectorAll('#atlas-map img, .portrait')].every(i=>i.complete&&i.naturalWidth)"));
  assert.equal(await js("document.querySelectorAll('.atlas-pin').length"),11);
  await shot("01-武汉地图");
  await click("#filters button:nth-child(3)");assert.equal(await js("document.querySelectorAll('.atlas-pin').length"),3);
  await pin("华中师范大学");await click("#toggle-pick");
  await click("#filters button:nth-child(4)");await pin("户部巷");await click("#toggle-pick");await click("#apply");
  await wait(()=>js("!document.querySelector('#open-route').hidden"),15000);
  const created=await current();assert.deepEqual(new Set(created.cards["1"].order),new Set(["华中师范大学","户部巷"]));
  await click("#open-route");await wait(()=>js("document.querySelector('#route-plan')?.value==='current'"));
  await go("/city");await visible();await click("#filters button:nth-child(2)");await pin("黄鹤楼");await click("#toggle-pick");await click("#apply");
  await wait(()=>js("!document.querySelector('#open-route').hidden"),15000);
  const updated=await current();assert.equal(updated.cards["1"].order.length,3);assert(updated.cards["1"].order.includes("黄鹤楼"));
  assert.deepEqual(updated.cards["1"].audit.violations,[]);
  await shot("02-加入已有行程");
  await click("#open-route");await wait(()=>js("document.querySelector('.route-stop .stop-edit')!==null"));
  await js("Array.from(document.querySelectorAll('.route-stop')).find(r=>r.querySelector('strong')?.textContent==='户部巷').querySelector('.stop-edit').click()");
  await click("#apply-stops");await wait(()=>js("!saving && !removed.size"));
  const deleted=await current();assert.deepEqual(deleted.cards["1"].order,updated.cards["1"].order.filter(n=>n!=="户部巷"));
  await go("/city");await visible();await click("#filters button:nth-child(4)");await pin("户部巷");await click("#toggle-pick");await click("#apply");
  await wait(()=>js("!document.querySelector('#open-route').hidden"));
  const restored=await current();assert.deepEqual(new Set(restored.cards["1"].order),new Set(updated.cards["1"].order));
  await go("/#workspace");await wait(()=>js("document.querySelector('.plan')?.innerText.includes('地图自选一日游')"));

  await size(390,844,true);await go("/city");await visible();
  assert.equal(await js("document.documentElement.scrollWidth"),390);
  await click("#filters button:nth-child(3)");await click("#expand");await pin("武汉大学");
  assert.equal(await js("document.querySelector('#expand').getAttribute('aria-pressed')"),"false");
  await shot("03-手机地点卡");await js("scrollTo(0,0)");await sleep(300);await shot("04-手机地图");
  assert.deepEqual(exceptions,[]);
  fs.writeFileSync(join(out,"验收.json"),JSON.stringify({desktop:1440,mobileEmulation:390,places:11,created:created.cards["1"].order,updated:updated.cards["1"].order,afterDelete:deleted.cards["1"].order,afterRestore:restored.cards["1"].order,exceptions},null,2));
}).catch(e=>{console.error(e);process.exitCode=1;});
