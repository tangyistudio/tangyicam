# -*- coding: utf-8 -*-
"""相機數學、穩定器、錄製。全部在 Blender 主執行緒的 app timer 裡跑。

手機送來的是「裝置的絕對姿態」四元數（three.js DeviceOrientation 公式算出，
已經處理過螢幕橫向；它的座標慣例＝相機看向 -Z、+Y 朝上，跟 Blender 相機
的區域座標一模一樣）。我們不用世界座標對齊，只算**相對於 Recenter 那一刻的
區域旋轉**：

    q_rel = q_base⁻¹ · q_now
    cam_rot = cam_base_rot · q_rel

這條式子跟手機世界與 Blender 世界之間的偏航差無關，所以指北針亂飄也沒差。

穩定器（stab 0–5）：
- 旋轉：目標四元數與目前平滑值做 slerp，α = 1 − exp(−dt/τ)。
- 位置：同樣的指數平滑。
- 死區：兩個四元數夾角小於門檻就當作沒動，把手的細抖濾掉。
- 水平鎖（horizon）：把 roll 拿掉，等於三軸穩定器的 roll 軸鎖死。
τ 越大越像掛在穩定器上；0 檔＝關閉，手機怎麼動相機就怎麼動。
"""

import math
import threading
import time

import bpy
from .studio import curves as action_curves
from mathutils import Matrix, Quaternion, Vector

# 檔位 → (旋轉 τ 秒, 位置 τ 秒, 死區角度°)
STAB_LEVELS = {
    0: (0.0, 0.0, 0.0),
    1: (0.04, 0.04, 0.03),
    2: (0.08, 0.08, 0.06),
    3: (0.14, 0.12, 0.10),
    4: (0.25, 0.20, 0.15),
    5: (0.45, 0.35, 0.25),
}
# 自適應：角速度越大，平滑越少（1€ filter 的想法）。大幅度甩鏡不拖尾，
# 靜止時細抖照樣被吃掉。ADAPT 是每 1°/tick 減少多少 τ 的比例。
STAB_ADAPT = 0.35
MODE_SPEED = {"WALK": 1.0, "FPV": 2.5, "DOLLY": 1.0}
LENS_MIN, LENS_MAX = 8.0, 300.0

# ---------------------------------------------------------------------------
# 手機最新狀態（網路執行緒寫、主執行緒讀，鎖保護）
# ---------------------------------------------------------------------------
lock = threading.Lock()
state = {
    "q": None,          # [w,x,y,z] 手機絕對姿態；None＝陀螺儀沒開
    "mx": 0.0, "my": 0.0, "mz": 0.0,   # 搖桿 [-1,1]
    "boost": 1.0,
    "speed": 1.0,        # 手機的移動速度倍率
    "tscale": 1.0,       # 慢動作：角色動畫相對真實時間的速率（長按時 0.25）
    "gain": 1.0,         # 轉向倍率：手機轉 30°、相機轉 30°×gain
    "stab": 3,
    "horizon": False,
    "mode": "WALK",
    "lens": None,        # 一次性：手機要求的絕對焦段
    "zoom": 0.0,         # 連續：焦段變化率 [-1,1]
    "recenter": False,   # 一次性
    "rec": None,         # None＝沒表態；True/False＝手機 REC 鈕的狀態
    "shot": None,        # 一次性：手機選了某顆鏡
    "shade": None,       # 一次性：SOLID / MATERIAL / RENDERED / WIREFRAME
    "scrub": None,       # 一次性：0–1，把時間軸拉到該鏡的這個位置
    "key_cmd": None,     # 一次性：("add"|"del"|"build"|"goto", 參數)
    "home": False,       # 一次性：回到啟動時的機位
    "seq": 0,
    "last_seen": 0.0,
}

# 主執行緒私有
rt = {
    "q_base": None,        # Recenter 時的手機姿態
    "cam_base_rot": None,  # Recenter 時的相機旋轉（Quaternion）
    "smooth_q": None,      # 穩定器輸出（旋轉）
    "smooth_p": None,      # 穩定器輸出（位置）
    "raw_p": None,         # 搖桿意圖的積分（未平滑）；smooth_p 追著它走
    "home_matrix": None,   # 啟動時的相機矩陣
    "home_lens": 50.0,
    "last_tick": 0.0,
    "fps": 0.0,
    "driving": "",         # 目前被驅動的相機物件名
    # 錄製
    "recording": False,
    "rec_cam": "",
    "rec_start_frame": 1,
    "rec_end_frame": None,
    "rec_t0": 0.0,
    "rec_last_frame": -1,
    "rec_sf": 0.0,         # 角色動畫的場景格（浮點，慢動作時走得慢）
    "rec_slow": False,     # 目前是否在慢動作中（做進出標記用）
    "shell_hidden": [],    # 因相機在外面而被藏起來的外殼物件名
    "rec_shot": None,
    "rec_take": 0,
    "rec_phone": None,     # 上一次看到的手機 REC 狀態（做邊緣觸發）
    "takes": [],           # [(cam_name, shot_id, frames)]
    "current_shot": None,  # dict
    "shots": {"fps": 24, "shots": []},
    "message": "",
}


