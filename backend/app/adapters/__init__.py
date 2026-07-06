"""資料源 adapter 套件：各具體來源（日價量、籌碼、分點、除權息…）皆放在此套件下的模組，
並在自己的模組內用 `app.adapters.registry.register` 自我註冊。

本檔特意不 import 任何具體 adapter 模組——`registry.discover()` 靠 `pkgutil` 掃描本套件
底下的模組來觸發註冊，若在此手動 import 會與該機制重複、也違反「不手動維護來源清單」的設計。
"""
