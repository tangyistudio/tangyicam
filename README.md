# Tangyi Cam

**用手機控制 Blender 攝影機，將運鏡錄成可編輯的 Take。**  
A local-first phone camera controller for Blender, with gyro rotation, joystick movement, shot lists, recording and preview export.

[免費下載 / 安裝教學](https://workshop.tangyi.mx/tangyicam) · [作品示範](https://workshop.tangyi.mx/resources) · [Release notes](docs/CHANGELOG.md)

> **0.4.0 release candidate.** Windows x64 / Blender 4.5.10 and 5.1.2 installation, recording and export have been tested. iPhone Safari hardware acceptance is still pending. This is not a stable-release claim.

## What it does

- Phone browser controls camera orientation through DeviceOrientation and position through joysticks / dolly mode.
- Local HTTPS, one-time six-digit pairing, HttpOnly sessions and disconnect / focus-loss stop handling.
- Live scene preview, adjustable smoothing, horizon lock, focal length and shot-list camera poses.
- Record independent camera takes and editable keyframes, then export preview MP4 plus first / last frames.
- No Workshop account, LLM, cloud generation credits or native phone app required for camera control.

**Not physical 6DOF tracking:** walking with the phone does not reconstruct its position. iPhone first-use certificate setup is required. Preview performance depends on your scene and hardware. Studio modeling / contact / animation utilities are experimental, and are not an automatic AI film generator.

## Install

1. Download `tangyicam-0.4.0-windows-x64.zip` from Releases. Keep it zipped.
2. Blender → Edit → Preferences → Get Extensions → Install from Disk. Enable TangyiCam.
3. Open a copy of your scene. In the 3D View press **N → TangyiCam → 首次設定／更新憑證**.
4. Start the phone camera server. Keep both devices on the same private Wi-Fi; allow only the private-network firewall prompt.
5. Follow the first QR to install and trust the local certificate on iPhone, comparing its SHA-256 fingerprint first.
6. Open the second QR in Safari, enter the one-time code, allow motion sensors, turn the phone landscape and recenter.

[繁體中文完整安裝與排錯](docs/RELEASE_README.md) · [Privacy](docs/PRIVACY.md) · [Device acceptance checklist](docs/TESTING.md)

Recording is camera motion, not live microphone audio. An export creates a new folder beside the blend file (`tc_export`), or in `Documents/TangyiCam/Exports` for an unsaved scene. The download does not include SECONDHAND film scenes or assets.

## Develop and verify

Python 3.10+:

```sh
python -m unittest discover -s tests -p test_security.py
python tools/build.py
```

The build is deterministic and does not install anything unless `--install` is explicitly passed. Artifacts go to `dist/releases/0.4.0/`. On the release source snapshot, the Windows installation archive SHA-256 is:

`d7fbf3658294d37ead532a80085512b134581545c2e46dbfd89f2663e6cff20c`

Run the Blender acceptance scripts with isolated user directories as described in `tests/run_blender_acceptance.py`. Do not point automation at your everyday Blender profile. Real phone sensor permissions, LAN connectivity and long recording sessions require hardware testing; browser automation is not a substitute.

## License and attribution

GPL-3.0-or-later. See [LICENSE](LICENSE) and [third-party notices](tangyicam/THIRD_PARTY_NOTICES.md). The phone-camera design references the GPL Higgsfield for Blender phonecam module; Tangyi Cam adds its own local transport, pairing, recording and workflow tools. It is an independent project, not endorsed by Higgsfield or Blender. No proprietary Higgsfield model is included.

Bundled components retain their own notices: mkcert, QRCode.js, three.js formula attribution and Pillow wheels. No certificates, private keys, user film assets or model weights belong in this repository.

## Feedback

Please include the Tangyi Cam version, Blender / Windows / phone OS versions, steps to reproduce and an error log. Never share pairing codes, private certificates or private scene files. Start with a small scene you are allowed to share.