def apply_payload(p):
    """網路執行緒：把一則手機訊息合併進 state。"""
    with lock:
        seq = p.get("seq")
        if isinstance(seq, int):
            state["seq"] = seq
        q = p.get("q")
        if isinstance(q, (list, tuple)) and len(q) == 4:
            try:
                state["q"] = [float(v) for v in q]
            except (TypeError, ValueError):
                state["q"] = None
        elif "q" in p:
            state["q"] = None
        for k in ("mx", "my", "mz", "boost", "zoom"):
            if k in p:
                try:
                    state[k] = max(1.0, min(4.0, float(p[k]))) if k == "boost" else max(-1.0, min(1.0, float(p[k]))) if k == "zoom" else max(-4.0, min(4.0, float(p[k])))
                except (TypeError, ValueError):
                    pass
        for k, lo, hi in (("speed", 0.1, 8.0), ("gain", 0.5, 3.0), ("tscale", 0.05, 1.0)):
            if k in p:
                try:
                    state[k] = max(lo, min(hi, float(p[k])))
                except (TypeError, ValueError):
                    pass
        if "stab" in p:
            try:
                state["stab"] = max(0, min(5, int(p["stab"])))
            except (TypeError, ValueError):
                pass
        if "horizon" in p:
            state["horizon"] = bool(p["horizon"])
        if p.get("mode") in MODE_SPEED:
            state["mode"] = p["mode"]
        if "lens" in p:
            try:
                state["lens"] = max(LENS_MIN, min(LENS_MAX, float(p["lens"])))
            except (TypeError, ValueError):
                pass
        if p.get("shade") in ("SOLID", "MATERIAL", "RENDERED", "WIREFRAME"):
            state["shade"] = p["shade"]
        for flag in ("recenter", "home"):
            if p.get(flag):
                state[flag] = True
        if "rec" in p:
            state["rec"] = p["rec"] if type(p["rec"]) is bool else None
        if isinstance(p.get("shot"), str):
            state["shot"] = p["shot"][:32]
        if "scrub" in p:
            try:
                state["scrub"] = max(0.0, min(1.0, float(p["scrub"])))
            except (TypeError, ValueError):
                pass
        kc = p.get("key")
        if isinstance(kc, dict) and kc.get("cmd") in ("add", "del", "build", "goto", "export"):
            state["key_cmd"] = (kc["cmd"], kc.get("arg"))
        state["last_seen"] = time.time()


def phone_seen(within=3.0):
    with lock:
        return (time.time() - state["last_seen"]) < within


# ---------------------------------------------------------------------------
# 相機取得／建立
# ---------------------------------------------------------------------------
DRIVER = "TC_CAM"


def driven_camera(scene):
    """被手機驅動的相機。

    錄製中＝那一個 take 的相機；平常＝一台永遠乾淨（沒有動畫資料）的 TC_CAM。
    每個 take 都是獨立的相機物件＋自己的 action，錄完 TC_CAM 停在 take 結束的
    機位，方便微調再錄下一個。
    """
    if rt["recording"] and rt["rec_cam"] in bpy.data.objects:
        return bpy.data.objects[rt["rec_cam"]]
    cam = bpy.data.objects.get(DRIVER)
    if cam is None or cam.type != "CAMERA":
        data = bpy.data.cameras.new(DRIVER)
        cam = bpy.data.objects.new(DRIVER, data)
        scene.collection.objects.link(cam)
        src = scene.camera
        if src is not None and src.type == "CAMERA":
            cam.matrix_world = src.matrix_world.copy()
            cam.data.lens = src.data.lens
        else:
            cam.location = (0.0, -4.0, 1.6)
            cam.rotation_euler = (math.radians(90), 0.0, 0.0)
    elif cam.name not in scene.objects:
        scene.collection.objects.link(cam)
    if cam.animation_data:
        cam.animation_data_clear()
    if cam.data.animation_data:
        cam.data.animation_data_clear()
    if cam.rotation_mode != "QUATERNION":
        # 用四元數錄，插值才不會在 ±180° 打結
        q = cam.matrix_world.to_quaternion()
        cam.rotation_mode = "QUATERNION"
        cam.rotation_quaternion = q
    if scene.camera is not cam:
        scene.camera = cam
    return cam


def _cam_rot(cam):
    return cam.matrix_world.to_quaternion()


def recenter(cam):
    with lock:
        q = state["q"]
    rt["q_base"] = Quaternion(q) if q else None
    rt["cam_base_rot"] = _cam_rot(cam)
    rt["smooth_q"] = rt["cam_base_rot"].copy()
    rt["smooth_p"] = cam.matrix_world.translation.copy()
    rt["raw_p"] = rt["smooth_p"].copy()


