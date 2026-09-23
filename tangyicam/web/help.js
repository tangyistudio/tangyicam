"use strict";
fetch("/bootstrap.json",{cache:"no-store"}).then(r=>{if(!r.ok)throw new Error();return r.json();}).then(s=>{
  document.getElementById("go").href=s.url;
  document.getElementById("fingerprint").textContent=s.fingerprint;
}).catch(()=>{document.getElementById("go").textContent="服務未啟動，請回 Blender 檢查";});
