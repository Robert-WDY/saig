const fs = require("node:fs");
const { setTimeout: sleep } = require("node:timers/promises");

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

async function browser(run) {
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
    await run({cdp,js,size,shot,exceptions,base,out,wait,sleep});
  } finally {
    try {await cdp("Browser.close");} catch {}
    ws.close();
  }
}
module.exports = {browser};
