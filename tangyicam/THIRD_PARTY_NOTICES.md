# TangyiCam third-party notices

TangyiCam 0.4.0 is distributed under GPL-3.0-or-later. The full text is in LICENSE.txt.
Copyright 2026 Tangyi Studio. Preserve these notices when redistributing.

The original phone-camera design references the GPL-3.0 Higgsfield for Blender phonecam module. TangyiCam changes transport to local HTTPS and adds local pairing, shot lists, recording and Studio tools. TangyiCam is an independent project and is not endorsed by Higgsfield. No proprietary Higgsfield generation model is included. Corresponding TangyiCam source is distributed beside every installation ZIP.

- mkcert 1.4.4, Filippo Valsorda, BSD-3-Clause: licenses/mkcert-LICENSE.txt. Windows x64 binary SHA-256 d2660b50a9ed59eada480750561c96abc2ed4c9a38c6a24d93e30e0977631398. Source: https://github.com/FiloSottile/mkcert/tree/v1.4.4 . Checksum cross-checked with the Microsoft winget-pkgs manifest.
- QRCode.js, davidshimjs, MIT: licenses/qrcodejs-LICENSE.txt. The exact vendored commit, URL and checksum are in licenses/sources.json.
- DeviceOrientationControls quaternion formula references three.js, MIT: licenses/threejs-LICENSE.txt; https://github.com/mrdoob/three.js .
- Pillow 12.3.0: bundled Windows Python 3.11 and 3.13 wheels include their own license and third-party codec notices in their dist-info/license directories. Those files remain intact.
- Blender is separately installed software. The fallback video encoder uses the FFmpeg implementation distributed with Blender. A separately installed ffmpeg executable may also be used; no ffmpeg executable is redistributed in this ZIP.

No certificates, private keys, user assets, motion-capture models, film projects or cloud API credentials are included in this release.
