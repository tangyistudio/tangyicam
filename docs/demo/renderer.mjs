const vertexSource = `
attribute vec3 position;
attribute vec3 color;
uniform vec3 eye;
uniform vec2 rotation;
uniform vec2 projection;
varying lowp vec3 faceColor;
void main() {
  vec3 p = position-eye;
  float cy=cos(rotation.x), sy=sin(rotation.x);
  float cp=cos(rotation.y), sp=sin(rotation.y);
  float rx=cy*p.x-sy*p.z, rz=sy*p.x+cy*p.z;
  float ry=cp*p.y+sp*rz, depth=sp*p.y-cp*rz;
  const float nearPlane=.12, farPlane=80.;
  // Homogeneous coordinates let the GPU clip triangles crossing the near plane.
  gl_Position=vec4(projection.x*rx,projection.y*ry,
    (farPlane+nearPlane)/(farPlane-nearPlane)*depth-2.*farPlane*nearPlane/(farPlane-nearPlane),depth);
  faceColor=color;
}`;
const fragmentSource = `precision mediump float; varying lowp vec3 faceColor;
void main(){gl_FragColor=vec4(faceColor,1.);}`;

export function createRenderer(canvas, geometry, {onStatus=()=>{}, antialias=true}={}) {
  const gl=canvas.getContext('webgl',{alpha:false,antialias,depth:true});
  if(!gl) throw new Error('WebGL unavailable');
  let program, buffers=[], attributes, uniforms, ready=false, lastCamera;
  function initialize() {
    const shaders=[];
    try {
      for(const [type,source] of [[gl.VERTEX_SHADER,vertexSource],[gl.FRAGMENT_SHADER,fragmentSource]]) {
        const shader=gl.createShader(type);shaders.push(shader);
        gl.shaderSource(shader,source);gl.compileShader(shader);
        if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(shader));
      }
      program=gl.createProgram();for(const shader of shaders)gl.attachShader(program,shader);
      gl.linkProgram(program);
      if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program));
      attributes={position:gl.getAttribLocation(program,'position'),color:gl.getAttribLocation(program,'color')};
      uniforms=Object.fromEntries(['eye','rotation','projection'].map(n=>[n,gl.getUniformLocation(program,n)]));
      buffers=[];
      for(const [data,mode] of [[geometry.triangles,gl.TRIANGLES],[geometry.lines,gl.LINES]]) {
        if(!data?.length)continue;
        const buffer=gl.createBuffer();buffers.push({buffer,mode,count:data.length/6});
        gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);
      }
      gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.clearDepth(1);
      gl.disable(gl.CULL_FACE);gl.disable(gl.BLEND);
      gl.clearColor(228/255,242/255,237/255,1);
      ready=true;
    } finally {for(const shader of shaders)gl.deleteShader(shader);}
  }
  function draw(camera) {
    lastCamera={...camera};if(!ready||gl.isContextLost())return false;
    const {width,height}=canvas;if(!width||!height)return false;
    gl.viewport(0,0,width,height);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.useProgram(program);
    gl.uniform3f(uniforms.eye,camera.x,camera.y,camera.z);
    gl.uniform2f(uniforms.rotation,camera.yaw,camera.pitch);
    const f=2*camera.focal/36;gl.uniform2f(uniforms.projection,f,f*width/height);
    for(const {buffer,mode,count} of buffers) {
      gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
      gl.enableVertexAttribArray(attributes.position);gl.vertexAttribPointer(attributes.position,3,gl.FLOAT,false,24,0);
      gl.enableVertexAttribArray(attributes.color);gl.vertexAttribPointer(attributes.color,3,gl.FLOAT,false,24,12);
      gl.drawArrays(mode,0,count);
    }
    return true;
  }
  const lost=e=>{e.preventDefault();ready=false;onStatus(false,'lost');};
  const restored=()=>{try{initialize();if(lastCamera)draw(lastCamera);onStatus(true);}catch{ready=false;onStatus(false,'unavailable');}};
  function dispose(){ready=false;canvas.removeEventListener('webglcontextlost',lost);canvas.removeEventListener('webglcontextrestored',restored);for(const {buffer} of buffers)gl.deleteBuffer(buffer);if(program)gl.deleteProgram(program);}
  try {initialize();}catch(error){dispose();throw error;}
  canvas.addEventListener('webglcontextlost',lost);canvas.addEventListener('webglcontextrestored',restored);
  return {draw,dispose,isAvailable:()=>ready&&!gl.isContextLost()};
}