def set_home(cam):
    rt["home_matrix"] = cam.matrix_world.copy()
    rt["home_lens"] = cam.data.lens


# ---------------------------------------------------------------------------
# 每 tick
# ---------------------------------------------------------------------------
def tick(scene):
    """由 app timer 每 1/60 秒呼叫一次。回傳遙測 dict 給手機。"""
    now = time.perf_counter()
    dt = now - rt["last_tick"] if rt["last_tick"] else 1.0 / 60.0
    dt = max(1e-3, min(0.1, dt))
    rt["last_tick"] = now
    rt["fps"] = rt["fps"] * 0.9 + (1.0 / dt) * 0.1

    cam = driven_camera(scene)
    rt["driving"] = cam.name
    if rt["home_matrix"] is None:
        set_home(cam)

    with lock:
        q = list(state["q"]) if state["q"] else None
        mx, my, mz = state["mx"], state["my"], state["mz"]
        boost = state["boost"] * state["speed"]
        gain = state["gain"]
        tscale = state["tscale"]
        stab = state["stab"]
        horizon = state["horizon"]
        mode = state["mode"]
        lens_set, state["lens"] = state["lens"], None
        zoom = state["zoom"]
        do_recenter, state["recenter"] = state["recenter"], False
        do_home, state["home"] = state["home"], False
        rec_req, state["rec"] = state["rec"], None
        shot_pick, state["shot"] = state["shot"], None
        shade, state["shade"] = state["shade"], None
        scrub, state["scrub"] = state["scrub"], None
        key_cmd, state["key_cmd"] = state["key_cmd"], None
        seen = (time.time() - state["last_seen"]) < 0.5

    if not seen:
        mx = my = mz = zoom = 0.0  # A lost phone must not keep the camera moving.
        if rt["recording"] and rt.get("rec_requires_phone"):
            record_stop(scene)
            rt["rec_phone"] = None
            rec_req = None
            cam = driven_camera(scene)
            rt["message"] = "手機訊號中斷，已停止錄製"

    if shot_pick is not None:
        select_shot(scene, cam, shot_pick)
    if scrub is not None and not rt["recording"]:
        scrub_shot(scene, scrub)
    if key_cmd is not None and not rt["recording"]:
        key_command(scene, cam, key_cmd[0], key_cmd[1])
    if do_home and rt["home_matrix"] is not None:
        cam.matrix_world = rt["home_matrix"].copy()
        cam.data.lens = rt["home_lens"]
        recenter(cam)
    if do_recenter or rt["q_base"] is None and q is not None:
        recenter(cam)
        # recenter 只重設「手機的零點」，相機留在原地
    if rt["smooth_q"] is None:
        rt["smooth_q"] = _cam_rot(cam)
        rt["smooth_p"] = cam.matrix_world.translation.copy()
    if rt["raw_p"] is None:
        rt["raw_p"] = rt["smooth_p"].copy()

    # ---- 目標旋轉 ----------------------------------------------------------
    target_q = rt["smooth_q"].copy()
    if q is not None and rt["q_base"] is not None and rt["cam_base_rot"] is not None:
        q_now = Quaternion(q)
        q_rel = rt["q_base"].inverted() @ q_now
        if abs(gain - 1.0) > 1e-3:
            axis, ang = q_rel.to_axis_angle()
            q_rel = Quaternion(axis, ang * gain)
        target_q = rt["cam_base_rot"] @ q_rel
    if horizon:
        target_q = _remove_roll(target_q)

    # ---- 穩定器 -------------------------------------------------------------
    tau_r, tau_p, dead = STAB_LEVELS.get(stab, STAB_LEVELS[3])
    if tau_r <= 0.0:
        rt["smooth_q"] = target_q
    else:
        ang = math.degrees(rt["smooth_q"].rotation_difference(target_q).angle)
        if ang > dead:
            tau = tau_r / (1.0 + STAB_ADAPT * ang)
            a = 1.0 - math.exp(-dt / tau)
            rt["smooth_q"] = rt["smooth_q"].slerp(target_q, a)

    # ---- 平移（搖桿）-------------------------------------------------------
    speed = MODE_SPEED.get(mode, 1.0) * boost * _prop(scene, "move_speed", 1.5)
    rot = rt["smooth_q"]
    track = _prop(scene, "track", None) if mode == "DOLLY" else None
    if track is not None and track.type == "CURVE":
        # 軌道模式：左搖桿前後＝沿曲線滑，左右＝離軌道的橫向偏移，右搖桿上下＝高度偏移
        target_p = _dolly_target(scene, track, mx, my, mz, speed, dt)
        rt["raw_p"] = target_p.copy()
    else:
        fwd = rot @ Vector((0.0, 0.0, -1.0))
        right = rot @ Vector((1.0, 0.0, 0.0))
        if mode != "FPV":
            fwd.z = 0.0
            right.z = 0.0
            if fwd.length > 1e-6:
                fwd.normalize()
            if right.length > 1e-6:
                right.normalize()
            up = Vector((0.0, 0.0, 1.0))
        else:
            up = rot @ Vector((0.0, 1.0, 0.0))
        delta = (right * mx + fwd * my + up * mz) * speed * dt
        # 意圖先積分，平滑只負責「追」——不然速度會被穩定器吃掉
        rt["raw_p"] = _clamp_bounds(scene, rt["raw_p"] + delta)
        target_p = rt["raw_p"]
        rt["dolly"] = None
    if tau_p <= 0.0:
        rt["smooth_p"] = target_p
    else:
        a = 1.0 - math.exp(-dt / tau_p)
        rt["smooth_p"] = rt["smooth_p"].lerp(target_p, a)

    # ---- 套用 ---------------------------------------------------------------
    if cam.parent is None:
        cam.rotation_quaternion = rt["smooth_q"]
        cam.location = rt["smooth_p"]
    else:
        m = Matrix.Translation(rt["smooth_p"]) @ rt["smooth_q"].to_matrix().to_4x4()
        cam.matrix_world = m

    _update_shell(scene, rt["smooth_p"])

    # ---- 焦段 ---------------------------------------------------------------
    if lens_set is not None:
        cam.data.lens = lens_set
    elif abs(zoom) > 0.02:
        # 以「每秒一級」的對數速率變焦，長焦短焦手感一致
        cam.data.lens = max(LENS_MIN, min(LENS_MAX, cam.data.lens * math.exp(zoom * dt * 0.9)))

    if shade and _view3d_space() is not None:
        try:
            _view3d_space().shading.type = shade
        except Exception:
            pass

    # ---- 錄製 ---------------------------------------------------------------
    _resolve_record(scene, cam, rec_req)
    if rt["recording"]:
        cam = driven_camera(scene)  # REC may have created a new take this tick.
        _record_tick(scene, cam, now, dt, tscale)

    return telemetry(scene, cam, seen)


