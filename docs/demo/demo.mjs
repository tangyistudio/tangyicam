import {initialCamera,move,look,project,sampleTake,clamp} from './camera.mjs';
const $=s=>document.querySelector(s), canvas=$('#scene'),ctx=canvas.getContext('2d');
let camera=initialCamera(),frames=[],mode='idle',started=0,last=0,raf=0,dirty=true,drag=null,padDrag=null;
const keys=new Set(),held=new Map();let pad={x:0,y:0};
const status=$('#status'), pose=$('#pose'),padEl=$('#joystick'),thumb=$('#thumb');
const objects=[];
function box(x,y,z,w,h,d,color){const p=[[x-w/2,y,z-d/2],[x+w/2,y,z-d/2],[x+w/2,y,z+d/2],[x-w/2,y,z+d/2],[x-w/2,y+h,z-d/2],[x+w/2,y+h,z-d/2],[x+w/2,y+h,z+d/2],[x-w/2,y+h,z+d/2]];const faces=[[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7],[4,5,6,7]];for(const f of faces)objects.push({p:f.map(i=>p[i]),color});}
box(0,0,-5,13,4,.15,'#f7e9bf');box(-6.5,0,-1,.15,4,8,'#d6eae0');
box(-3.9,1.2,-4.85,2.8,2.1,.08,'#93cbd5');box(3.9,1.2,-4.85,2.8,2.1,.08,'#93cbd5');
box(0,0,-.8,5.2,1.3,1.25,'#72ab93');box(0,1.3,-.8,5.45,.15,1.45,'#ffdf80');
for(const x of [-2,0,2]){box(x,0,1,.15,.8,.15,'#497368');box(x,.8,1,.65,.15,.65,'#e9ac63');}
for(const x of [-1.5,0,1.5]){box(x,1.45,-.8,.12,.45,.12,'#44855f');box(x,2.9,-2,.65,.2,.65,'#ffd15b');}
box(-5,0,-2,.8,1.2,.8,'#e2a36e');box(-5,1.2,-2,1.3,.8,1.3,'#78ac7c');
box(5,0,-2,.8,1.2,.8,'#e2a36e');box(5,1.2,-2,1.3,.8,1.3,'#78ac7c');
function line(a,b,color){a=project(a,camera,canvas.width,canvas.height);b=project(b,camera,canvas.width,canvas.height);if(!a||!b)return;ctx.strokeStyle=color;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();}
function draw(){const w=canvas.width,h=canvas.height;ctx.fillStyle='#e4f2ed';ctx.fillRect(0,0,w,h);ctx.lineWidth=1;for(let i=-10;i<=14;i++){line([i,0,-10],[i,0,15],'#c5d9c8');line([-12,0,i],[12,0,i],'#c5d9c8');}
 const faces=objects.map(o=>({...o,screen:o.p.map(p=>project(p,camera,w,h))})).filter(o=>o.screen.every(Boolean)).sort((a,b)=>b.screen.reduce((s,p)=>s+p[2],0)-a.screen.reduce((s,p)=>s+p[2],0));
 for(const o of faces){ctx.beginPath();o.screen.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fillStyle=o.color;ctx.fill();ctx.strokeStyle='#315b5329';ctx.stroke();}
 ctx.strokeStyle='#ffffff88';ctx.lineWidth=1;for(const k of [1/3,2/3]){ctx.beginPath();ctx.moveTo(w*k,0);ctx.lineTo(w*k,h);ctx.stroke();ctx.beginPath();ctx.moveTo(0,h*k);ctx.lineTo(w,h*k);ctx.stroke();}
 pose.textContent=`X ${camera.x.toFixed(1)} · Y ${camera.y.toFixed(1)} · Z ${camera.z.toFixed(1)} · ${Math.round(camera.focal)} mm`;
 $('#focal').value=camera.focal;$('#focal-value').textContent=Math.round(camera.focal)+' mm';dirty=false;
}
function resize(){const r=canvas.getBoundingClientRect(),ratio=Math.min(devicePixelRatio||1,1.5);canvas.width=Math.round(r.width*ratio);canvas.height=Math.round(r.height*ratio);dirty=true;wake();}
function announce(s){status.textContent=s;}
function updateButtons(){$('#record').textContent=mode==='recording'?'■ 停止':'● 錄製';$('#record').setAttribute('aria-pressed',String(mode==='recording'));$('#replay').disabled=frames.length<2||mode==='recording';$('#replay').textContent=mode==='replay'?'■ 停止':'▶ 回放';}
function clearInput(){keys.clear();held.clear();pad={x:0,y:0};drag=null;padDrag=null;thumb.style.transform='translate(0,0)';}
function stop(message){if(mode==='recording'&&frames.length)frames.push({t:performance.now()-started,camera:{...camera}});mode='idle';clearInput();updateButtons();if(message)announce(message);dirty=true;wake();}
function changeCamera(next){if(mode==='replay')stop('回放已停止，可繼續操作。');camera=next;dirty=true;wake();}
function tick(now){raf=0;const dt=last?Math.min((now-last)/1000,.05):0;last=now;
 if(mode==='replay'){const t=now-started;camera=sampleTake(frames,t);dirty=true;if(t>=frames.at(-1).t)stop('回放完成。這是瀏覽器練習紀錄，未傳送至 Blender。');}
 else {let side=pad.x,forward=-pad.y,up=0;const input=new Set([...keys,...held.values()]);side+=(input.has('d')||input.has('ArrowRight')?1:0)-(input.has('a')||input.has('ArrowLeft')?1:0);forward+=(input.has('w')||input.has('ArrowUp')?1:0)-(input.has('s')||input.has('ArrowDown')?1:0);up+=(input.has('e')?1:0)-(input.has('q')?1:0);if(side||forward||up){camera=move(camera,side,forward,up,dt);dirty=true;}}
 if(mode==='recording'){if(!frames.length||now-started-frames.at(-1).t>=40)frames.push({t:now-started,camera:{...camera}});$('#timer').textContent=((now-started)/1000).toFixed(1)+' s';if(now-started>=15000)stop('已保存 15 秒練習，可以回放。');}
 if(dirty)draw();if(mode!=='idle'||keys.size||held.size||pad.x||pad.y)raf=requestAnimationFrame(tick);
}
function wake(){if(!raf&&!document.hidden){last=performance.now();raf=requestAnimationFrame(tick);}}
canvas.addEventListener('pointerdown',e=>{canvas.focus({preventScroll:true});canvas.setPointerCapture(e.pointerId);drag={id:e.pointerId,x:e.clientX,y:e.clientY};if(mode==='replay')stop();drag={id:e.pointerId,x:e.clientX,y:e.clientY};});
canvas.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;changeCamera(look(camera,e.clientX-drag.x,e.clientY-drag.y));drag={id:e.pointerId,x:e.clientX,y:e.clientY};});
for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{drag=null;});
function updatePad(e){const r=padEl.getBoundingClientRect(),radius=r.width*.32;let x=(e.clientX-r.left-r.width/2)/radius,y=(e.clientY-r.top-r.height/2)/radius;const length=Math.max(1,Math.hypot(x,y));pad={x:x/length,y:y/length};thumb.style.transform=`translate(${pad.x*radius}px,${pad.y*radius}px)`;wake();}
padEl.addEventListener('pointerdown',e=>{padEl.focus({preventScroll:true});if(mode==='replay')stop();padDrag=e.pointerId;padEl.setPointerCapture(e.pointerId);updatePad(e);});padEl.addEventListener('pointermove',e=>{if(padDrag===e.pointerId)updatePad(e);});
for(const event of ['pointerup','pointercancel','lostpointercapture'])padEl.addEventListener(event,()=>{padDrag=null;pad={x:0,y:0};thumb.style.transform='translate(0,0)';});
for(const btn of document.querySelectorAll('[data-move]')){btn.addEventListener('pointerdown',e=>{if(mode==='replay')stop();held.set(e.pointerId,btn.dataset.move);btn.setPointerCapture(e.pointerId);wake();});for(const event of ['pointerup','pointercancel','lostpointercapture'])btn.addEventListener(event,e=>held.delete(e.pointerId));btn.addEventListener('click',e=>{if(e.detail===0){const k=btn.dataset.move;changeCamera(move(camera,k==='d'?1:k==='a'?-1:0,k==='w'?1:k==='s'?-1:0,k==='e'?1:k==='q'?-1:0,.05));}});}
const allowed=new Set(['w','a','s','d','q','e','ArrowUp','ArrowDown','ArrowLeft','ArrowRight']);
$('#playground').addEventListener('keydown',e=>{if(e.ctrlKey||e.metaKey||e.altKey||!allowed.has(e.key)||e.target.matches('input,summary,a'))return;e.preventDefault();if(mode==='replay')stop();keys.add(e.key);wake();});
$('#playground').addEventListener('focusout',e=>{if(e.relatedTarget&&!$('#playground').contains(e.relatedTarget))stop('已離開練習場，操作暫停。');});
window.addEventListener('keyup',e=>keys.delete(e.key));window.addEventListener('blur',()=>stop('已暫停操作；回到練習場可繼續。'));
document.addEventListener('visibilitychange',()=>{if(document.hidden){if(raf)cancelAnimationFrame(raf);raf=0;stop(mode==='recording'?'切換背景，錄製已停止。':undefined);}else wake();});
$('#focal').addEventListener('input',e=>changeCamera({...camera,focal:clamp(Number(e.target.value),18,100)}));
$('#reset').addEventListener('click',()=>{stop();camera=initialCamera();announce('已回到起始位置。');dirty=true;wake();});
$('#record').addEventListener('click',()=>{if(mode==='recording'){stop('練習已保存，可按回放。');return;}stop();frames=[{t:0,camera:{...camera}}];mode='recording';started=performance.now();announce('正在錄製瀏覽器練習，最多 15 秒。');updateButtons();wake();});
$('#replay').addEventListener('click',()=>{if(mode==='replay'){stop('回放已停止。');return;}if(frames.length<2)return;clearInput();mode='replay';started=performance.now();announce('回放你的瀏覽器運鏡。');updateButtons();wake();});
new ResizeObserver(resize).observe(canvas);updateButtons();resize();
// Read-only diagnostics for the documented QA checks, never a Blender connection.
window.tangyiDemo={snapshot:()=>({camera:{...camera},mode,frameCount:frames.length,heldInputs:keys.size+held.size,joystick:{...pad}})};
