# -*- coding: utf-8 -*-
"""離屏渲染「相機看到的畫面」→ JPEG，推給手機。

跟 Higgsfield 的做法差一點：它們畫的是 viewport 目前的視角（再把 viewport 切到
相機視角），我們直接用相機自己的 view / projection 矩陣，viewport 在幹嘛都無所謂——
你在 PC 上可以自由轉視角看角色，手機上永遠是相機畫面。

JPEG 用 Pillow（extension 內附 wheel）；找不到 Pillow 就退回 Blender 自己的
save_render（慢三到五倍，但能動）。
"""

import os
import tempfile
import time

import bpy
import gpu

try:
    import numpy as np
except Exception:  # Blender 一定有 numpy，這只是保險
    np = None

try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    Image = None
    HAVE_PIL = False

_offscreen = None
_size = (0, 0)
_last_err = ""
stats = {"ms": 0.0, "bytes": 0, "pil": HAVE_PIL}


def free():
    global _offscreen
    if _offscreen is not None:
        try:
            _offscreen.free()
        except Exception:
            pass
    _offscreen = None


def _find_view3d():
    wm = bpy.context.window_manager
    best, best_size = (None, None, None), -1
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None:
                continue
            size = area.width * area.height
            if size > best_size:
                best_size = size
                best = (window, area, region)
    return best


def capture_jpeg(scene, cam, width=960, height=540, quality=70, shading=None):
    """回傳 JPEG bytes；失敗回傳 None（並把原因放在 stats['err']）。"""
    global _offscreen, _size, _last_err
    t0 = time.perf_counter()
    window, area, region = _find_view3d()
    if window is None:
        stats["err"] = "沒有 3D 視窗"
        return None
    space = area.spaces.active
    if shading and space.shading.type != shading:
        try:
            space.shading.type = shading
        except Exception:
            pass
    if _offscreen is None or _size != (width, height):
        free()
        _offscreen = gpu.types.GPUOffScreen(width, height)
        _size = (width, height)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    view_matrix = cam.matrix_world.inverted()
    proj = cam.calc_matrix_camera(depsgraph, x=width, y=height, scale_x=1.0, scale_y=1.0)
    try:
        with bpy.context.temp_override(window=window, area=area, region=region):
            with _offscreen.bind():
                _offscreen.draw_view3d(
                    scene, bpy.context.view_layer, space, region,
                    view_matrix, proj, do_color_management=True,
                )
                fb = gpu.state.active_framebuffer_get()
                pixels = fb.read_color(0, 0, width, height, 4, 0, "UBYTE")
    except Exception as e:
        _last_err = str(e)
        stats["err"] = _last_err
        free()
        return None
    # Blender 5.1 在 Metal 上 Buffer 的 stride 是 Fortran 式；ravel(order="K") 兩邊都對
    arr = np.asarray(pixels).ravel(order="K").reshape(height, width, 4)
    rgb = np.ascontiguousarray(arr[::-1, :, :3])  # OpenGL 從左下角開始，翻回來
    data = _encode(rgb, width, height, quality)
    stats["ms"] = (time.perf_counter() - t0) * 1000.0
    stats["bytes"] = len(data) if data else 0
    stats["err"] = ""
    return data


def _encode(rgb, width, height, quality):
    if HAVE_PIL:
        import io
        buf = io.BytesIO()
        Image.frombuffer("RGB", (width, height), rgb.tobytes(), "raw", "RGB", 0, 1).save(
            buf, "JPEG", quality=quality, optimize=False)
        return buf.getvalue()
    # 退路：走 Blender 影像系統存檔再讀回來
    name = "_tangyicam_preview"
    img = bpy.data.images.get(name)
    if img is None or img.size[0] != width or img.size[1] != height:
        if img is not None:
            bpy.data.images.remove(img)
        img = bpy.data.images.new(name, width, height, alpha=False)
    flat = (rgb[::-1].astype(np.float32) / 255.0)
    rgba = np.concatenate([flat, np.ones((height, width, 1), np.float32)], axis=2).ravel()
    img.pixels.foreach_set(rgba)
    path = os.path.join(tempfile.gettempdir(), "tangyicam_preview.jpg")
    scene = bpy.context.scene
    old = (scene.render.image_settings.file_format, scene.render.image_settings.quality)
    old_media = getattr(scene.render.image_settings, "media_type", None)
    if old_media is not None:
        scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = quality
    try:
        img.save_render(path, scene=scene)
    finally:
        if old_media is not None:
            scene.render.image_settings.media_type = old_media
        scene.render.image_settings.file_format, scene.render.image_settings.quality = old
    with open(path, "rb") as f:
        return f.read()