def _sample_track(scene, track):
    """把曲線物件取樣成世界座標折線＋累積弧長。每兩秒重取一次，曲線被改也跟得上。"""
    d = rt.get("dolly")
    now = time.perf_counter()
    if d and d["name"] == track.name and now - d["t"] < 2.0:
        return d
    dg = bpy.context.evaluated_depsgraph_get()
    ob = track.evaluated_get(dg)
    me = ob.to_mesh()
    try:
        pts = [ob.matrix_world @ v.co for v in me.vertices]
    finally:
        ob.to_mesh_clear()
    if len(pts) < 2:
        return None
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + (b - a).length)
    s = d["s"] if d and d["name"] == track.name else None
    lat = d["lat"] if d and d["name"] == track.name else 0.0
    hgt = d["hgt"] if d and d["name"] == track.name else 0.0
    if s is None:
        # 進軌道模式：從離相機最近的軌道點開始，不會瞬移
        p0 = rt["smooth_p"]
        best, s = 1e18, 0.0
        for i, p in enumerate(pts):
            dd = (p - p0).length_squared
            if dd < best:
                best, s = dd, cum[i]
    d = {"name": track.name, "pts": pts, "cum": cum, "len": cum[-1], "s": s, "lat": lat, "hgt": hgt, "t": now}
    rt["dolly"] = d
    return d


def _dolly_target(scene, track, mx, my, mz, speed, dt):
    d = _sample_track(scene, track)
    if d is None:
        return rt["smooth_p"]
    d["s"] = max(0.0, min(d["len"], d["s"] + my * speed * dt))
    d["lat"] += mx * speed * dt * 0.5
    d["hgt"] += mz * speed * dt * 0.5
    cum, pts = d["cum"], d["pts"]
    # 二分找段
    lo, hi = 0, len(cum) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if cum[mid] <= d["s"]:
            lo = mid
        else:
            hi = mid
    seg = cum[hi] - cum[lo]
    t = (d["s"] - cum[lo]) / seg if seg > 1e-9 else 0.0
    pos = pts[lo].lerp(pts[hi], t)
    tang = pts[hi] - pts[lo]
    tang.z = 0.0
    right = Vector((tang.y, -tang.x, 0.0))
    if right.length > 1e-6:
        right.normalize()
    return pos + right * d["lat"] + Vector((0.0, 0.0, d["hgt"]))


def _bounds(scene):
    p = getattr(scene, "tangyicam", None)
    if p is None or not p.bounds_set:
        return None
    return (p.bounds_min, p.bounds_max)


