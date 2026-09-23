# -*- coding: utf-8 -*-
"""TangyiCam — 手機驅動的虛擬攝影機，帶鏡表與軟體穩定器。

Blender 端：
- N 面板 › TangyiCam：啟動伺服器、顯示 QR、鏡表、穩定器、錄製。
- 兩個 app timer：tick（60 Hz 套姿態＋錄鍵）、preview（≤20 Hz 離屏渲染推手機）。
手機端：web/ 裡的單頁，掃 QR 開。
"""

import json
import os
import time
import webbrowser

import bpy

from mathutils import Matrix, Quaternion, Vector

from . import camera, export, preview, server, studio_ui
from . import setup as connection_setup


ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(ADDON_DIR, "web")
DEFAULT_CERT_DIR = connection_setup.default_cert_dir()

_srv = None
_tick_registered = False
_last_tele = 0.0
_last_preview = 0.0
_disconnect_pending = False


def _prefs():
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 偏好設定
# ---------------------------------------------------------------------------
class TC_Prefs(bpy.types.AddonPreferences):
    bl_idname = __package__

    cert_dir: bpy.props.StringProperty(
        name="憑證資料夾", subtype="DIR_PATH", default=DEFAULT_CERT_DIR,
        description="放 server.pem / server-key.pem / rootCA.pem（mkcert 產生）")
    https_port: bpy.props.IntProperty(name="HTTPS 埠", default=8443, min=1024, max=65535)
    http_port: bpy.props.IntProperty(name="HTTP 埠（裝憑證用）", default=8080, min=1024, max=65535)
    preview_width: bpy.props.IntProperty(name="預覽寬", default=960, min=320, max=1920, step=32)
    preview_fps: bpy.props.IntProperty(name="預覽 FPS", default=20, min=5, max=30)
    preview_quality: bpy.props.IntProperty(name="JPEG 品質", default=70, min=30, max=95)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "cert_dir")
        col.operator("tangyicam.setup_connection", icon="PREFERENCES")
        row = col.row()
        row.prop(self, "https_port")
        row.prop(self, "http_port")
        row = col.row()
        row.prop(self, "preview_width")
        row.prop(self, "preview_fps")
        row.prop(self, "preview_quality")
        col.label(text="Pillow: %s" % ("有" if preview.HAVE_PIL else "無（退回 save_render，較慢）"))


# ---------------------------------------------------------------------------
# 場景屬性
# ---------------------------------------------------------------------------
def _stab_update(self, context):
    with camera.lock:
        camera.state["stab"] = int(self.stab)
        camera.state["horizon"] = bool(self.horizon)
        camera.state["mode"] = self.mode


class TC_Props(bpy.types.PropertyGroup):
    stab: bpy.props.EnumProperty(
        name="穩定器", items=[(str(i), ["關", "1 輕", "2", "3 中", "4", "5 重"][i], "") for i in range(6)],
        default="3", update=_stab_update)
    horizon: bpy.props.BoolProperty(name="水平鎖", default=False, update=_stab_update,
                                    description="鎖死 roll 軸，畫面永遠水平（像三軸穩定器）")
    mode: bpy.props.EnumProperty(name="移動模式", items=[("WALK", "步行", "前後左右貼地面，升降走世界 Z"),
                                                     ("FPV", "FPV", "全部沿相機自己的軸"),
                                                     ("DOLLY", "軌道", "沿指定曲線滑動，像真的軌道車")],
                                 default="WALK", update=_stab_update)
    track: bpy.props.PointerProperty(name="軌道曲線", type=bpy.types.Object,
                                     poll=lambda self, o: o.type == "CURVE",
                                     description="軌道模式用的曲線物件（Add › Curve › Path，拉成你要的推軌路線）")
    move_speed: bpy.props.FloatProperty(name="移動速度 m/s", default=2.5, min=0.05, max=20.0)
    shading: bpy.props.EnumProperty(name="預覽著色", items=[("SOLID", "實體", ""), ("MATERIAL", "材質", ""),
                                                        ("RENDERED", "渲染", ""), ("WIREFRAME", "線框", "")],
                                    default="SOLID")
    shots_path: bpy.props.StringProperty(name="鏡表 JSON", subtype="FILE_PATH", default="")
    # 邊界盒與外殼
    bounds_set: bpy.props.BoolProperty(name="已抓邊界", default=False)
    bounds_min: bpy.props.FloatVectorProperty(name="邊界 min", size=3, default=(0, 0, 0), subtype="XYZ")
    bounds_max: bpy.props.FloatVectorProperty(name="邊界 max", size=3, default=(1, 1, 1), subtype="XYZ")
    bounds_clamp: bpy.props.BoolProperty(name="鎖在房間裡", default=False,
                                         description="相機不能超出邊界盒（含安全距離）")
    bounds_margin: bpy.props.FloatProperty(name="安全距離", default=0.15, min=0.0, max=2.0)
    shell_hide: bpy.props.BoolProperty(name="出界自動藏外殼", default=True,
                                       description="相機在房間外面時，把那一側的天花板／牆藏起來，回來就恢復")
    shell_prefix: bpy.props.StringProperty(name="外殼前綴", default="CEILING,WALL,FLOOR",
                                           description="名字以這些開頭的物件視為外殼（逗號分隔）")
    export_width: bpy.props.IntProperty(name="輸出寬", default=1920, min=640, max=3840, step=64)
    shot_id: bpy.props.StringProperty(name="鏡", default="")


