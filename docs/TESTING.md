# 發布驗收

自動測試必須從正式安裝 ZIP 解壓後執行，再記錄套件 SHA-256。不得以本機未打包程式的通過結果代替。

- `python tests/test_security.py`：配對、到期、限流、Host/Origin、HTTP 隔離、撤銷與單一控制權。只啟動 loopback 測試服務，不接觸使用者的憑證。
- Blender factory-startup 背景測試：錄製格數、時間對齐、慢動作、獨立 Take、Studio 回歸、存檔重開、實際 MP4格數及輸出失敗處理。
- 瀏覽器測試：配對表單、錯誤提示、離線 QR、匯入鏡表文字安全、重新連線。

## 重現自動驗收

使用 `python tools/build.py` 建置，再用 `python tests/run_blender_acceptance.py --blender "Blender 執行檔路徑"` 從 ZIP 解出程式與測試。此腳本隔離所有 Blender 使用者設定，結果與套件雜湊在 dist/release-qa。

`python tests/install_acceptance.py --blender "Blender 執行檔路徑"` 另驗證 Blender 官方 ZIP 驗證、全新安裝、啟用後重開、停用與重啟；不修改目前使用中的 Blender。

從上述解壓的測試目錄執行 `python tests/test_security.py` 與 `node tests/browser_acceptance.mjs "輸出影格.jpg 路徑"`。瀏覽器測試使用 Node 22+、Python 3.10+、Windows Chrome 的全新暫存設定；可用 CHROME_PATH 指定 Chrome。使用實際 HTTPS 與 WebSocket，不替代 iPhone 感測器驗收。

## iPhone 必做，尚未執行

記錄 iPhone 型號、iOS/Safari、Windows、Blender、安裝包 SHA-256 與日期。

1. 全新設定：安裝 ZIP、建立憑證、掃 QR、安裝／信任憑證、配對成功。
2. 橫向與陀螺儀：左右轉向、抬低、歸零、直向鎖定提示及拒絕權限後的搖桿模式。
3. 搖桿推軌、升降、變焦、穩定器、水平鎖、軌道及鏡表選取。
4. 錄製 30 秒、停止；切背景、關 Wi-Fi，再連線；確認不持續移動、不偷續錄。
5. 連續操作至少 15 分鐘，觀察延遲、發熱與預覽是否持續。
6. 儲存 blend、重開、播放 Take、輸出 MP4與首尾幀，確認動作與焦段一致。
7. 另一手機不輸入配對碼不能查看鏡表或控制；重設配對後舊手機失效。
8. 更新、停用／重啟外掛，再安裝舊版回復時不破壞使用者場景與影片。

以上未完成前可交付發布候選給受邀測試者，不能標成已通過 iPhone 正式驗收。