def _clamp_bounds(scene, v):
    """相機鎖在房間裡：座標夾在邊界盒內（含安全距離）。"""
    p = getattr(scene, "tangyicam", None)
    b = _bounds(scene)
    if b is None or not p.bounds_clamp:
        return v
    m = p.bounds_margin
    lo, hi = b
    return Vector((max(lo[0] + m, min(hi[0] - m, v.x)),
                   max(lo[1] + m, min(hi[1] - m, v.y)),
                   max(lo[2] + m, min(hi[2] - m, v.z))))


def _update_shell(scene, pos):
    """相機在房間外面時，把它那一側的外殼（天花板／牆）藏起來；回來就恢復。

    外殼＝名字以 shell_prefix 列出的前綴開頭的物件（預設 CEILING, WALL, FLOOR）。
    每片殼依它的中心相對邊界盒中心落在哪一側（±X ±Y ±Z 取相對距離最大者）決定歸屬。
    """
    p = getattr(scene, "tangyicam", None)
    b = _bounds(scene)
    if p is None or b is None or not p.shell_hide:
        if rt["shell_hidden"]:
            _restore_shell()
        return
    lo, hi = b
    c = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2))
    half = Vector(((hi[0] - lo[0]) / 2, (hi[1] - lo[1]) / 2, (hi[2] - lo[2]) / 2))
    out = set()
    if pos.x > hi[0]:
        out.add("+x")
    if pos.x < lo[0]:
        out.add("-x")
    if pos.y > hi[1]:
        out.add("+y")
    if pos.y < lo[1]:
        out.add("-y")
    if pos.z > hi[2]:
        out.add("+z")
    if pos.z < lo[2]:
        out.add("-z")
    prefixes = [s.strip().upper() for s in p.shell_prefix.split(",") if s.strip()]
    want_hidden = set()
    if out:
        for o in scene.objects:
            if o.type != "MESH" or not any(o.name.upper().startswith(pf) for pf in prefixes):
                continue
            d = o.matrix_world.translation - c
            rel = [(abs(d.x) / max(half.x, 1e-6), "+x" if d.x > 0 else "-x"),
                   (abs(d.y) / max(half.y, 1e-6), "+y" if d.y > 0 else "-y"),
                   (abs(d.z) / max(half.z, 1e-6), "+z" if d.z > 0 else "-z")]
            side = max(rel)[1]
            if side in out:
                want_hidden.add(o.name)
    cur = set(rt["shell_hidden"])
    for n in cur - want_hidden:
        o = bpy.data.objects.get(n)
        if o is not None:
            o.hide_set(False)
    for n in want_hidden - cur:
        o = bpy.data.objects.get(n)
        if o is not None:
            o.hide_set(True)
    rt["shell_hidden"] = sorted(want_hidden)


def _restore_shell():
    for n in rt["shell_hidden"]:
        o = bpy.data.objects.get(n)
        if o is not None:
            o.hide_set(False)
    rt["shell_hidden"] = []


def grab_bounds(scene):
    """從場景所有網格抓包圍盒，再縮進去外殼厚度（取最薄那片殼的厚度）。"""
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    p = scene.tangyicam
    prefixes = [s.strip().upper() for s in p.shell_prefix.split(",") if s.strip()]
    thick = 1e9
    n = 0
    for o in scene.objects:
        if o.type != "MESH" or o.name.startswith("TC_"):
            continue
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
            hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
        n += 1
        if any(o.name.upper().startswith(pf) for pf in prefixes):
            thick = min(thick, min(o.dimensions))
    if n == 0:
        return False
    t = thick if thick < 1.0 else 0.0
    p.bounds_min = (lo.x + t, lo.y + t, lo.z + t)
    p.bounds_max = (hi.x - t, hi.y - t, hi.z - t)
    p.bounds_set = True
    return True


def _prop(scene, name, default):
    props = getattr(scene, "tangyicam", None)
    return getattr(props, name, default) if props else default


def _remove_roll(q):
    """把相機的 roll 拿掉：保留視線方向，讓相機的 X 軸回到水平。"""
    fwd = q @ Vector((0.0, 0.0, -1.0))
    world_up = Vector((0.0, 0.0, 1.0))
    if abs(fwd.dot(world_up)) > 0.999:
        return q
    right = fwd.cross(world_up).normalized()
    up = right.cross(fwd).normalized()
    m = Matrix((right, up, -fwd)).transposed()  # columns = X, Y, Z
    return m.to_quaternion()


def _view3d_space():
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    return area.spaces.active
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 鏡表
# ---------------------------------------------------------------------------
def load_shots(data):
    rt["shots"] = data if isinstance(data, dict) and "shots" in data else {"fps": 24, "shots": []}
    rt["current_shot"] = None


def find_shot(shot_id):
    for s in rt["shots"].get("shots", []):
        if s.get("id") == shot_id:
            return s
    return None