# ---------------------------------------------------------------------------
# 伺服器
# ---------------------------------------------------------------------------
def _on_message(client, obj):
    seq = obj.get("seq")
    if isinstance(seq, int):
        if seq < getattr(client, "_tc_last_seq", -1):
            return
        client._tc_last_seq = seq
    camera.apply_payload(obj)


def _on_disconnect():
    global _disconnect_pending
    with camera.lock:
        camera.state.update(mx=0, my=0, mz=0, zoom=0, q=None, rec=None, last_seen=0.0, tscale=1.0)
    _disconnect_pending = True


def _shots_provider():
    return camera.rt["shots"]


def _ensure_timers():
    global _tick_registered
    if not _tick_registered:
        bpy.app.timers.register(_tick, first_interval=0.1, persistent=True)  # 回傳 1/120，實際由 Blender 主迴圈決定
        bpy.app.timers.register(_preview_tick, first_interval=0.2, persistent=True)
        _tick_registered = True


def _tick():
    """60 Hz：套姿態、錄鍵、10 Hz 遙測。"""
    global _last_tele, _disconnect_pending
    if _srv is None or not _srv.running:
        return 0.25
    scene = bpy.context.scene
    if scene is None:
        return 1.0 / 60.0
    if _disconnect_pending:
        _disconnect_pending = False
        if camera.rt["recording"]:
            camera.record_stop(scene)
        camera.rt["rec_phone"] = None
        camera.rt["message"] = "手機已中斷；錄製與移動已停止"
    try:
        tele = camera.tick(scene)
    except Exception as e:
        camera.rt["message"] = "tick 錯誤: %s" % e
        return 0.1
    now = time.perf_counter()
    if now - _last_tele > 0.1:
        _last_tele = now
        # 手機改了檔位／模式，面板要跟著顯示（值相同時 update 回寫無害）
        props = getattr(scene, "tangyicam", None)
        if props is not None:
            with camera.lock:
                s_stab, s_hor, s_mode = str(camera.state["stab"]), camera.state["horizon"], camera.state["mode"]
            if props.stab != s_stab:
                props.stab = s_stab
            if props.horizon != s_hor:
                props.horizon = s_hor
            if props.mode != s_mode:
                props.mode = s_mode
        tele["prev_ms"] = round(preview.stats["ms"], 1)
        tele["phones"] = _srv.phone_count()
        _srv.broadcast_text(tele)
        # 讓面板跟著刷新
        try:
            for area in bpy.context.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        except Exception:
            pass
    return 1.0 / 120.0


