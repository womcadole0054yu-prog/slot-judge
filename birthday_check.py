# -*- coding: utf-8 -*-
"""
birthday_check.py
翌日が誕生日のパチスロ関連アニメキャラをchar_birthdays.jsonから探してDiscord通知する。
毎日20:00にタスクスケジューラ(SlotCharBirthday_Daily)で実行。
該当なしの日は通知しない(ノイズ防止)。
"""
import io, sys, json
if sys.stdout is not None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(r"C:\Users\womca\slot-judge\char_birthdays.json")

def notify(msg: str):
    sys.path.insert(0, r'C:\Users\womca')
    from notify_discord import notify as _notify
    _notify(msg)

def main():
    tomorrow = datetime.now() + timedelta(days=1)
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    hits = [b for b in db["birthdays"]
            if b["month"] == tomorrow.month and b["day"] == tomorrow.day]

    if not hits:
        if sys.stdout is not None:
            print(f"明日({tomorrow.month}/{tomorrow.day})誕生日のキャラなし")
        return

    lines = [f"🎂 明日{tomorrow.month}/{tomorrow.day}誕生日のパチスロキャラ！"]
    for b in hits:
        mark = "✅" if b.get("verified") else "⚠️未検証"
        lines.append(f"・{b['character']}（{b['machine']}）{mark}")
    lines.append("")
    lines.append("キャラ誕投入の可能性あり。匂わせ解読と合わせて要チェック🎰")
    msg = "\n".join(lines)
    notify(msg)
    if sys.stdout is not None:
        print(msg)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        try:
            notify(f"⚠️ birthday_check.py 実行失敗\n{type(e).__name__}: {str(e)[:200]}")
        except Exception:
            pass
        if sys.stdout is not None:
            print(err)
        raise
