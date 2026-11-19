const {browser}=require("./browser.cjs");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const {join}=require("node:path");
browser(async({cdp,js,size,sleep,wait,shot,exceptions,base,out})=>{
  await size(1440,900);
  await cdp("Network.enable");
  await cdp("Network.setCacheDisabled",{cacheDisabled:true});
  await cdp("Network.setBlockedURLs",{urls:["*/web/island/*.svg"]});
  await cdp("Page.navigate",{url:new URL("/city",base).href});
  await wait(()=>js("document.querySelector('#atlas-map')?.dataset.mapState==='ready' && !!document.querySelector('.atlas-pin')"));
  await js("map.setView([30.554,114.32],12,{animate:false});void 0");
  await wait(()=>js("map.getContainer().dataset.mapState==='error'"),5000);
  assert(await js("document.querySelector('.wuhan-board-surface').naturalWidth>0 && !document.querySelector('.board-status').hidden"));
  await cdp("Network.setBlockedURLs",{urls:[]});
  await js("document.querySelector('.board-status button').click()");
  await wait(()=>js("map.getContainer().dataset.mapState==='ready' && !!document.querySelector('.wuhan-streets .leaflet-tile-loaded')"),10000);
  await js("window.samples=[];map.on('zoom',()=>samples.push(map.getZoom()));void 0");
  const z=await js("map.getZoom()");
  const pos=await js("(()=>{const r=map.getContainer().getBoundingClientRect();return {x:r.x+r.width*.57,y:r.y+r.height*.46}})()");
  const saveAnchor=await js("map.mouseEventToLatLng({clientX:"+pos.x+",clientY:"+pos.y+"})");
  for(let i=0;i<8;i++){
    await cdp("Input.dispatchMouseEvent",{type:"mouseWheel",...pos,deltaX:0,deltaY:-35});await sleep(20);
  }
  await wait(()=>js("map.getZoom()>"+(z+1)),4000);await sleep(400);
  const wheel=await js("({end:map.getZoom(),frames:new Set(samples).size,drift:map.latLngToContainerPoint("+JSON.stringify(saveAnchor)+").distanceTo(map.mouseEventToContainerPoint({clientX:"+pos.x+",clientY:"+pos.y+"}))})");
  assert(wheel.frames>8);assert(wheel.drift<5);
  await cdp("Input.dispatchMouseEvent",{type:"mouseWheel",...pos,deltaX:0,deltaY:150});
  await wait(()=>js("map.getZoom()<"+(wheel.end-.4)),4000);
  await size(390,844,true);await cdp("Emulation.setTouchEmulationEnabled",{enabled:true,maxTouchPoints:5});
  await js("map.getContainer().scrollIntoView({block:'center'});map.setView([30.555,114.31],12,{animate:false});void 0");await sleep(400);
  const touch=await js("(()=>{const r=map.getContainer().getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,z:map.getZoom()}})()");
  const points=distance=>[-1,1].map((sign,i)=>({x:touch.x+distance*sign,y:touch.y,id:i+1}));
  await cdp("Input.dispatchTouchEvent",{type:"touchStart",touchPoints:points(28)});
  for(const distance of [34,42,50,60,72]){await cdp("Input.dispatchTouchEvent",{type:"touchMove",touchPoints:points(distance)});await sleep(28);}
  await cdp("Input.dispatchTouchEvent",{type:"touchEnd",touchPoints:[]});
  await wait(()=>js("map.getZoom()>"+(touch.z+.7)),4000);await sleep(450);
  const pinch=await js("map.getZoom()");assert(pinch>touch.z+.7);
  await shot("05-手机双指放大");
  assert.deepEqual(exceptions,[]);
  fs.writeFileSync(join(out,"缩放验收.json"),JSON.stringify({wheel,pinch:{from:touch.z,to:pinch},detailFailureRecovered:true,exceptions},null,2));
}).catch(e=>{console.error(e);process.exitCode=1});