def _preview_tick():
    if _srv is None or not _srv.running:
        return 0.5
    if _srv.phone_count() == 0 or not camera.phone_seen(5.0):
        return 0.5
    scene = bpy.context.scene
    if scene is None:
        return 0.2
    p = _prefs()
    fps = p.preview_fps if p else 20
    w = p.preview_width if p else 960
    q = p.preview_quality if p else 70
    h = int(round(w * scene.render.resolution_y / max(1, scene.render.resolution_x) / 2.0)) * 2
    props = getattr(scene, "tangyicam", None)
    shade = props.shading if props else "SOLID"
    cam = camera.driven_camera(scene)
    data = preview.capture_jpeg(scene, cam, w, h, q, shading=shade)
    if data:
        _srv.broadcast_video(data)
    # 渲染本身花掉的時間要扣掉，不然實際 fps 會掉一半
    return max(0.01, 1.0 / fps - preview.stats["ms"] / 1000.0)


class TC_OT_setup_connection(bpy.types.Operator):
    bl_idname = "tangyicam.setup_connection"
    bl_label = "首次設定／更新憑證"
    bl_description = "建立此電腦專用的本機憑證，不修改電腦的信任憑證設定"

    def execute(self, context):
        if _srv is not None and _srv.running:
            self.report({"ERROR"}, "請先停止手機攝影機再更新憑證")
            return {"CANCELLED"}
        prefs = _prefs()
        folder = bpy.path.abspath(prefs.cert_dir) if prefs else DEFAULT_CERT_DIR
        try:
            message = connection_setup.create_certificate(folder, server.detect_lan_ip())
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        camera.rt["message"] = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


class TC_OT_reset_pairing(bpy.types.Operator):
    bl_idname = "tangyicam.reset_pairing"
    bl_label = "重設配對／中斷手機"
    bl_description = "撤銷已配對裝置並產生新的六位配對碼"

    def execute(self, context):
        if _srv is not None:
            _srv.reset_pairing()
        return {"FINISHED"}


class TC_OT_start(bpy.types.Operator):
    bl_idname = "tangyicam.start"
    bl_label = "啟動手機攝影機"
    bl_description = "啟動本機 HTTPS 伺服器，手機掃 QR 連進來"

    def execute(self, context):
        global _srv
        p = _prefs()
        cert_dir = bpy.path.abspath(p.cert_dir) if p else DEFAULT_CERT_DIR
        if _srv is not None and _srv.running:
            self.report({"INFO"}, "攝影機已啟動")
            return {"FINISHED"}
        ok, message = connection_setup.certificate_status(cert_dir, server.detect_lan_ip())
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        if p and p.https_port == p.http_port:
            self.report({"ERROR"}, "HTTPS 與安裝說明的 HTTP 埠不可相同")
            return {"CANCELLED"}
        cert = os.path.join(cert_dir, "server.pem")
        key = os.path.join(cert_dir, "server-key.pem")
        ca = os.path.join(cert_dir, "rootCA.pem")
        if not (os.path.isfile(cert) and os.path.isfile(key)):
            self.report({"ERROR"}, "找不到憑證：%s（先用 mkcert 產生）" % cert_dir)
            return {"CANCELLED"}
        if _srv is None or not _srv.running:
            _srv = server.TCServer(WEB_DIR, cert, key, ca,
                                   https_port=p.https_port if p else 8443,
                                   http_port=p.http_port if p else 8080)
            _srv.on_message = _on_message
            _srv.on_disconnect = _on_disconnect
            _srv.shots_provider = _shots_provider
        if not _srv.start():
            self.report({"ERROR"}, "啟動失敗：%s" % _srv.error)
            return {"CANCELLED"}
        cam = camera.driven_camera(context.scene)
        camera.set_home(cam)
        camera.recenter(cam)
        _stab_update(context.scene.tangyicam, context)
        _ensure_timers()
        camera.rt["message"] = "伺服器 %s" % _srv.url()
        self.report({"INFO"}, "手機開 %s" % _srv.url())
        return {"FINISHED"}


class TC_OT_stop(bpy.types.Operator):
    bl_idname = "tangyicam.stop"
    bl_label = "停止"

    def execute(self, context):
        if _srv is not None:
            _srv.stop()
        if camera.rt["recording"]:
            camera.record_stop(context.scene)
        preview.free()
        camera._restore_shell()
        camera.rt["message"] = "已停止"
        return {"FINISHED"}


