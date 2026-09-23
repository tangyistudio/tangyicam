# 本機資料與權限

TangyiCam 不建立雲端帳號、不上傳影片、不傳送使用分析。手機與 Blender 透過區域網路 HTTPS/WebSocket 傳送姿態、按鈕與預覽影像。

手機授權憑證與動作感測器；無需麥克風、手機鏡頭或相簿權限。配對碼只顯示在電腦，工作階段 cookie 使用 HttpOnly、Secure、SameSite=Strict。停止服务會撤銷配對。

根憑證只應來自自己的電腦。CA 私鑰保存在本機 private-ca；網頁只提供公開 rootCA.pem。iPhone 信任根憑證的能力不限於 TangyiCam，因此須核對指紋、不分享私鑰，不使用時可移除描述檔。

檔案權限用於讀鏡表、素材與寫出影片／Blender 場景。Studio 本機 Agent 使用該使用者的檔案佇列，預設需手動啟動；不提供遠端任意 Python 或 shell 入口。使用者自行選擇上傳素材到其他網站，另受該網站政策規範。
