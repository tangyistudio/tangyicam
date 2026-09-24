import {getMessage} from './messages.mjs?v=20260924-i18n';
import './language.mjs?v=20260924-i18n';
const msg=key=>getMessage(document.documentElement.lang,key);
import {initialCamera,move,look,sampleTake,clamp} from './camera.mjs';
import {createScene} from './scene.mjs?v=20260924-depth2';
import {createRenderer} from './renderer.mjs?v=20260924-depth2';
const $=s=>document.querySelector(s), canvas=$('#scene');
let camera=initialCamera(),frames=[],mode='idle',started=0,last=0,raf=0,dirty=true,drag=null,padDrag=null;
const keys=new Set(),held=new Map();let pad={x:0,y:0};
const status=$('#status'), pose=$('#pose'),padEl=$('#joystick'),thumb=$('#thumb');
const fallback=$('#render-fallback');
function rendererStatus(available,reason){
 fallback.hidden=available;
 $('#render-message').textContent=reason==='lost'?msg('render.lost'):msg('render.unavailable');
 if(available)announce(msg('status.recovered'));else stop(msg('status.renderPaused'));
 for(const control of document.querySelectorAll('.phone button,.phone input,.phone-support button'))control.disabled=!available;
 if(available)updateButtons();
}
let renderer;
try{renderer=createRenderer(canvas,createScene(),{onStatus:rendererStatus});}
catch{rendererStatus(false,'unavailable');}
function draw(){renderer?.draw(camera);
 pose.textContent=`X ${camera.x.toFixed(1)} · Y ${camera.y.toFixed(1)} · Z ${camera.z.toFixed(1)} · ${Math.round(camera.focal)} mm`;
 $('#focal').value=camera.focal;$('#focal-value').textContent=Math.round(camera.focal)+' mm';dirty=false;
}
function resize(){const r=canvas.getBoundingClientRect(),ratio=Math.min(devicePixelRatio||1,1.5);canvas.width=Math.round(r.width*ratio);canvas.height=Math.round(r.height*ratio);dirty=true;wake();}
function announce(s){status.textContent=s;}
function updateButtons(){$('#record').textContent=mode==='recording'?msg('control.stop'):msg('control.record');$('#record').setAttribute('aria-pressed',String(mode==='recording'));$('#replay').disabled=!renderer?.isAvailable()||frames.length<2||mode==='recording';$('#replay').textContent=mode==='replay'?msg('control.stop'):msg('control.replay');}
function clearInput(){keys.clear();held.clear();pad={x:0,y:0};drag=null;padDrag=null;thumb.style.transform='translate(0,0)';}
function stop(message){if(mode==='recording'&&frames.length)frames.push({t:performance.now()-started,camera:{...camera}});mode='idle';clearInput();updateButtons();if(message)announce(message);dirty=true;wake();}
function changeCamera(next){if(mode==='replay')stop(msg('status.replayInterrupted'));camera=next;dirty=true;wake();}
function tick(now){raf=0;const dt=last?Math.min((now-last)/1000,.05):0;last=now;
 if(mode==='replay'){const t=now-started;camera=sampleTake(frames,t);dirty=true;if(t>=frames.at(-1).t)stop(msg('status.replayDone'));}
 else {let side=pad.x,forward=-pad.y,up=0;const input=new Set([...keys,...held.values()]);side+=(input.has('d')||input.has('ArrowRight')?1:0)-(input.has('a')||input.has('ArrowLeft')?1:0);forward+=(input.has('w')||input.has('ArrowUp')?1:0)-(input.has('s')||input.has('ArrowDown')?1:0);up+=(input.has('e')?1:0)-(input.has('q')?1:0);if(side||forward||up){camera=move(camera,side,forward,up,dt);dirty=true;}}
 if(mode==='recording'){if(!frames.length||now-started-frames.at(-1).t>=40)frames.push({t:now-started,camera:{...camera}});$('#timer').textContent=((now-started)/1000).toFixed(1)+' s';if(now-started>=15000)stop(msg('status.limit'));}
 if(dirty)draw();if(mode!=='idle'||keys.size||held.size||pad.x||pad.y)raf=requestAnimationFrame(tick);
}
function wake(){if(!raf&&!document.hidden){last=performance.now();raf=requestAnimationFrame(tick);}}
canvas.addEventListener('pointerdown',e=>{if(!renderer?.isAvailable())return;canvas.focus({preventScroll:true});canvas.setPointerCapture(e.pointerId);drag={id:e.pointerId,x:e.clientX,y:e.clientY};if(mode==='replay')stop();drag={id:e.pointerId,x:e.clientX,y:e.clientY};});
canvas.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;changeCamera(look(camera,e.clientX-drag.x,e.clientY-drag.y));drag={id:e.pointerId,x:e.clientX,y:e.clientY};});
for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{drag=null;});
function updatePad(e){const r=padEl.getBoundingClientRect(),radius=r.width*.32;let x=(e.clientX-r.left-r.width/2)/radius,y=(e.clientY-r.top-r.height/2)/radius;const length=Math.max(1,Math.hypot(x,y));pad={x:x/length,y:y/length};thumb.style.transform=`translate(${pad.x*radius}px,${pad.y*radius}px)`;wake();}
padEl.addEventListener('pointerdown',e=>{padEl.focus({preventScroll:true});if(mode==='replay')stop();padDrag=e.pointerId;padEl.setPointerCapture(e.pointerId);updatePad(e);});padEl.addEventListener('pointermove',e=>{if(padDrag===e.pointerId)updatePad(e);});
for(const event of ['pointerup','pointercancel','lostpointercapture'])padEl.addEventListener(event,()=>{padDrag=null;pad={x:0,y:0};thumb.style.transform='translate(0,0)';});
for(const btn of document.querySelectorAll('[data-move]')){btn.addEventListener('pointerdown',e=>{if(mode==='replay')stop();held.set(e.pointerId,btn.dataset.move);btn.setPointerCapture(e.pointerId);wake();});for(const event of ['pointerup','pointercancel','lostpointercapture'])btn.addEventListener(event,e=>held.delete(e.pointerId));btn.addEventListener('click',e=>{if(e.detail===0){const k=btn.dataset.move;changeCamera(move(camera,k==='d'?1:k==='a'?-1:0,k==='w'?1:k==='s'?-1:0,k==='e'?1:k==='q'?-1:0,.05));}});}
const allowed=new Set(['w','a','s','d','q','e','ArrowUp','ArrowDown','ArrowLeft','ArrowRight']);
$('#playground').addEventListener('keydown',e=>{if(!renderer?.isAvailable())return;if(e.ctrlKey||e.metaKey||e.altKey||!allowed.has(e.key)||e.target.matches('input,summary,a'))return;e.preventDefault();if(mode==='replay')stop();keys.add(e.key);wake();});
$('#playground').addEventListener('focusout',e=>{if(e.relatedTarget&&!$('#playground').contains(e.relatedTarget))stop(msg('status.left'));});
window.addEventListener('keyup',e=>keys.delete(e.key));window.addEventListener('blur',()=>stop(msg('status.blur')));
document.addEventListener('visibilitychange',()=>{if(document.hidden){if(raf)cancelAnimationFrame(raf);raf=0;stop(mode==='recording'?msg('status.background'):undefined);}else wake();});
$('#focal').addEventListener('input',e=>changeCamera({...camera,focal:clamp(Number(e.target.value),18,100)}));
$('#reset').addEventListener('click',()=>{stop();camera=initialCamera();announce(msg('status.reset'));dirty=true;wake();});
$('#record').addEventListener('click',()=>{if(mode==='recording'){stop(msg('status.saved'));return;}stop();frames=[{t:0,camera:{...camera}}];mode='recording';started=performance.now();announce(msg('status.recording'));updateButtons();wake();});
$('#replay').addEventListener('click',()=>{if(mode==='replay'){stop(msg('status.replayStopped'));return;}if(frames.length<2)return;clearInput();mode='replay';started=performance.now();announce(msg('status.replaying'));updateButtons();wake();});
new ResizeObserver(resize).observe(canvas);updateButtons();resize();
// Read-only diagnostics for the documented QA checks, never a Blender connection.
window.tangyiDemo={snapshot:()=>({camera:{...camera},mode,frameCount:frames.length,heldInputs:keys.size+held.size,joystick:{...pad},renderer:renderer?.isAvailable()?'webgl':'unavailable'})};