class TC_OT_qr(bpy.types.Operator):
    bl_idname = "tangyicam.qr"
    bl_label = "顯示 QR"
    bl_description = "在瀏覽器開一頁 QR：手機掃了就連進來（第一次要先裝憑證）"

    def execute(self, context):
        if _srv is None or not _srv.running:
            self.report({"ERROR"}, "先啟動伺服器")
            return {"CANCELLED"}
        webbrowser.open("http://127.0.0.1:%d/qr" % _srv.http_port)
        return {"FINISHED"}


class TC_OT_recenter(bpy.types.Operator):
    bl_idname = "tangyicam.recenter"
    bl_label = "歸零"
    bl_description = "把手機現在的朝向當成相機現在的朝向（相機不動）"

    def execute(self, context):
        camera.recenter(camera.driven_camera(context.scene))
        return {"FINISHED"}


class TC_OT_home(bpy.types.Operator):
    bl_idname = "tangyicam.home"
    bl_label = "回起點"

    def execute(self, context):
        with camera.lock:
            camera.state["home"] = True
        return {"FINISHED"}


class TC_OT_set_home(bpy.types.Operator):
    bl_idname = "tangyicam.set_home"
    bl_label = "設起點"
    bl_description = "把相機現在的機位設為「回起點」的位置"

    def execute(self, context):
        camera.set_home(camera.driven_camera(context.scene))
        return {"FINISHED"}


class TC_OT_record(bpy.types.Operator):
    bl_idname = "tangyicam.record"
    bl_label = "錄製"

    def execute(self, context):
        if camera.rt["recording"]:
            camera.record_stop(context.scene)
        else:
            camera.record_start(context.scene)
        return {"FINISHED"}