def select_shot(scene, cam, shot_id):
    s = find_shot(shot_id)
    rt["current_shot"] = s
    if s is None:
        return
    fps = scene.render.fps / scene.render.fps_base
    start = int(s.get("start", scene.frame_current))
    scene.frame_set(start)
    if s.get("lens"):
        cam.data.lens = float(s["lens"])
    pose = s.get("pose")
    if pose and isinstance(pose, dict):
        loc = pose.get("loc")
        rot = pose.get("rot")
        if loc and rot and len(loc) == 3 and len(rot) == 4:
            cam.location = Vector(loc)
            cam.rotation_quaternion = Quaternion(rot)
            recenter(cam)
    rt["message"] = "鏡 %s  %s" % (s.get("id"), s.get("title", ""))


def _shot_range(scene, s):
    fps = scene.render.fps / scene.render.fps_base
    start = int(s.get("start", scene.frame_current))
    end = start + max(1, int(round(float(s.get("dur", 0) or 0) * fps))) - 1
    return start, end


def scrub_shot(scene, t):
    """把時間軸拉到目前鏡的 t（0–1）。沒選鏡就不動。"""
    s = rt["current_shot"]
    if s is None:
        return
    a, b = _shot_range(scene, s)
    scene.frame_set(int(round(a + (b - a) * t)))


def key_command(scene, cam, cmd, arg=None):
    s = rt["current_shot"]
    if s is None:
        rt["message"] = "先選一顆鏡再記機位"
        return
    keys = s.setdefault("keys", [])
    if cmd == "add":
        f = scene.frame_current
        k = {"frame": f, "loc": list(cam.matrix_world.translation),
             "rot": list(cam.matrix_world.to_quaternion()), "lens": cam.data.lens}
        keys[:] = [x for x in keys if x["frame"] != f] + [k]
        keys.sort(key=lambda x: x["frame"])
        rt["message"] = "機位 %d/%d @ 第 %d 格" % (keys.index(k) + 1, len(keys), f)
    elif cmd == "del":
        if keys:
            # 刪掉離目前格最近的那一個
            k = min(keys, key=lambda x: abs(x["frame"] - scene.frame_current))
            keys.remove(k)
            rt["message"] = "刪機位 @ 第 %d 格，剩 %d" % (k["frame"], len(keys))
    elif cmd == "goto":
        if keys:
            i = int(arg or 0) % len(keys)
            k = keys[i]
            scene.frame_set(k["frame"])
            cam.location = Vector(k["loc"])
            cam.rotation_quaternion = Quaternion(k["rot"])
            cam.data.lens = k["lens"]
            recenter(cam)
            rt["raw_p"] = Vector(k["loc"])
            rt["message"] = "到機位 %d/%d @ 第 %d 格" % (i + 1, len(keys), k["frame"])
    elif cmd == "build":
        build_keys(scene, s)
    elif cmd == "export":
        # 輸出這顆鏡最近的成品：串接結果優先，否則最後一個 take
        name = s.get("built") or next((t[0] for t in reversed(rt["takes"]) if t[1] == s.get("id")), None)
        obj = bpy.data.objects.get(name) if name else None
        if obj is None:
            rt["message"] = "這顆鏡還沒有 take 或串接結果"
            return
        from . import export
        p = scene.tangyicam
        rt["message"], _ = export.export_take(scene, obj, p.export_width, p.shading)


def build_keys(scene, s):
    """串接：把這顆鏡的機位關鍵影格接成一台 TC_<鏡>_kf 相機，貝茲＋自動夾緊把手。"""
    keys = sorted(s.get("keys", []), key=lambda x: x["frame"])
    if len(keys) < 2:
        rt["message"] = "至少要兩個機位才能串接"
        return None
    name = "TC_%s_kf" % s.get("id", "free")
    old = bpy.data.objects.get(name)
    if old is not None:
        data = old.data
        bpy.data.objects.remove(old)
        if data.users == 0:
            bpy.data.cameras.remove(data)
    src = driven_camera(scene)
    data = src.data.copy()
    data.name = name
    if data.animation_data:
        data.animation_data_clear()
    cam = bpy.data.objects.new(name, data)
    scene.collection.objects.link(cam)
    cam.rotation_mode = "QUATERNION"
    cam.color = (0.2, 0.6, 1.0, 1.0)
    prev_q = None
    for k in keys:
        q = Quaternion(k["rot"])
        if prev_q is not None and prev_q.dot(q) < 0:
            q.negate()  # 同號，插值才不會繞遠路
        prev_q = q
        cam.location = Vector(k["loc"])
        cam.rotation_quaternion = q
        cam.data.lens = k["lens"]
        cam["tc_sf"] = float(k["frame"])
        f = k["frame"]
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_quaternion", frame=f)
        cam.keyframe_insert('["tc_sf"]', frame=f)
        cam.data.keyframe_insert("lens", frame=f)
    for owner in (cam, cam.data):
        ad = owner.animation_data
        if ad and ad.action:
            for fc in action_curves(owner):
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR" if fc.data_path == '["tc_sf"]' else "BEZIER"
                    kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
                fc.update()
            ad.action.name = name
    s["built"] = name
    rt["takes"].append((name, s.get("id"), keys[-1]["frame"] - keys[0]["frame"] + 1))
    rt["message"] = "串接 %d 個機位 → %s（第 %d–%d 格）" % (len(keys), name, keys[0]["frame"], keys[-1]["frame"])
    return cam


