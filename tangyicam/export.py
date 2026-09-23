"""Take export with isolated output directories and verified encoder completion."""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from fractions import Fraction

import bpy
from mathutils import Matrix, Quaternion, Vector
from . import preview
from .studio import curves as action_curves


def _workbench_frame(scene, obj, path, width, height):
    """Background acceptance tests use Blender's actual renderer, not fake frames."""
    r = scene.render
    old = (scene.camera, r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage,
           r.filepath, r.image_settings.file_format, r.image_settings.quality, r.film_transparent)
    old_media = getattr(r.image_settings, "media_type", None)
    try:
        if old_media is not None:
            r.image_settings.media_type = "IMAGE"
        scene.camera = obj
        r.engine = "BLENDER_WORKBENCH"
        r.resolution_x, r.resolution_y, r.resolution_percentage = width, height, 100
        r.filepath = str(path)
        r.image_settings.file_format = "JPEG"
        r.image_settings.quality = 92
        r.film_transparent = False
        bpy.ops.render.render(write_still=True, scene=scene.name)
    finally:
        scene.camera, r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage = old[:5]
        if old_media is not None:
            r.image_settings.media_type = old_media
        r.filepath, r.image_settings.file_format, r.image_settings.quality, r.film_transparent = old[5:]


def _native_encode(frames, target, width, height, fps, fps_base):
    """Use Blender's built-in FFmpeg when no separate executable is installed."""
    enc = bpy.data.scenes.new("TC_Encode_Temporary")
    try:
        r = enc.render
        r.resolution_x, r.resolution_y, r.resolution_percentage = width, height, 100
        r.fps, r.fps_base = fps, fps_base
        r.filepath = str(target)
        if hasattr(r.image_settings, "media_type"):
            r.image_settings.media_type = "VIDEO"
        r.image_settings.file_format = "FFMPEG"
        r.ffmpeg.format = "MPEG4"
        r.ffmpeg.codec = "H264"
        r.ffmpeg.constant_rate_factor = "HIGH"
        r.ffmpeg.audio_codec = "NONE"
        enc.view_settings.view_transform = "Standard"
        enc.view_settings.look = "None"
        enc.view_settings.exposure = 0
        enc.view_settings.gamma = 1
        editor = enc.sequence_editor_create()
        strips = getattr(editor, "strips", None)
        if strips is None:
            strips = editor.sequences
        strip = strips.new_image("Take", str(frames[0]), channel=1, frame_start=1)
        for frame in frames[1:]:
            strip.elements.append(frame.name)
        strip.frame_final_duration = len(frames)
        enc.frame_start, enc.frame_end = 1, len(frames)
        result = bpy.ops.render.render(animation=True, scene=enc.name)
        if "FINISHED" not in result:
            raise RuntimeError("Blender 影片編碼未完成")
    finally:
        bpy.data.scenes.remove(enc)


