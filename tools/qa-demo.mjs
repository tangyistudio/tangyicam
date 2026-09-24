import {spawn} from 'node:child_process';import {createServer} from 'node:http';import {readFileSync,writeFileSync,existsSync,mkdirSync,mkdtempSync} from 'node:fs';import {join,resolve,extname,sep} from 'node:path';import {fileURLToPath} from 'node:url';import {tmpdir} from 'node:os';import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../',import.meta.url)),docs=join(root,'docs'),out=process.env.QA_OUT||join(root,'dist','demo-qa');mkdirSync(out,{recursive:true});
let server;let base=process.env.DEMO_URL;
if(!base){server=createServer((req,res)=>{const part=decodeURIComponent(new URL(req.url,'http://localhost').pathname),path=resolve(docs,'.'+(part==='/'?'/index.html':part));if(!path.startsWith(docs+sep)){res.writeHead(403).end();return;}try{res.setHeader('Content-Type',({'.html':'text/html; charset=utf-8','.mjs':'text/javascript','.css':'text/css','.jpg':'image/jpeg','.png':'image/png'})[extname(path)]||'application/octet-stream');res.end(readFileSync(path));}catch{res.writeHead(404).end();}});await new Promise(r=>server.listen(0,'127.0.0.1',r));base='http://127.0.0.1:'+server.address().port;}
base=base.replace(/\/$/,'');const profile=mkdtempSync(join(tmpdir(),'tangyicam-demo-qa-'));
const chrome=process.env.CHROME_PATH||(process.platform==='win32'?'C:/Program Files/Google/Chrome/Application/chrome.exe':'/usr/bin/google-chrome');
const proc=spawn(chrome,['--headless=new','--disable-gpu','--no-proxy-server','--disable-background-networking','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,...(process.platform==='linux'?['--no-sandbox']:[]),'about:blank'],{windowsHide:true,stdio:'ignore'});
let socket;const events=[];const results=[];let serial=0;const pending=new Map();
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
try {
 for(let i=0;i<100&&!existsSync(join(profile,"DevToolsActivePort"));i++)await sleep(100);
 const port=readFileSync(join(profile,"DevToolsActivePort"),"utf8").split("\n")[0];
 const version=await(await fetch("http://127.0.0.1:"+port+"/json/version")).json();
 socket=new WebSocket(version.webSocketDebuggerUrl);
 await new Promise((res,rej)=>{socket.onopen=res;socket.onerror=rej;});
 socket.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const t=pending.get(m.id);if(t){clearTimeout(t.timer);pending.delete(m.id);m.error?t.reject(Error(JSON.stringify(m.error))):t.resolve(m.result);}}else events.push(m);};
 function send(method,params={},sessionId){return new Promise((resolve,reject)=>{const id=++serial;const timer=setTimeout(()=>reject(Error("CDP timeout "+method)),30000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});}
 const targets=await send("Target.getTargets");
 const {sessionId}=await send("Target.attachToTarget",{targetId:targets.targetInfos.find(t=>t.type==="page").targetId,flatten:true});
 const call=(method,params={})=>send(method,params,sessionId);
 const evaluate=async expression=>{const r=await call("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expression=>{for(let i=0;i<120;i++){try{if(await evaluate(expression))return;}catch{}await sleep(150);}throw Error("Wait failed: "+expression);};
 // Forward real HTTP responses; this host's Chrome network service stalls on loopback.
 socket.addEventListener("message",async e=>{const m=JSON.parse(e.data);if(m.method!=="Fetch.requestPaused")return;const {requestId,request}=m.params;
  try{const headers=new Headers();for(const [k,v] of Object.entries(request.headers))if(["cookie","content-type","range","origin","referer","user-agent","sec-fetch-mode"].includes(k.toLowerCase()))headers.set(k,v);
   const response=await fetch(request.url,{method:request.method,headers,...(request.postData?{body:request.postData}:{}),signal:AbortSignal.timeout(40000)});
   const responseHeaders=[...response.headers].filter(([k])=>!["content-encoding","content-length","transfer-encoding"].includes(k)).map(([name,value])=>({name,value}));
   await call("Fetch.fulfillRequest",{requestId,responseCode:response.status,responseHeaders,body:Buffer.from(await response.arrayBuffer()).toString("base64")});
  }catch(error){events.push({transportError:request.url,message:error.message});await call("Fetch.failRequest",{requestId,errorReason:"Failed"}).catch(()=>{});}
 });
 await call("Fetch.enable",{patterns:[{urlPattern:base+"/*"},{urlPattern:"https://media.tangyi.mx/*"}]});
 await call("Page.enable");await call("Runtime.enable");await call("Network.enable");
 await call("Emulation.setEmulatedMedia",{features:[{name:"prefers-reduced-motion",value:"reduce"}]});

 const state=()=>evaluate('window.tangyiDemo.snapshot()');
 const click=selector=>evaluate('document.querySelector('+JSON.stringify(selector)+').click()');
 const rect=selector=>evaluate('(()=>{const e=document.querySelector('+JSON.stringify(selector)+');e.scrollIntoView({block:"center",behavior:"instant"});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,width:r.width,height:r.height}})()');
 const mouse=(type,x,y)=>call('Input.dispatchMouseEvent',{type,x,y,button:'left',buttons:type==='mouseReleased'?0:1,clickCount:1});
 for(const width of [1440,1061,768,390,320]){
  await call('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:width<600});
  await call('Emulation.setTouchEmulationEnabled',{enabled:width<600});
  await call('Page.navigate',{url:base+'/'});await wait('!!window.tangyiDemo');await sleep(100);
  assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth+1'),false);
  const phone=await evaluate('(()=>{const p=document.querySelector(".phone"),r=p.getBoundingClientRect();return {width:r.width,height:r.height,overflow:p.scrollHeight>p.clientHeight+1||p.scrollWidth>p.clientWidth+1}})()');
  assert(phone.width/phone.height>1.9,'phone must remain landscape: '+JSON.stringify(phone));assert.equal(phone.overflow,false);
  const start=await state(),c=await rect('#scene');
  if(width<600){await call('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:c.x,y:c.y}]});await call('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:c.x+35,y:c.y-10}]});await call('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});}
  else{await mouse('mousePressed',c.x,c.y);await mouse('mouseMoved',c.x+50,c.y-10);await mouse('mouseReleased',c.x+50,c.y-10);}
  assert.notEqual((await state()).camera.yaw,start.camera.yaw);
  await click('#reset');await click('#record');const pad=await rect('#joystick');
  if(width<600){await call('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:pad.x,y:pad.y}]});await call('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:pad.x,y:pad.y-30}]});}
  else{await mouse('mousePressed',pad.x,pad.y);await mouse('mouseMoved',pad.x,pad.y-30);}
  await sleep(280);const moving=await state();assert(moving.camera.z<start.camera.z);
  if(width<600)await call('Input.dispatchTouchEvent',{type:'touchCancel',touchPoints:[]});else await mouse('mouseReleased',pad.x,pad.y-30);
  const stopped=await state();await sleep(100);assert.equal((await state()).camera.z,stopped.camera.z);assert.deepEqual((await state()).joystick,{x:0,y:0});
  await evaluate('(()=>{const e=document.querySelector("#focal");e.value=70;e.dispatchEvent(new Event("input",{bubbles:true}));})()');assert.equal((await state()).camera.focal,70);
  await click('#record');assert.equal((await state()).mode,'idle');assert((await state()).frameCount>=2);const end=(await state()).camera;
  await click('#replay');await wait('window.tangyiDemo.snapshot().mode==="idle"');assert.deepEqual((await state()).camera,end);
  await click('#record');await evaluate('window.dispatchEvent(new Event("blur"))');assert.equal((await state()).mode,'idle');assert.equal((await state()).heldInputs,0);
  await click('#reset');await evaluate('document.querySelector("#scene").focus()');await call('Input.dispatchKeyEvent',{type:'keyDown',key:'w',code:'KeyW'});await sleep(100);assert((await state()).camera.z<start.camera.z);
  await evaluate('window.dispatchEvent(new Event("blur"))');const blur=await state();await sleep(80);assert.equal((await state()).camera.z,blur.camera.z);await call('Input.dispatchKeyEvent',{type:'keyUp',key:'w',code:'KeyW'});
  await click('#reset');await rect('#scene');await sleep(80);
  const shot=await call('Page.captureScreenshot',{format:'png'});writeFileSync(join(out,'demo-'+width+'.png'),Buffer.from(shot.data,'base64'));
  await evaluate('document.querySelector("#qa").scrollIntoView();document.querySelector("details").open=true');assert(await evaluate('document.querySelector("details").open'));assert.equal(await evaluate('document.querySelectorAll("details").length'),11);
  results.push({width,touch:width<600,drag:true,joystick:true,cancelStops:true,focal:true,recordReplay:true,blurStops:true,keyboard:true,faqCount:11,phoneAspect:phone.width/phone.height,overflow:false});console.log('DEMO_BROWSER_PASS',width);
 }
 if(process.env.DEMO_CAPTURE==='1'){
  await call('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false});await call('Emulation.setTouchEmulationEnabled',{enabled:false});
  await call('Page.navigate',{url:base+'/'});await wait('!!window.tangyiDemo');await evaluate('document.querySelector("#demo-title").scrollIntoView({block:"start",behavior:"instant"})');await sleep(100);
  await click('#record');
  const area=await evaluate('(()=>{const r=document.querySelector("#scene").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()');
  await mouse('mousePressed',area.x,area.y);
  for(let i=0;i<32;i++){
   const offset=Math.sin(i/31*Math.PI*2)*35;await mouse('mouseMoved',area.x+offset,area.y+Math.sin(i/31*Math.PI)*10);
   if(i===10)await evaluate('(()=>{const e=document.querySelector("#focal");e.value=50;e.dispatchEvent(new Event("input",{bubbles:true}));})()');
   if(i===23)await evaluate('(()=>{const e=document.querySelector("#focal");e.value=35;e.dispatchEvent(new Event("input",{bubbles:true}));})()');
   await sleep(65);const shot=await call('Page.captureScreenshot',{format:'png'});writeFileSync(join(out,'motion-'+String(i).padStart(2,'0')+'.png'),Buffer.from(shot.data,'base64'));
  }
  await mouse('mouseReleased',area.x,area.y);await click('#record');
 }
 const exceptions=events.filter(e=>e.method==='Runtime.exceptionThrown');assert.equal(exceptions.length,0,JSON.stringify(exceptions));
 writeFileSync(join(out,'report.json'),JSON.stringify({base,results,exceptions},null,2));
 await send('Browser.close');
}finally{socket?.close();proc.kill();server?.close();}
