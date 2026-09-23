/* TangyiCam 手機端。純 JS，沒有框架。
 *
 * 陀螺儀 → 四元數：照 three.js DeviceOrientationControls 的公式。
 * 它算出來的是「相機」的姿態（看向 -Z、+Y 朝上），已經補過螢幕橫向，
 * Blender 那邊直接拿相對值用。
 *
 * 送出：每 1/30 秒一則 JSON（seq, q, mx, my, mz, zoom, boost, stab, horizon, mode, rec
 *      ＋ 一次性的 recenter / home / lens / shot / shade）。
 * 收到：二進位＝JPEG 畫面；文字＝遙測 JSON。
 */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  // ---------------- 狀態 ----------------
  const st = {
    seq: 0, q: null, mx: 0, my: 0, mz: 0, zoom: 0, boost: 1,
    stab: 3, horizon: false, mode: "WALK", rec: false, speed: 1.0, gain: 1.0, tscale: 1.0, slowFactor: 0.25,
    oneshot: {},          // 一次性欄位，送出一次就清掉
    gyroOn: false, swap: localStorage.getItem("tc.swap") === "1",
    ws: null, connected: false, lastTele: null, shots: null,
    frameCount: 0, lastFrameT: 0, viewFps: 0,
  };

  // ---------------- 四元數 ----------------
  const DEG = Math.PI / 180;
  function qFromEulerYXZ(x, y, z) {
    const c1 = Math.cos(x / 2), c2 = Math.cos(y / 2), c3 = Math.cos(z / 2);
    const s1 = Math.sin(x / 2), s2 = Math.sin(y / 2), s3 = Math.sin(z / 2);
    return [
      s1 * c2 * c3 + c1 * s2 * s3,
      c1 * s2 * c3 - s1 * c2 * s3,
      c1 * c2 * s3 - s1 * s2 * c3,
      c1 * c2 * c3 + s1 * s2 * s3,
    ]; // [x,y,z,w]
  }
  function qMul(a, b) {
    const [ax, ay, az, aw] = a, [bx, by, bz, bw] = b;
    return [
      ax * bw + aw * bx + ay * bz - az * by,
      ay * bw + aw * by + az * bx - ax * bz,
      az * bw + aw * bz + ax * by - ay * bx,
      aw * bw - ax * bx - ay * by - az * bz,
    ];
  }
  function qAxisZ(angle) { const h = angle / 2; return [0, 0, Math.sin(h), Math.cos(h)]; }
  const Q1 = [-Math.SQRT1_2, 0, 0, Math.SQRT1_2]; // -90° 繞 X：相機從螢幕背面看出去

  function screenAngle() {
    if (screen.orientation && typeof screen.orientation.angle === "number") return screen.orientation.angle;
    if (typeof window.orientation === "number") return window.orientation;
    return 0;
  }

  function onOrientation(e) {
    if (e.alpha == null || e.beta == null || e.gamma == null) return;
    let q = qFromEulerYXZ(e.beta * DEG, e.alpha * DEG, -e.gamma * DEG);
    q = qMul(q, Q1);
    q = qMul(q, qAxisZ(-screenAngle() * DEG));
    st.q = [q[3], q[0], q[1], q[2]]; // mathutils 的順序 [w,x,y,z]
  }

  async function enableGyro() {
    try {
      if (!window.isSecureContext || typeof DeviceOrientationEvent === "undefined") { toast("此瀏覽器無法使用陀螺儀，請用 iPhone Safari 的 HTTPS 頁面"); return false; }
      if (typeof DeviceOrientationEvent !== "undefined" && typeof DeviceOrientationEvent.requestPermission === "function") {
        const r = await DeviceOrientationEvent.requestPermission();
        if (r !== "granted") { toast("陀螺儀權限被拒絕"); return false; }
      }
      window.addEventListener("deviceorientation", onOrientation, true);
      st.gyroOn = true;
      setTimeout(() => { if(st.gyroOn && !st.q) toast("尚未收到陀螺儀資料，請檢查權限或改用搖桿"); },5000);
      $("#gyro").textContent = "陀螺儀開";
      return true;
    } catch (err) {
      toast("陀螺儀啟用失敗：" + err);
      return false;
    }
  }
  function disableGyro() {
    window.removeEventListener("deviceorientation", onOrientation, true);
    st.gyroOn = false; st.q = null;
    $("#gyro").textContent = "陀螺儀關";
  }

  // ---------------- WebSocket ----------------
  let reconnectTimer = null, retryDelay = 1000;
  function showPairing(message) {
    $("#pairing").classList.remove("hidden");
    $("#pair-error").textContent = message || "輸入電腦 Blender 面板或 QR 頁的配對碼";
    $("#conn").textContent = "等待配對";
  }
  function releaseControls() {
    st.mx = st.my = st.mz = st.zoom = 0;
    st.tscale = 1; st.rec = false; st.oneshot = {rec:false};
    if (st.ws && st.ws.readyState === WebSocket.OPEN) send();
    st.oneshot = {};
  }
  async function connect() {
    clearTimeout(reconnectTimer);
    if (document.hidden) return;
    try {
      const status = await fetch("/state", {cache:"no-store"});
      if (status.status === 401) { showPairing(); return; }
      if (!status.ok) throw new Error();
      $("#pairing").classList.add("hidden");
    } catch {
      $("#conn").textContent = "電腦未連線，重試中";
      reconnectTimer = setTimeout(connect, retryDelay);
      retryDelay = Math.min(10000,retryDelay*1.5);
      return;
    }
    const ws = new WebSocket("wss://" + location.host + "/ws");
    ws.binaryType = "blob";
    st.ws = ws;
    ws.onopen = () => {
      st.connected = true; retryDelay = 1000; st.seq = 0;
      st.oneshot.recenter = true;
      $("#conn").textContent = "已連線";
    };
    ws.onclose = () => {
      if (st.ws !== ws) return;
      releaseControls(); st.connected = false;
      $("#conn").textContent = "重連中；若另支手機使用中，請先中斷它";
      if (!document.hidden) {
        reconnectTimer = setTimeout(connect,retryDelay);
        retryDelay = Math.min(10000,retryDelay*1.5);
      }
    };
    ws.onerror = () => {};
    ws.onmessage = ev => {
      if (ev.data instanceof Blob) return showFrame(ev.data);
      try { onTele(JSON.parse(ev.data)); } catch {}
    };
  }
  $("#pair-form").addEventListener("submit", async event => {
    event.preventDefault();
    const button = $("#pair-submit"); button.disabled = true;
    try {
      const r = await fetch("/pair", {method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({code:$("#pair-code").value.trim()})});
      const data = await r.json();
      if (!r.ok) {
        const messages = {too_many_attempts:"嘗試過多，請等一分鐘再試",expired_code:"配對碼過期，請在電腦重設",invalid_code:"配對碼不正確或已使用，請查看電腦最新的配對碼",session_limit:"配對數已滿，請在電腦重設配對"};
        showPairing(messages[data.error] || "配對失敗，請回電腦確認服務"); return;
      }
      $("#pair-code").value = "";
      await connect();
    } catch { showPairing("連不到電腦，請確認同一 Wi-Fi 與憑證設定"); }
    finally { button.disabled = false; }
  });
  $("#btn-unpair").addEventListener("click",async()=>{
    releaseControls();
    try { await fetch("/unpair",{method:"POST"}); } catch {}
    if(st.ws) st.ws.close(); showPairing("已解除配對");
  });
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden){releaseControls();clearTimeout(reconnectTimer);if(st.ws)st.ws.close();}
    else {connect(); if(navigator.wakeLock)navigator.wakeLock.request("screen").catch(()=>{});}
  });
  window.addEventListener("pagehide",()=>{releaseControls();if(st.ws)st.ws.close();});
  window.addEventListener("blur",releaseControls);

  let lastUrl = null;
  const view = $("#view");
  function showFrame(blob) {
    const url = URL.createObjectURL(blob);
    view.src = url;
    if (lastUrl) URL.revokeObjectURL(lastUrl);
    lastUrl = url;
    $("#noview").classList.add("hidden");
    const t = performance.now();
    if (st.lastFrameT) st.viewFps = st.viewFps * 0.9 + (1000 / (t - st.lastFrameT)) * 0.1;
    st.lastFrameT = t;
  }

  function onTele(t) {
    if (t.t !== "tele") return;
    st.lastTele = t;
    st.rec = !!t.rec;
    $("#fps").textContent = Math.round(st.viewFps || 0);
    $("#lens").textContent = t.lens;
    $("#shot-id").textContent = t.shot ? "鏡 " + t.shot : "自由";
    $("#shot-meta").textContent = t.shot ? `${t.shot_size || ""} ${t.shot_dur ? "⏱ " + t.shot_dur + '"' : ""} ${t.shot_title || ""}`.trim() : "未選鏡";
    const rec = !!t.rec;
    $("#rec-ind").classList.toggle("hidden", !rec);
    $("#btn-rec").classList.toggle("on", rec);
    $("#btn-rec").textContent = rec ? "■" : "●";
    $("#remain").textContent = (rec && t.remain != null) ? " " + t.remain.toFixed(1) + '"' : (rec ? " " + t.frame : "");
    $("#rec-text").textContent = rec ? "REC t" + (t.take || "") + (t.slow ? " 慢" : "") : "";
    $("#shell").textContent = t.shell ? " · 藏殼" + t.shell : "";
    // 機位列：目前格、已記的機位刻度
    const kr = $("#keyrow");
    kr.classList.toggle("hidden", !t.shot);
    if (t.shot) {
      $("#frame-v").textContent = t.frame;
      $("#keys-v").textContent = (t.keys || []).length ? (t.keys || []).join("·") : "—";
      const a = t.shot_start, b = t.shot_end;
      if (a != null && b != null && !rec && document.activeElement !== $("#scrub")) $("#scrub").value = ((t.frame - a) / Math.max(1, b - a)).toFixed(3);
      const ticks = $("#keyticks"); ticks.innerHTML = "";
      for (const f of (t.keys || [])) { const d = document.createElement("i"); d.style.left = (100 * (f - a) / Math.max(1, b - a)) + "%"; ticks.appendChild(d); }
    }
    // Blender 面板改的檔位要同步回手機
    if (t.stab !== st.stab) { st.stab = t.stab; paintStab(); }
    if (!!t.horizon !== st.horizon) { st.horizon = !!t.horizon; paintStab(); }
    if (t.mode && t.mode !== st.mode) { st.mode = t.mode; paintMode(); }
    $("#diag").textContent = `cam ${t.cam} · loc ${t.loc} · tick ${t.fps} · 預覽 ${t.prev_ms}ms · 手機 ${t.phones}`;
    if (t.msg && t.msg !== onTele.lastMsg) { onTele.lastMsg = t.msg; toast(t.msg); }
  }

  function send() {
    if (!st.ws || st.ws.readyState !== 1) return;
    const p = {
      seq: st.seq++, q: st.q,
      mx: st.mx, my: st.my, mz: st.mz, zoom: st.zoom, boost: st.boost,
      stab: st.stab, horizon: st.horizon, mode: st.mode, speed: st.speed, gain: st.gain, tscale: st.tscale,
    };
    for (const k in st.oneshot) p[k] = st.oneshot[k];
    st.oneshot = {};
    st.ws.send(JSON.stringify(p));
  }
  setInterval(send, 1000 / 60);

  // ---------------- 搖桿 ----------------
  // 指數曲線：中心附近細、推到底才快。站著微調機位靠這個。
  const expo = (v) => Math.sign(v) * Math.pow(Math.abs(v), 1.8);
  // 推到底＝瞬間加速：一格斷層，不是斜坡。97% 進、90% 出（遲滯，避免邊緣抖動）
  const EDGE_BOOST = 3.5;
  let edgeOn = false;
  const edgeMult = (x, y) => { const m = Math.hypot(x, y); if (m >= 0.97) edgeOn = true; else if (m < 0.90) edgeOn = false; return edgeOn ? EDGE_BOOST : 1; };
  function makeStick(el, onMove) {
    const knob = el.querySelector(".knob");
    let id = null, cx = 0, cy = 0, R = 0;
    const set = (x, y) => { knob.style.transform = `translate(${x * R}px, ${y * R}px)`; onMove(x, -y); knob.classList.toggle("edge", edgeOn && Math.hypot(x, y) > 0.5); };
    el.addEventListener("touchstart", (e) => {
      if (id !== null) return;
      const t = e.changedTouches[0]; id = t.identifier;
      const r = el.getBoundingClientRect(); cx = r.left + r.width / 2; cy = r.top + r.height / 2; R = r.width / 2 - 20;
      e.preventDefault();
    }, { passive: false });
    const move = (e) => {
      for (const t of e.changedTouches) {
        if (t.identifier !== id) continue;
        let x = (t.clientX - cx) / R, y = (t.clientY - cy) / R;
        const m = Math.hypot(x, y); if (m > 1) { x /= m; y /= m; }
        set(x, y); e.preventDefault();
      }
    };
    const end = (e) => { for (const t of e.changedTouches) if (t.identifier === id) { id = null; set(0, 0); } };
    el.addEventListener("touchmove", move, { passive: false });
    el.addEventListener("touchend", end); el.addEventListener("touchcancel", end);
    // 桌機測試用滑鼠
    let down = false;
    el.addEventListener("mousedown", (e) => { down = true; const r = el.getBoundingClientRect(); cx = r.left + r.width / 2; cy = r.top + r.height / 2; R = r.width / 2 - 20; });
    window.addEventListener("mousemove", (e) => { if (!down) return; let x = (e.clientX - cx) / R, y = (e.clientY - cy) / R; const m = Math.hypot(x, y); if (m > 1) { x /= m; y /= m; } set(x, y); });
    window.addEventListener("mouseup", () => { if (down) { down = false; set(0, 0); } });
  }
  function bindSticks() {
    const L = $("#stick-l"), Rr = $("#stick-r");
    const moveFn = (x, y) => { const k = edgeMult(x, y); st.mx = expo(x) * k; st.my = expo(y) * k; };
    const liftFn = (x, y) => { const k = edgeMult(0, y); st.mz = expo(y) * k; st.zoom = Math.abs(x) > 0.25 ? expo(x) : 0; };
    makeStick(L, st.swap ? liftFn : moveFn);
    makeStick(Rr, st.swap ? moveFn : liftFn);
  }

  // ---------------- 按鈕 ----------------
  function paintStab() {
    $$("#stab-row .chip[data-stab]").forEach((b) => b.classList.toggle("on", +b.dataset.stab === st.stab));
    $("#btn-horizon").classList.toggle("on", st.horizon);
  }
  function paintMode() { $$("[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === st.mode)); }
  function toast(s) { const m = $("#msg"); m.textContent = s; m.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => m.classList.remove("show"), 1800); }

  $$("#stab-row .chip[data-stab]").forEach((b) => b.addEventListener("click", () => { st.stab = +b.dataset.stab; paintStab(); }));
  $("#btn-horizon").addEventListener("click", () => { st.horizon = !st.horizon; paintStab(); });
  $$("[data-lens]").forEach((b) => b.addEventListener("click", () => { st.oneshot.lens = +b.dataset.lens; $$("[data-lens]").forEach((x) => x.classList.toggle("on", x === b)); }));
  $$("[data-mode]").forEach((b) => b.addEventListener("click", () => { st.mode = b.dataset.mode; paintMode(); }));
  $$("[data-shade]").forEach((b) => b.addEventListener("click", () => { st.oneshot.shade = b.dataset.shade; $$("[data-shade]").forEach((x) => x.classList.toggle("on", x === b)); }));
  $("#btn-rec").addEventListener("click", () => { st.rec = !st.rec; st.oneshot.rec = st.rec; });
  // 長按＝慢動作（新 iPhone 沒有壓力感應，用按住時間）；放開＝回實速
  const slowBtn = $("#btn-slow");
  const slowOn = (e) => { st.tscale = st.slowFactor; slowBtn.classList.add("on"); e.preventDefault(); };
  const slowOff = () => { st.tscale = 1.0; slowBtn.classList.remove("on"); };
  slowBtn.addEventListener("touchstart", slowOn, { passive: false });
  slowBtn.addEventListener("touchend", slowOff); slowBtn.addEventListener("touchcancel", slowOff);
  slowBtn.addEventListener("mousedown", slowOn); window.addEventListener("mouseup", slowOff);
  // 機位關鍵影格：時間滑桿拉到該鏡的某一格 → ＋機位；串接＝接成整條運鏡線
  $("#scrub").addEventListener("input", (e) => { st.oneshot.scrub = +e.target.value; });
  $("#btn-key-add").addEventListener("click", () => { st.oneshot.key = { cmd: "add" }; });
  $("#btn-key-del").addEventListener("click", () => { st.oneshot.key = { cmd: "del" }; });
  $("#btn-key-build").addEventListener("click", () => { st.oneshot.key = { cmd: "build" }; });
  $("#btn-key-export").addEventListener("click", () => { st.oneshot.key = { cmd: "export" }; toast("輸出中，Blender 會卡幾秒"); });
  let keyIdx = 0;
  $("#btn-key-prev").addEventListener("click", () => { keyIdx = Math.max(0, keyIdx - 1); st.oneshot.key = { cmd: "goto", arg: keyIdx }; });
  $("#btn-key-next").addEventListener("click", () => { keyIdx = keyIdx + 1; st.oneshot.key = { cmd: "goto", arg: keyIdx }; });
  $("#slow").addEventListener("input", (e) => { st.slowFactor = +e.target.value; $("#slow-v").textContent = "×" + st.slowFactor.toFixed(2); });
  $("#btn-recenter").addEventListener("click", () => { st.oneshot.recenter = true; toast("歸零"); });
  $("#btn-home").addEventListener("click", () => { st.oneshot.home = true; });
  $("#btn-boost").addEventListener("click", (e) => { st.boost = st.boost > 1 ? 1 : 2; e.currentTarget.classList.toggle("on", st.boost > 1); });
  $("#btn-shots").addEventListener("click", () => { $("#drawer").classList.remove("hidden"); loadShots(); });
  $("#btn-drawer-close").addEventListener("click", () => $("#drawer").classList.add("hidden"));
  $("#btn-menu").addEventListener("click", () => $("#menu").classList.remove("hidden"));
  $("#btn-menu-close").addEventListener("click", () => $("#menu").classList.add("hidden"));
  $("#speed").addEventListener("input", (e) => { st.speed = +e.target.value; $("#speed-v").textContent = "×" + st.speed.toFixed(1); });
  $("#gain").addEventListener("input", (e) => { st.gain = +e.target.value; $("#gain-v").textContent = "×" + st.gain.toFixed(1); });
  $("#btn-gyro-on").addEventListener("click", enableGyro);
  $("#btn-gyro-off").addEventListener("click", disableGyro);
  $("#btn-swap").addEventListener("click", (e) => { st.swap = !st.swap; localStorage.setItem("tc.swap", st.swap ? "1" : "0"); releaseControls(); location.reload(); });

  $("#btn-rotate-skip").addEventListener("click", () => $("#rotate").classList.add("skip"));
  $("#btn-gate").addEventListener("click", async () => { if (await enableGyro()) closeGate(); });
  $("#btn-gate-nogyro").addEventListener("click", closeGate);
  function closeGate() {
    $("#gate").classList.add("hidden");
    if (navigator.wakeLock) navigator.wakeLock.request("screen").catch(() => { });
    st.oneshot.recenter = true;
  }

  // ---------------- 鏡表 ----------------
  async function loadShots() {
    try {
      const r = await fetch("/shots.json", { cache: "no-store" });
      if (!r.ok) throw new Error();
      st.shots = await r.json();
      if (!Array.isArray(st.shots.shots)) throw new Error();
    } catch (e) { st.shots = { shots: [] }; }
    const list = $("#shot-list"); list.innerHTML = "";
    const cur = st.lastTele && st.lastTele.shot;
    let unit = null;
    if (!st.shots.shots.length) { list.innerHTML = '<div class="unit-head">Blender 面板還沒載入鏡表</div>'; return; }
    for (const s of st.shots.shots) {
      if (s.unit && s.unit !== unit) { unit = s.unit; const h = document.createElement("div"); h.className = "unit-head"; h.textContent = "【" + unit + "】"; list.appendChild(h); }
      const d = document.createElement("div");
      d.className = "shot" + (s.id === cur ? " on" : "");
      for (const [cls, text] of [["sid",s.id],["st",[s.size,s.title].filter(Boolean).join(" ")],["sd",[s.dur != null ? s.dur + "秒" : "",s.lens ? s.lens+"mm" : ""].join(" ")],["pin",s.pose ? "📍" : ""]]) { const span=document.createElement("span");span.className=cls;span.textContent=text;d.appendChild(span); }
      d.addEventListener("click", () => { st.oneshot.shot = s.id; $("#drawer").classList.add("hidden"); toast("鏡 " + s.id); });
      list.appendChild(d);
    }
  }

  // ---------------- 啟動 ----------------
  bindSticks(); paintStab(); paintMode();
  $$("[data-shade]")[0].classList.add("on");
  connect();
})();

/* PATCH_V02_DONE */

/* PATCH_V02B_DONE */
