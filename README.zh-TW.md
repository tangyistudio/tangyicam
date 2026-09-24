# Tangyi Cam｜Blender 手機運鏡外掛

[![CI](https://github.com/tangyistudio/tangyicam/actions/workflows/ci.yml/badge.svg)](https://github.com/tangyistudio/tangyicam/actions/workflows/ci.yml)
[![GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-28734f)](LICENSE)

### [▶ 線上 Demo：先玩鏡頭，再安裝](https://tangyistudio.github.io/tangyicam/)

[English / 雙語主頁](README.md) · [免費下載](https://workshop.tangyi.mx/tangyicam) · [Q&A](docs/FAQ.md) · [驗證狀態](docs/QA.md)

**轉動手機控制方向、推動搖桿移動鏡頭，在自己的 Blender 場景裡找角度與節奏。** 錄下運鏡後，回到 Blender 編輯 Take 與關鍵影格，再輸出預覽 MP4 與首尾 PNG。

[![Tangyi Cam：用手機拍 Blender 鏡頭；圖片內為 3D 場景與模擬手機示意](docs/images/tangyicam-phone-blender.jpg)](https://tangyistudio.github.io/tangyicam/)

> 目前提供 **0.4.0 發布候選版**。Windows x64 / Blender 4.5.10 LTS、5.1.2 已有安裝、錄製與輸出測試。**iPhone Safari 真機驗收仍待完成**；不把桌面測試當作真機驗收。

## Demo 可以做什麼？

[![Browser practice demo: real drag-to-look and focal-length changes, not a Blender connection](docs/images/demo-interaction.webp)](https://tangyistudio.github.io/tangyicam/)



1. 拖曳畫面，改變視角。
2. 拖動搖桿或用 WASD／方向鍵移動；Q／E 升降。
3. 拉動焦段滑桿，看看廣角與特寫的差異。
4. 按「錄製練習」，錄下最多 15 秒，再回放你的鏡頭。

這是瀏覽器中的原創幾何練習場，不讀取手機感測器，也不會連接或控制你的 Blender。練習只暫存在記憶體，重整後消失；不匯出 MP4。正式外掛才會在 Blender 中錄下作品。

[30 秒 SECONDHAND 操作示意影片](https://media.tangyi.mx/opensource/20260924/tangyicam-secondhand-30s.mp4) 使用電影場景與模擬手機操作，不是真機驗收錄影。

## 正式外掛功能

- 手機陀螺儀控制方向，螢幕搖桿控制移動；支援焦段、歸零、穩定器與水平鎖。
- 同一私人 Wi-Fi，透過本機 HTTPS 與一次性六位碼配對。
- 每次錄製為獨立 Take，可在 Blender 編輯關鍵影格。
- 輸出預覽 MP4、first.png、last.png，成果留在本機。
- 不需要 LLM、Workshop 會員、雲端生成額度或額外的原生手機 App。

**不是手機走位的 6DOF 追蹤，也不是 AI 自動生成電影工具。** 預覽效果依場景、硬體及網路而異；Studio 進階工具仍屬實驗功能。

## 六步開始

1. 下載 Windows 安裝 ZIP，保持壓縮狀態。
2. Blender 偏好設定 → 從磁碟安裝，啟用 TangyiCam。
3. 3D 視窗按 N → TangyiCam → 首次設定／更新憑證。
4. 電腦與手機連上同一私人 Wi-Fi，啟動手機攝影機服務。
5. 依第一個 QR 安裝並信任本機憑證；先核對 SHA-256 指紋。
6. Safari 開啟第二個 QR，輸入新的一次性配對碼、允許感測，橫放手機並歸零。

[完整六步圖文教學](https://workshop.tangyi.mx/tangyicam#setup) · [詳細安裝說明](docs/RELEASE_README.md)

## Q&A 與排錯

| 問題 | 簡答 |
|---|---|
| 免費嗎？ | 免費開源，GPL-3.0-or-later；攝影機控制不需付雲端額度 |
| 要裝手機 App 嗎？ | 不必另裝原生 App；手機用瀏覽器，電腦安裝 Blender 外掛 |
| 拿手機走動就能追蹤位置？ | 不會；方向靠陀螺儀、位置靠搖桿 |
| 哪些平台已驗證？ | Windows x64 + 兩個指定 Blender 版本；iPhone 真機待驗收 |
| 可以錄聲音嗎？ | 錄製運鏡與預覽，不含手機麥克風音訊 |
| 可以下載電影場景嗎？ | 不包含 SECONDHAND 電影場景 |
| 為什麼連不上？ | 先看 Wi-Fi、LAN IP、服務、憑證與新配對碼，再依排錯表處理 |

[完整 Q&A 與排錯表](docs/FAQ.md)

## 如何驗證

[QA 說明](docs/QA.md) 將瀏覽器 Demo、安全整合測試與真機驗收分開記錄。CI 綠燈不代表 iPhone 已驗收，也不代表所有 Blender 場景都流暢。

```sh
node --test test/demo-camera.test.mjs
python tools/check_docs.py
node tools/qa-demo.mjs
```

Windows 安全測試：

```sh
python -m unittest discover -s tests -p test_security.py
```

完整 Blender 與 iPhone 步驟見 [TESTING.md](docs/TESTING.md)。

## 文件與回報

[版本說明](docs/CHANGELOG.md) · [隱私](docs/PRIVACY.md) · [貢獻指南](CONTRIBUTING.md) · [安全回報](SECURITY.md)

[回報問題](https://github.com/tangyistudio/tangyicam/issues/new/choose) 請附版本、重現步驟、預期與實際結果。不要附私人場景、配對碼或憑證私鑰。

## 授權與致謝

程式與原創幾何練習場為 GPL-3.0-or-later。參考 Higgsfield for Blender 的 GPL phonecam 設計，並加入本地連線、配對、錄製與工作流程；本專案獨立開發，未獲 Higgsfield 或 Blender 背書。第三方元件保留其授權，見 [第三方聲明](tangyicam/THIRD_PARTY_NOTICES.md)。

產品圖片與 SECONDHAND 示範影片 © Tangyi Studio，不因程式開源而隨同授權。見 [媒體聲明](docs/MEDIA.md)。