def save_shot_pose(scene, cam):
    s = rt["current_shot"]
    if s is None:
        return False
    s["pose"] = {"loc": list(cam.matrix_world.translation),
                 "rot": list(cam.matrix_world.to_quaternion()),
                 "lens": cam.data.lens}
    s["lens"] = cam.data.lens
    return True


# ---------------------------------------------------------------------------
# 錄製
# ---------------------------------------------------------------------------
def _resolve_record(scene, cam, rec_req):
    """Consume an explicit phone record command; UI and automatic stop stay independent."""
    if rec_req is None:
        return
    rt["rec_phone"] = rec_req
    if rec_req and not rt["recording"]:
        record_start(scene)
    elif not rec_req and rt["recording"]:
        record_stop(scene)


def record_start(scene):
    if rt["recording"]:
        return
    src = driven_camera(scene)
    shot = rt["current_shot"]
    fps = scene.render.fps / scene.render.fps_base
    shot_id = (shot or {}).get("id") or "free"
    rt["rec_take"] = _next_take(shot_id)
    name = "TC_%s_t%02d" % (shot_id, rt["rec_take"])
    data = src.data.copy()
    data.name = name
    if data.animation_data:
        data.animation_data_clear()
    cam = bpy.data.objects.new(name, data)
    scene.collection.objects.link(cam)
    cam.rotation_mode = "QUATERNION"
    cam.matrix_world = src.matrix_world.copy()
    cam.data.lens = src.data.lens
    cam.color = (1.0, 0.2, 0.2, 1.0)
    scene.camera = cam
    rt["rec_cam"] = cam.name
    start = int(shot.get("start", scene.frame_current)) if shot else scene.frame_current
    dur = float(shot.get("dur", 0) or 0) if shot else 0.0
    rt["rec_start_frame"] = start
    rt["rec_end_frame"] = (start + max(1, int(round(dur * fps))) - 1) if dur > 0 else None
    rt["rec_t0"] = time.perf_counter()
    rt["rec_last_frame"] = -1
    rt["rec_sf"] = float(start)
    rt["rec_sample"] = (0.0, float(start), cam.matrix_world.copy(), cam.data.lens)
    rt["rec_slow"] = False
    rt["rec_shot"] = shot_id
    rt["recording"] = True
    rt["rec_requires_phone"] = phone_seen(within=0.5)
    # 讓平滑值接續到新相機上（同一個矩陣，不會跳）
    rt["smooth_q"] = cam.matrix_world.to_quaternion()
    rt["smooth_p"] = cam.matrix_world.translation.copy()
    rt["raw_p"] = rt["smooth_p"].copy()
    if rt["cam_base_rot"] is not None:
        rt["cam_base_rot"] = rt["smooth_q"].copy()
        with lock:
            q = state["q"]
        rt["q_base"] = Quaternion(q) if q else None
    scene.frame_set(start)
    rt["message"] = "● REC %s" % name


def _record_tick(scene, cam, now, dt, tscale):
    """Sample both clocks at exact output-frame times without re-evaluation
    overwriting the live phone pose. Every take owns its own curves."""
    fps = scene.render.fps / scene.render.fps_base
    start = rt["rec_start_frame"]
    elapsed = max(0.0, now - rt["rec_t0"])
    previous_t, previous_sf, previous_matrix, previous_lens = rt["rec_sample"]
    elapsed = max(previous_t, elapsed)
    sample_matrix = cam.matrix_world.copy()
    sample_lens = cam.data.lens
    span = elapsed - previous_t
    sf = previous_sf + span * fps * tscale
    rt["rec_sf"] = sf
    frame = start + int(elapsed * fps + 1e-7)
    end = rt["rec_end_frame"]
    last = min(frame, end) if end is not None else frame
    first = max(start, rt["rec_last_frame"] + 1)
    slow = tscale < 0.999
    if slow != rt["rec_slow"]:
        rt["rec_slow"] = slow
        scene.timeline_markers.new(("SLO_in " if slow else "SLO_out ") + cam.name,
                                   frame=last)
    # Evaluating the scene also evaluates this camera's already-recorded action.
    # Keep the live matrix separately and restore it after every evaluation.
    scene.frame_set(int(sf), subframe=sf - int(sf))
    for f in range(first, last + 1):
        output_t = (f - start) / fps
        alpha = max(0.0, min(1.0, (output_t - previous_t) / span)) if span > 1e-9 else 0.0
        loc = previous_matrix.translation.lerp(sample_matrix.translation, alpha)
        rot = previous_matrix.to_quaternion().slerp(sample_matrix.to_quaternion(), alpha)
        cam.matrix_world = Matrix.Translation(loc) @ rot.to_matrix().to_4x4()
        cam.data.lens = previous_lens + (sample_lens - previous_lens) * alpha
        cam["tc_sf"] = previous_sf + max(0.0, output_t - previous_t) * fps * tscale
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_quaternion", frame=f)
        cam.keyframe_insert('["tc_sf"]', frame=f)
        cam.data.keyframe_insert("lens", frame=f)
        rt["rec_last_frame"] = f
    cam.matrix_world = sample_matrix
    cam.data.lens = sample_lens
    rt["rec_sample"] = (elapsed, sf, sample_matrix, sample_lens)
    if end is not None and elapsed >= (end - start + 1) / fps:
        record_stop(scene)

