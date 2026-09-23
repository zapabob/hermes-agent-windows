# Hermes 分階段工程實作

本功能依序執行規劃、實作及主機驗證，不是 MoA，也不是供應商故障備援。
啟用 `implementation_router` 外掛，於既有輔助模型選擇器設定 `engineering_planner`、`engineering_worker` 與 `engineering_reviewer`。可選擇已設定供應商支援的任意模型；無法使用時停止，不暗中切換模型。
在外掛設定指定不含秘密的 `source_paths`、受保護驗收測試 `protected_paths`、事先準備的映像摘要及固定驗證指令 `checks`。執行 `/engineer {"workspace":"sample","task":"以TDD實作所需變更"}`。
憑證及推論用戶端只保留於父 Hermes 主機。子孫程序在全新且經檢查的 Docker 環境執行，不繼承主機憑證掛載、環境變數或網路。Windows 主機同樣需要 Linux Docker 引擎，不會退回一般本機 shell。
成功後回傳驗證過的工作區副本，不直接修改原始檢出目錄，也不自動合併 PR。須檢查最終提交的 CI 與原生驗收結果；模擬推論測試不代表真實帳戶的使用權限。
空環境變數不等於作業系統隔離。主機、Docker 常駐程式、映像與信任的外掛構成信任基礎。請檢查原始碼中是否嵌入秘密。殘留 lease 須由操作者調查後復原，不自動重跑完成狀態不明的工作。

<!-- routing-not-moa -->
<!-- credentials-host-only -->
<!-- native-adapter-requirements -->
<!-- not-os-sandbox -->

[Agent protocol](../AGENT_PROTOCOL.md)

各階段的推理設定依角色固定，並在父程序的請求邊界驗證 medium/medium/high，而非依介面標籤推定。封鎖結果可附帶不洩漏憑證的固定診斷碼。請保留 lease 與 journal；診斷不代表取得重新執行的許可。
