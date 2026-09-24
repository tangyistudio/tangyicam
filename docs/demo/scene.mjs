// Procedural demo geometry only; no film or user assets.
export function addBox(vertices, x, y, z, w, h, d, color) {
  const p = [[x-w/2,y,z-d/2],[x+w/2,y,z-d/2],[x+w/2,y,z+d/2],[x-w/2,y,z+d/2],
    [x-w/2,y+h,z-d/2],[x+w/2,y+h,z-d/2],[x+w/2,y+h,z+d/2],[x-w/2,y+h,z+d/2]];
  const faces = [[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7],[4,5,6,7],[3,2,1,0]];
  const rgb = color.match(/\w\w/g).map(v => parseInt(v,16)/255);
  const shade = [.86,.92,1,.88,1.08,.75];
  faces.forEach((face, i) => {
    const c = rgb.map(v => Math.min(1,v*shade[i]));
    for (const j of [0,1,2,0,2,3]) vertices.push(...p[face[j]],...c);
  });
}
export function createScene() {
  const triangles = [], lines = [];
  const box = (...args) => addBox(triangles,...args);
  box(0,-.1,2,28,.1,30,'#e4f2ed');
  box(0,0,-5,13,4,.15,'#f7e9bf');box(-6.5,0,-1,.15,4,8,'#d6eae0');
  box(-3.9,1.2,-4.85,2.8,2.1,.08,'#93cbd5');box(3.9,1.2,-4.85,2.8,2.1,.08,'#93cbd5');
  box(0,0,-.8,5.2,1.3,1.25,'#72ab93');box(0,1.3,-.8,5.45,.15,1.45,'#ffdf80');
  for(const x of [-2,0,2]){box(x,0,1,.15,.8,.15,'#497368');box(x,.8,1,.65,.15,.65,'#e9ac63');}
  for(const x of [-1.5,0,1.5]){box(x,1.45,-.8,.12,.45,.12,'#44855f');box(x,2.9,-2,.65,.2,.65,'#ffd15b');}
  for(const x of [-5,5]){box(x,0,-2,.8,1.2,.8,'#e2a36e');box(x,1.2,-2,1.3,.8,1.3,'#78ac7c');}
  const line = (a,b) => {for(const p of [a,b]) lines.push(...p,197/255,217/255,200/255);};
  // A small physical offset keeps the floor grid from fighting the floor surface.
  for(let i=-10;i<=14;i++){line([i,.003,-10],[i,.003,15]);line([-12,.003,i],[12,.003,i]);}
  return {triangles:new Float32Array(triangles),lines:new Float32Array(lines)};
}
