// Small, dependency-free camera model for the browser practice scene.
export const initialCamera = () => ({x:0,y:2.3,z:9,yaw:0,pitch:-0.12,focal:35});
export const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
export function move(camera, side, forward, up, dt){
 const c={...camera}, distance=Math.min(Math.max(dt,0),0.05)*3;
 const length=Math.max(1,Math.hypot(side,forward,up));
 side/=length;forward/=length;up/=length;
 c.x=clamp(c.x+(side*Math.cos(c.yaw)-forward*Math.sin(c.yaw))*distance,-6,6);
 c.z=clamp(c.z+(-side*Math.sin(c.yaw)-forward*Math.cos(c.yaw))*distance,1.5,12);
 c.y=clamp(c.y+up*distance,0.7,5);
 return c;
}
export function look(camera,dx,dy){return {...camera,yaw:camera.yaw-dx*0.006,pitch:clamp(camera.pitch-dy*0.006,-0.8,0.65)};}
export function project(point,c,width,height){
 const dx=point[0]-c.x,dy=point[1]-c.y,dz=point[2]-c.z;
 const rx=Math.cos(c.yaw)*dx-Math.sin(c.yaw)*dz,rz=Math.sin(c.yaw)*dx+Math.cos(c.yaw)*dz;
 const ry=Math.cos(c.pitch)*dy+Math.sin(c.pitch)*rz, depth=Math.sin(c.pitch)*dy-Math.cos(c.pitch)*rz;
 if(depth<=0.12)return null;
 const scale=width*c.focal/36;
 return [width/2+rx*scale/depth,height/2-ry*scale/depth,depth];
}
export function sampleTake(frames,time){
 if(!frames.length)return null;
 if(time<=frames[0].t)return {...frames[0].camera};
 const last=frames.at(-1);if(time>=last.t)return {...last.camera};
 let i=1;while(frames[i].t<time)i++;
 const a=frames[i-1],b=frames[i],ratio=(time-a.t)/(b.t-a.t);
 return Object.fromEntries(Object.keys(a.camera).map(k=>[k,a.camera[k]+(b.camera[k]-a.camera[k])*ratio]));
}
