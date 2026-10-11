# grok-bot-patch-away

[English](README.en.md)

Grok Bot 在視窗離開前景大約 10 分鐘後，會把這台電腦標成 away，雲端電腦跟著睡著，本機指令通道也會斷掉。程式開著、人在用別的視窗時也會發生。

這個腳本改的是本機安裝檔 `app.asar` 裡的那個判斷，讓視窗不在前景、螢幕鎖定、系統暫停都不會標成 away。電腦睡眠時程式本來就暫停；醒過來時不會卡在 away。

它用穩定的屬性名稱 `isSuspended`、`isScreenLocked`、`unfocusedSinceMs` 尋找判斷式，不依賴壓縮後的函式名稱或位元組位移，並重算該檔的 asar SHA256。標頭後面 0 到 3 個位元組的對齊填充也可以讀。

## 使用

完全退出 Grok Bot 後：

```bash
sudo python3 grok-bot-patch-away.py
```

只看會改哪個檔、不寫入：

```bash
python3 grok-bot-patch-away.py --dry-run
```

安裝路徑不在預設位置時，把 `app.asar` 傳進去：

```bash
sudo python3 grok-bot-patch-away.py "/opt/Grok Bot/resources/app.asar"
```

預設會找這些路徑：

- Linux：`/opt/Grok Bot/resources/app.asar`
- macOS：`/Applications/Grok Bot.app/Contents/Resources/app.asar`
- Windows：`%LOCALAPPDATA%\Programs\Grok Bot\resources\app.asar`

第一次套用會在同目錄留下 `app.asar.bak-before-away-patch`。再跑一次已經修過的檔案不會重複改。還原：

```bash
sudo python3 grok-bot-patch-away.py --restore
```

Grok Bot 更新會蓋掉 `app.asar`。更新後再執行一次。

套用之後要完全退出再打開，正在跑的程式仍用舊的程式碼。

## 它改了什麼

原本的條件大致是：

```text
isSuspended || isScreenLocked || unfocusedSinceMs !== null && 距今 >= 10 分鐘
```

腳本把整段 `return` 換成等長的 `return!1`。三個條件都不再成立。舊版腳本如果只改過「視窗不在前景」，再跑一次會補上鎖屏和暫停。

如果這版的寫法對不上，腳本會停下來，不會寫入一個過不了完整性檢查的 asar。

## 限制

需要 Python 3，以及對安裝目錄的寫入權限。這是本機客戶端的修改，不是 Grok Bot 的設定項。鎖屏或睡眠時，雲端電腦不會因此被要求睡著；電腦真正睡眠時，本機指令仍然無法執行，直到喚醒。
