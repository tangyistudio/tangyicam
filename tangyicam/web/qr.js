"use strict";
let adminToken = "", lastUrls = "";
const el = id => document.getElementById(id);
async function refresh() {
  try {
    const response = await fetch("/local-info", {cache:"no-store"});
    if (!response.ok) throw new Error("請從 Blender 的「顯示 QR」在這台電腦開啟");
    const info = await response.json();
    adminToken = info.admin_token;
    el("pair-code").textContent = info.expires_in ? info.code : "已過期";
    el("expires").textContent = info.expires_in ? "剩餘 " + Math.ceil(info.expires_in/60) + " 分鐘" : "請按下方按鈕重設配對碼";
    el("stat").textContent = info.phones ? "手機已連線，可開始運鏡" : "等待手機配對與連線";
    el("fingerprint").textContent = info.fingerprint;
    if (lastUrls !== info.url + info.help_url) {
      lastUrls = info.url + info.help_url;
      for (const [id, url] of [["help",info.help_url],["app",info.url]]) {
        el("url-"+id).textContent = url;
        if (id === "app") el("url-app").href = url;
        el("qr-"+id).replaceChildren();
        new QRCode(el("qr-"+id), {text:url,width:200,height:200});
      }
    }
  } catch (error) { el("stat").textContent = error.message || "服務未啟動，請回 Blender 重新啟動"; }
}
el("reset").addEventListener("click", async () => {
  if (!confirm("這會中斷目前手機，並撤銷所有配對。繼續？")) return;
  try {
    const r = await fetch("/local/rotate", {method:"POST", headers:{"X-TangyiCam-Admin":adminToken}});
    if (!r.ok) throw new Error();
    await refresh();
  } catch { el("stat").textContent = "重設失敗，請回 Blender 按「重設配對」"; }
});
refresh(); setInterval(refresh,2000);