def export_take(scene, obj, width=1920, shade="SOLID", quality=92, output_root=None, encoder="auto"):
    """Return a success message and MP4 only when every expected frame was encoded."""
    if obj is None or obj.type != "CAMERA" or not obj.animation_data or not obj.animation_data.action:
        return "選一台錄好的 TC_ 相機", None
    act = obj.animation_data.action
    f0, f1 = math.floor(act.frame_range[0]), math.ceil(act.frame_range[1])
    if f1 < f0 or f1 - f0 > 200000:
        return "相機影格範圍無效或過長", None
    width = max(64, min(3840, int(width))) // 2 * 2
    height = max(2, int(round(width * scene.render.resolution_y / max(1, scene.render.resolution_x) / 2)) * 2)
    fps, fps_base = scene.render.fps, scene.render.fps_base
    rate = Fraction(fps) / Fraction(str(fps_base)).limit_denominator(10000)
    fcs = {(c.data_path, c.array_index): c for c in action_curves(obj)}
    lens_fc = next((c for c in action_curves(obj.data) if c.data_path == "lens"), None) if obj.data.animation_data else None
    base = Path(output_root) if output_root else (Path(bpy.data.filepath).parent / "tc_export" if bpy.data.filepath else Path.home() / "Documents" / "TangyiCam" / "Exports")
    base.mkdir(parents=True, exist_ok=True)
    name = bpy.path.clean_name(obj.name)[:80] or "Take"
    out = Path(tempfile.mkdtemp(prefix=name + "_", dir=base))
    old = (scene.camera, scene.frame_current, scene.frame_subframe, obj.matrix_world.copy(), obj.data.lens)
    frames = []
    error = None
    try:
        for frame in range(f0, f1 + 1):
            time_curve = fcs.get(('["tc_sf"]', 0))
            sf = time_curve.evaluate(frame) if time_curve else float(frame)
            source_frame = math.floor(sf)
            scene.frame_set(source_frame, subframe=sf - source_frame)
            loc = [fcs[("location", i)].evaluate(frame) if ("location", i) in fcs else obj.location[i] for i in range(3)]
            rot = [fcs[("rotation_quaternion", i)].evaluate(frame) if ("rotation_quaternion", i) in fcs else obj.rotation_quaternion[i] for i in range(4)]
            obj.matrix_world = Matrix.Translation(Vector(loc)) @ Quaternion(rot).to_matrix().to_4x4()
            if lens_fc:
                obj.data.lens = lens_fc.evaluate(frame)
            bpy.context.view_layer.update()
            path = out / ("%05d.jpg" % len(frames))
            if bpy.app.background:
                _workbench_frame(scene, obj, path, width, height)
            else:
                data = preview.capture_jpeg(scene, obj, width, height, quality, shading=shade)
                if not data:
                    raise RuntimeError(preview.stats.get("err", "無法擷取 3D 預覽"))
                path.write_bytes(data)
            if not path.is_file() or path.stat().st_size < 20:
                raise RuntimeError("影格未完整寫入")
            frames.append(path)
        target = out / (name + ".mp4")
        pending = out / (name + ".partial.mp4")
        ff = shutil.which("ffmpeg") if encoder == "auto" else None
        if ff:
            result = subprocess.run([ff, "-y", "-framerate", str(rate), "-i", str(out / "%05d.jpg"),
                "-frames:v", str(len(frames)), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                "-movflags", "+faststart", str(pending)], capture_output=True, timeout=1800,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                raise RuntimeError("FFmpeg 編碼失敗：" + result.stderr.decode("utf-8", errors="replace")[-600:])
        else:
            _native_encode(frames, pending, width, height, fps, fps_base)
        if not pending.is_file() or pending.stat().st_size < 100:
            raise RuntimeError("編碼器沒有產生有效影片")
        with pending.open("rb") as handle:
            if b"ftyp" not in handle.read(64):
                raise RuntimeError("輸出不是 MP4 容器")
        # Native Blender movie loading also checks the encoded frame count.
        clip = bpy.data.movieclips.load(str(pending), check_existing=False)
        try:
            if clip.frame_duration != len(frames):
                raise RuntimeError("影片格數不符：%d / %d" % (clip.frame_duration, len(frames)))
        finally:
            bpy.data.movieclips.remove(clip)
        os.replace(pending, target)
        for frame, label in ((frames[0], "first"), (frames[-1], "last")):
            if preview.HAVE_PIL:
                with preview.Image.open(frame) as image:
                    image.save(out / (label + ".png"))
            else:
                image = bpy.data.images.load(str(frame), check_existing=False)
                try:
                    image.pack()  # Force decoding before changing a lazy-loaded image path.
                    image.filepath_raw = str(out / (label + ".png"))
                    image.file_format = "PNG"
                    image.save()
                finally:
                    bpy.data.images.remove(image)
        (out / "export.json").write_text(json.dumps({"camera": obj.name, "frames": len(frames),
            "fps": str(rate), "width": width, "height": height, "source_range": [f0, f1],
            "encoder": "ffmpeg" if ff else "blender", "complete": True}, indent=2), encoding="utf-8")
        return "輸出完成：%d 格 → %s" % (len(frames), target), str(target)
    except Exception as exc:
        error = str(exc)
        (out / "error.txt").write_text(error, encoding="utf-8")
        return "輸出失敗，保留診斷資料：%s；%s" % (out, error), None
    finally:
        scene.camera = old[0]
        scene.frame_set(old[1], subframe=old[2])
        obj.matrix_world = old[3]
        obj.data.lens = old[4]