class TC_OT_load_shots(bpy.types.Operator):
    bl_idname = "tangyicam.load_shots"
    bl_label = "載入鏡表"

    def execute(self, context):
        path = bpy.path.abspath(context.scene.tangyicam.shots_path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                camera.load_shots(json.load(f))
        except Exception as e:
            self.report({"ERROR"}, "讀不到鏡表：%s" % e)
            return {"CANCELLED"}
        n = len(camera.rt["shots"].get("shots", []))
        camera.rt["message"] = "鏡表 %d 顆" % n
        self.report({"INFO"}, "載入 %d 顆" % n)
        return {"FINISHED"}


class TC_OT_save_shots(bpy.types.Operator):
    bl_idname = "tangyicam.save_shots"
    bl_label = "存回鏡表"
    bl_description = "把每顆鏡存下來的起始機位寫回 JSON"

    def execute(self, context):
        path = bpy.path.abspath(context.scene.tangyicam.shots_path)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(camera.rt["shots"], f, ensure_ascii=False, indent=1)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class TC_OT_select_shot(bpy.types.Operator):
    bl_idname = "tangyicam.select_shot"
    bl_label = "選鏡"
    shot_id: bpy.props.StringProperty()

    def execute(self, context):
        camera.select_shot(context.scene, camera.driven_camera(context.scene), self.shot_id)
        context.scene.tangyicam.shot_id = self.shot_id
        return {"FINISHED"}


class TC_OT_save_pose(bpy.types.Operator):
    bl_idname = "tangyicam.save_pose"
    bl_label = "存起始機位"
    bl_description = "把相機現在的機位與焦段記到目前這顆鏡"

    def execute(self, context):
        if camera.save_shot_pose(context.scene, camera.driven_camera(context.scene)):
            camera.rt["message"] = "機位已存到鏡 %s" % camera.rt["current_shot"].get("id")
            return {"FINISHED"}
        self.report({"WARNING"}, "先選一顆鏡")
        return {"CANCELLED"}


class TC_OT_key(bpy.types.Operator):
    bl_idname = "tangyicam.key"
    bl_label = "機位關鍵影格"
    cmd: bpy.props.StringProperty(default="add")
    arg: bpy.props.IntProperty(default=0)

    def execute(self, context):
        camera.key_command(context.scene, camera.driven_camera(context.scene), self.cmd, self.arg)
        return {"FINISHED"}


class TC_OT_grab_bounds(bpy.types.Operator):
    bl_idname = "tangyicam.grab_bounds"
    bl_label = "從場景抓邊界"
    bl_description = "用場景所有網格的包圍盒當房間邊界，再扣掉外殼厚度"

    def execute(self, context):
        if not camera.grab_bounds(context.scene):
            self.report({"WARNING"}, "場景沒有網格")
            return {"CANCELLED"}
        p = context.scene.tangyicam
        camera.rt["message"] = "邊界 %.1f,%.1f,%.1f → %.1f,%.1f,%.1f" % (*p.bounds_min, *p.bounds_max)
        return {"FINISHED"}


class TC_OT_export_take(bpy.types.Operator):
    bl_idname = "tangyicam.export_take"
    bl_label = "輸出選取 take 為 mp4"
    bl_description = ("把選取的 TC_ 相機渲染成白模 mp4（相機視角、目前著色），慢動作段依 tc_sf 重新對齊角色動畫；"
                      "另存首尾幀 PNG。需要 ffmpeg")

    def execute(self, context):
        scene = context.scene
        msg, mp4 = export.export_take(scene, context.active_object, scene.tangyicam.export_width, scene.tangyicam.shading)
        camera.rt["message"] = msg
        self.report({"INFO"} if mp4 else {"WARNING"}, msg)
        return {"FINISHED"} if mp4 else {"CANCELLED"}


class TC_OT_smooth_take(bpy.types.Operator):
    bl_idname = "tangyicam.smooth_take"
    bl_label = "柔化選取相機的曲線"
    bl_description = "對選取相機的 F-curve 做高斯平滑（後製版穩定器，可重複按）"
    width: bpy.props.IntProperty(name="寬度（格）", default=4, min=1, max=24)

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "CAMERA" or not obj.animation_data or not obj.animation_data.action:
            self.report({"WARNING"}, "選一台錄好的相機")
            return {"CANCELLED"}
        n = 0
        for fc in studio_ui.studio.curves(obj):
            pts = fc.keyframe_points
            vals = [kp.co[1] for kp in pts]
            if len(vals) < 3:
                continue
            w = self.width
            out = []
            for i in range(len(vals)):
                acc, wsum = 0.0, 0.0
                for k in range(-w, w + 1):
                    j = min(len(vals) - 1, max(0, i + k))
                    g = 2.718281828 ** (-(k * k) / (2.0 * (w / 2.0) ** 2))
                    acc += vals[j] * g
                    wsum += g
                out.append(acc / wsum)
            for kp, v in zip(pts, out):
                kp.co[1] = v
            fc.update()
            n += 1
        self.report({"INFO"}, "柔化 %d 條曲線" % n)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# 面板
# ---------------------------------------------------------------------------
class TC_PT_panel(bpy.types.Panel):
    bl_label = "TangyiCam"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TangyiCam"

    def draw(self, context):
        lay = self.layout
        props = context.scene.tangyicam
        running = _srv is not None and _srv.running
        box = lay.box()
        if running:
            row = box.row()
            row.operator("tangyicam.stop", icon="PAUSE")
            row.operator("tangyicam.qr", icon="URL")
            box.label(text=_srv.url(), icon="LINKED")
            pairing = _srv.pairing.status()
            box.label(text="配對碼：%s（%d 秒）" % (pairing["code"], pairing["expires_in"]))
            box.operator("tangyicam.reset_pairing", icon="FILE_REFRESH")
            box.label(text="手機 %d 台  tick %.0f fps  預覽 %.0f ms" % (
                _srv.phone_count(), camera.rt["fps"], preview.stats["ms"]))
        else:
            box.operator("tangyicam.setup_connection", icon="PREFERENCES")
            box.operator("tangyicam.start", icon="PLAY")
            if _srv is not None and _srv.error:
                box.label(text=_srv.error, icon="ERROR")
        if camera.rt["message"]:
            box.label(text=camera.rt["message"])

        box = lay.box()
        box.label(text="穩定器", icon="DRIVER_ROTATIONAL_DIFFERENCE")
        box.prop(props, "stab", expand=True)
        row = box.row()
        row.prop(props, "horizon")
        row.prop(props, "mode", expand=True)
        box.prop(props, "move_speed")
        if props.mode == "DOLLY":
            box.prop(props, "track")
        box.prop(props, "shading", expand=False)

        box = lay.box()
        box.label(text="房間邊界", icon="MESH_CUBE")
        box.operator("tangyicam.grab_bounds", icon="SHADING_BBOX")
        if props.bounds_set:
            box.label(text="%.1f,%.1f,%.1f → %.1f,%.1f,%.1f" % (*props.bounds_min, *props.bounds_max))
        row = box.row()
        row.prop(props, "bounds_clamp")
        row.prop(props, "bounds_margin")
        box.prop(props, "shell_hide")
        box.prop(props, "shell_prefix")
        if camera.rt["shell_hidden"]:
            box.label(text="藏起：" + ", ".join(camera.rt["shell_hidden"]), icon="HIDE_ON")

        box = lay.box()
        box.label(text="相機", icon="CAMERA_DATA")
        row = box.row()
        row.operator("tangyicam.recenter", icon="ORIENTATION_GIMBAL")
        row.operator("tangyicam.home", icon="HOME")
        row.operator("tangyicam.set_home", icon="PINNED")
        rec = camera.rt["recording"]
        row = box.row()
        row.scale_y = 1.6
        row.operator("tangyicam.record", text="■ 停止" if rec else "● 錄製", icon="REC", depress=rec)

        box = lay.box()
        box.label(text="鏡表", icon="SEQUENCE")
        row = box.row(align=True)
        row.prop(props, "shots_path", text="")
        row.operator("tangyicam.load_shots", text="", icon="IMPORT")
        row.operator("tangyicam.save_shots", text="", icon="EXPORT")
        cur = camera.rt["current_shot"]
        if cur:
            box.label(text="鏡 %s  %s  ⏱ %s\"  %smm" % (cur.get("id"), cur.get("size", ""),
                                                        cur.get("dur"), cur.get("lens", "")))
            box.operator("tangyicam.save_pose", icon="PINNED")
            keys = cur.get("keys", [])
            row = box.row(align=True)
            op = row.operator("tangyicam.key", text="＋機位", icon="KEYFRAME")
            op.cmd = "add"
            op = row.operator("tangyicam.key", text="刪", icon="X")
            op.cmd = "del"
            op = row.operator("tangyicam.key", text="串接 %d" % len(keys), icon="IPO_BEZIER")
            op.cmd = "build"
            if keys:
                row = box.row(align=True)
                for i, k in enumerate(keys[:12]):
                    op = row.operator("tangyicam.key", text=str(k["frame"]))
                    op.cmd = "goto"
                    op.arg = i
        shots = camera.rt["shots"].get("shots", [])
        if shots:
            col = box.column(align=True)
            for s in shots[:80]:
                row = col.row(align=True)
                op = row.operator("tangyicam.select_shot",
                                  text="%s  %s  %s\"" % (s.get("id"), s.get("size", ""), s.get("dur", "")),
                                  depress=(cur is s))
                op.shot_id = s.get("id", "")
                if s.get("pose"):
                    row.label(text="", icon="PINNED")
        takes = camera.rt["takes"]
        if takes:
            box = lay.box()
            box.label(text="Takes", icon="RENDER_ANIMATION")
            for name, shot, frames in takes[-8:]:
                box.label(text="%s  %d 格" % (name, frames))
            box.operator("tangyicam.smooth_take", icon="SMOOTHCURVE")
            row = box.row()
            row.prop(props, "export_width")
            row.operator("tangyicam.export_take", icon="RENDER_ANIMATION", text="輸出 mp4")


classes = (
    TC_Prefs, TC_Props,
    TC_OT_setup_connection, TC_OT_reset_pairing, TC_OT_start, TC_OT_stop, TC_OT_qr, TC_OT_recenter, TC_OT_home, TC_OT_set_home,
    TC_OT_record, TC_OT_load_shots, TC_OT_save_shots, TC_OT_select_shot, TC_OT_save_pose,
    TC_OT_smooth_take, TC_OT_grab_bounds, TC_OT_export_take, TC_OT_key, TC_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.tangyicam = bpy.props.PointerProperty(type=TC_Props)
    studio_ui.register()


def unregister():
    global _srv, _tick_registered
    for timer in (_tick, _preview_tick):
        if bpy.app.timers.is_registered(timer):
            bpy.app.timers.unregister(timer)
    _tick_registered = False
    studio_ui.unregister()
    if _srv is not None:
        _srv.stop()
        _srv = None
    preview.free()
    del bpy.types.Scene.tangyicam
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

# PATCH_V02_DONE

# PATCH_V02B_DONE