def record_stop(scene):
    if not rt["recording"]:
        return
    rt["recording"] = False
    name = rt["rec_cam"]
    frames = max(0, rt["rec_last_frame"] - rt["rec_start_frame"] + 1)
    rt["takes"].append((name, rt["rec_shot"], frames))
    if rt["rec_slow"]:
        scene.timeline_markers.new("SLO_out " + name, frame=rt["rec_last_frame"])
        rt["rec_slow"] = False
    cam = bpy.data.objects.get(name)
    if cam is not None and cam.animation_data and cam.animation_data.action:
        cam.animation_data.action.name = name
        # 錄下來的是「取樣」，線性插值最忠實；之後要柔化再選 keyframe 做平滑
        try:
            for fc in action_curves(cam):
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
        except Exception:
            pass
    rt["rec_cam"] = ""
    rt["message"] = "■ %s  %d 格" % (name, frames)
    # 停止後 TC_CAM 接手，停在 take 結束的機位；take 相機留著自己的 action
    driver = driven_camera(scene)
    if cam is not None:
        driver.matrix_world = cam.matrix_world.copy()
        driver.data.lens = cam.data.lens
        rt["smooth_q"] = driver.matrix_world.to_quaternion()
        rt["smooth_p"] = driver.matrix_world.translation.copy()
        rt["raw_p"] = rt["smooth_p"].copy()
        rt["cam_base_rot"] = rt["smooth_q"].copy()
        with lock:
            q = state["q"]
        rt["q_base"] = Quaternion(q) if q else None
    final_matrix = driver.matrix_world.copy()
    final_lens = driver.data.lens
    scene.frame_set(rt["rec_start_frame"])
    driver.matrix_world = final_matrix
    driver.data.lens = final_lens
    scene.camera = driver


def _next_take(shot_id):
    n = 0
    prefix = "TC_%s_t" % shot_id
    for o in bpy.data.objects:
        if o.name.startswith(prefix):
            try:
                n = max(n, int(o.name[len(prefix):len(prefix) + 2]))
            except ValueError:
                pass
    return n + 1


# ---------------------------------------------------------------------------
# 遙測（送給手機 HUD）
# ---------------------------------------------------------------------------
def telemetry(scene, cam, seen):
    shot = rt["current_shot"] or {}
    fps = scene.render.fps / scene.render.fps_base
    remain = None
    if rt["recording"] and rt["rec_end_frame"] is not None:
        remain = max(0.0, (rt["rec_end_frame"] - (rt["rec_start_frame"] + int((time.perf_counter() - rt["rec_t0"]) * fps))) / fps)
    with lock:
        stab = state["stab"]
        horizon = state["horizon"]
        mode = state["mode"]
        gyro = state["q"] is not None
    return {
        "t": "tele",
        "fps": round(rt["fps"], 1),
        "rec": rt["recording"],
        "frame": scene.frame_current,
        "remain": None if remain is None else round(remain, 1),
        "shot": shot.get("id"),
        "shot_title": shot.get("title", ""),
        "shot_dur": shot.get("dur"),
        "shot_size": shot.get("size", ""),
        "lens": round(cam.data.lens, 1),
        "cam": cam.name,
        "stab": stab,
        "horizon": horizon,
        "mode": mode,
        "gyro": gyro,
        "take": rt["rec_take"],
        "slow": rt["rec_slow"],
        "keys": [k["frame"] for k in shot.get("keys", [])] if shot else [],
        "shot_start": shot.get("start") if shot else None,
        "shot_end": (_shot_range(scene, shot)[1] if shot else None),
        "shell": len(rt["shell_hidden"]),
        "msg": rt["message"],
        "loc": [round(v, 2) for v in cam.matrix_world.translation],
    }

# PATCH_V02_DONE

# PATCH_V02B_DONE

