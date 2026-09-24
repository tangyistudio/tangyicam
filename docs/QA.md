# QA / 驗證範圍

[Live Demo](https://tangyistudio.github.io/tangyicam/) · [Q&A](FAQ.md) · [目前 CI 結果](https://github.com/tangyistudio/tangyicam/actions/workflows/ci.yml)

## 分開看三種證據

| 範圍 | 驗證方式 | 能證明什麼 | 不能代替什麼 |
|---|---|---|---|
| 瀏覽器 Demo | 7 個攝影機模型測試；1440、1061、768、390、320px 互動檢查 | 逐像素遮擋／近裁切、投影、焦段、移動、錄製回放、觸控取消與焦點遺失停止 | Blender 執行效能、手機陀螺儀與私人 Wi-Fi 實測 |
| 外掛安全控制 | 12 個 loopback HTTPS／WebSocket 整合測試 | 配對到期／撤銷、限流、Host／Origin、單一控制權、TLS 隔離 | 實體 LAN、憑證手動安裝、手機溫度與長時間錄影 |
| Blender 0.4.0 RC | 既有 Windows x64 / Blender 4.5.10 LTS、5.1.2 安裝／錄製／輸出驗收 | 發布候選套件在這些版本的已測流程 | 所有 Blender／OS 版本，或 iPhone 正式驗收 |

2026-09-24 的 Demo／文件更新未修改外掛程式，也沒有重新執行完整 Blender 驗收。已發布安裝包的校驗值不變。實際 iPhone 驗收仍待完成，請見 [TESTING.md](TESTING.md)。

## 本機重現

需要 Node.js 22+、Python 3.10+、Chrome。

```sh
node --test test/demo-camera.test.mjs
python tools/check_docs.py
node tools/qa-demo.mjs
```

`qa-demo.mjs` 會啟動隔離的 loopback 靜態伺服器與全新 Chrome 暫存設定，輸出到 `dist/demo-qa/`。以 `CHROME_PATH` 指定 Chrome 路徑；`QA_OUT` 可指定報告位置；`DEMO_URL` 可檢查已部署的 Demo。它不存取使用者的瀏覽器設定與登入資料。渲染檢查使用 Chrome 隔離設定中的 SwiftShader 軟體渲染，方便無 GPU 的 CI 重現；不能代替真機 GPU 效能驗證。啟動最長等候 30 秒，若失敗會保留 Chrome 的錯誤輸出。

瀏覽器檢查會真的派送滑鼠與觸控輸入，確認：
- WebGL 像素檢查：前後提交順序皆正確遮擋、穿越近裁切面的三角形保留可見部分、格線不穿透物件、箱體底面封閉、繪圖環境中斷後重建。
- WebGL 無法啟用時顯示說明與影片連結，停用無法使用的控制項。另保存場景起始、側面、近距離、低角度與高角度截圖供目視檢查。
- 拖曳改變視角、搖桿／鍵盤改變位置、焦段改變構圖。
- 放開／取消觸控／視窗失焦後不持續移動。
- 錄製後回放回到正確末狀態；失焦停止錄製。
- 1440／1061／768／390／320px 無水平溢位，手機外框保持 2:1 橫式且控制項不溢出，Q&A 可展開，沒有未處理 JavaScript 例外。

Windows 上可執行安全整合測試：

```sh
python -m unittest discover -s tests -p test_security.py
```

使用臨時本機憑證與 loopback 伺服器，不使用你的配對碼或日常憑證。CI 的 demo job 在 Linux Chrome 測試這個網頁，不表示 Blender 外掛已支援 Linux；外掛安全 job 使用 Windows Python 3.11／3.13。

## 發布套件與真機驗收

正式 ZIP 的驗收必須從 ZIP 解壓的程式進行，並附 SHA-256；工作目錄的測試不能替代。依 [完整驗收清單](TESTING.md) 執行。

Windows v0.4.0 安裝包 SHA-256：

`d7fbf3658294d37ead532a80085512b134581545c2e46dbfd89f2663e6cff20c`

iPhone 仍需親自完成感測器授權、橫向／歸零、斷線、15 分鐘連續操作、錄製與重開輸出。CI 顯示綠燈不代表這些真機項目已完成。
