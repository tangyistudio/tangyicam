// Runs inside an isolated browser through qa-demo.mjs, including against live Pages.
async function checkRendering(moduleBase) {
  const {createRenderer}=await import(moduleBase+'renderer.mjs');
  const {addBox,createScene}=await import(moduleBase+'scene.mjs');
  const check=(condition,message)=>{if(!condition)throw new Error(message);};
  const camera={x:0,y:0,z:0,yaw:0,pitch:0,focal:35}, results=[], images=[];
  const red=[1,0,0],blue=[0,0,1],green=[0,1,0];
  const triangle=(points,color)=>points.flatMap(p=>[...p,...color]);
  const quad=(z,size,color)=>[...triangle([[-size,-size,z],[size,-size,z],[size,size,z]],color),...triangle([[-size,-size,z],[size,size,z],[-size,size,z]],color)];
  const fixture=(triangles,lines=[])=>{
    const canvas=document.createElement('canvas');canvas.width=128;canvas.height=128;
    const renderer=createRenderer(canvas,{triangles:new Float32Array(triangles),lines:new Float32Array(lines)},{antialias:false});
    const gl=canvas.getContext('webgl');
    const pixel=(x=64,y=64)=>{const p=new Uint8Array(4);gl.readPixels(x,y,1,1,gl.RGBA,gl.UNSIGNED_BYTE,p);return [...p];};
    return {canvas,renderer,gl,pixel};
  };
  const isColor=(p,c)=>c.every((v,i)=>Math.abs(p[i]-v)<3);
  for(const order of ['near-first','far-first']) {
    const near=quad(-2,.5,red),far=quad(-4,3,blue);
    const f=fixture(order==='near-first'?[...near,...far]:[...far,...near]);
    try{f.renderer.draw(camera);check(isColor(f.pixel(),[255,0,0]),'near surface must occlude wall: '+order);check(isColor(f.pixel(5,5),[0,0,255]),'wall outside object remains visible');results.push('depth-'+order);}finally{f.renderer.dispose();}
  }
  {
    const f=fixture([...quad(-4,3,blue),...triangle([[-.6,-.6,-2],[.6,-.6,-2],[0,.8,.2]],red)]);
    try{f.renderer.draw(camera);check(isColor(f.pixel(),[255,0,0]),'triangle crossing near plane must remain visible');check(isColor(f.pixel(5,5),[0,0,255]),'near-plane clipping must preserve background');results.push('near-plane-clipping');}finally{f.renderer.dispose();}
  }
  {
    const f=fixture(quad(-2,2,green),[-2,0,-3,...red,2,0,-3,...red,-.4,.2,-1,...blue,.4,.2,-1,...blue]);
    try{f.renderer.draw(camera);check(isColor(f.pixel(),[0,255,0]),'grid behind a surface must be hidden');const pixels=new Uint8Array(128*128*4);f.gl.readPixels(0,0,128,128,f.gl.RGBA,f.gl.UNSIGNED_BYTE,pixels);let bluePixels=0,redPixels=0;for(let i=0;i<pixels.length;i+=4){if(pixels[i+2]>250&&pixels[i]<3)bluePixels++;if(pixels[i]>250&&pixels[i+1]<3)redPixels++;}check(bluePixels>30&&redPixels===0,'visible lines render but occluded lines do not');results.push('grid-occlusion');}finally{f.renderer.dispose();}
  }
  {
    const vertices=[];addBox(vertices,0,1,-3,4,1,4,'#00ff00');const f=fixture(vertices);
    try{f.renderer.draw({...camera,pitch:.6});check(isColor(f.pixel(),[0,191,0]),'underside must be a closed shaded face');results.push('closed-underside');}finally{f.renderer.dispose();}
  }
  {
    const f=fixture(quad(-2,2,red));
    try {
      const extension=f.gl.getExtension('WEBGL_lose_context');check(extension,'context loss extension available');
      const event=name=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(name+' timeout')),4000);f.canvas.addEventListener(name,()=>{clearTimeout(timer);resolve();},{once:true});});
      f.renderer.draw(camera);const lost=event('webglcontextlost');extension.loseContext();await lost;check(!f.renderer.isAvailable(),'renderer suspends after context loss');
      // Let the lost event finish dispatch before requesting restoration.
      await new Promise(resolve=>setTimeout(resolve,100));
      const restored=event('webglcontextrestored');extension.restoreContext();await restored;check(f.renderer.isAvailable(),'renderer recovers context');f.renderer.draw(camera);check(isColor(f.pixel(),[255,0,0]),'geometry rebuilt after context restore');results.push('context-restoration');
    } finally {f.renderer.dispose();}
  }
  // Review evidence from the actual room, including camera limits and strong zoom.
  const canvas=document.createElement('canvas');canvas.width=800;canvas.height=500;
  const renderer=createRenderer(canvas,createScene());
  try {
    for(const [name,pose] of Object.entries({start:{x:0,y:2.3,z:9,yaw:0,pitch:-.12,focal:35},left:{x:0,y:2.3,z:4,yaw:.75,pitch:-.12,focal:35},close:{x:0,y:1,z:1.5,yaw:.1,pitch:.1,focal:70},low:{x:2,y:.7,z:2,yaw:.4,pitch:.35,focal:18},high:{x:-4,y:5,z:3,yaw:-.3,pitch:-.8,focal:35}})){
      renderer.draw(pose);images.push({name,data:canvas.toDataURL('image/png').split(',')[1]});
    }
  } finally {renderer.dispose();}
  return {results,images};
}
