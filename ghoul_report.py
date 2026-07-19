# -*- coding: utf-8 -*-
"""
ghoul_report.py  (v3: 履歴蓄積 → 広範囲(直近N日)判定版)
東京喰種(スロット)の「狙い台まとめ」を毎晩Discordに通知する。

■v3の変更(2026-07-19)
- 前日1日だけでなく「直近N日の実データ」で判定する。
  goraggioは当日ぶんしか取れない(unit_listはtarget_date無効)ため、
  毎晩の当日スナップショットを ghoul_history.json に貯め、
  貯まった直近N日で「好調日数・持玉・稼働」を集計 → 本命/対抗/避け を出す。
  ※初期の過去分は teramoba ヒートマップ読取りで手動シード(src=heatmap)。
- 出力フォーマットを「本命 / 対抗 / 避け」を台番でスパッと出す形に刷新。

データ源: 台DATA ONLINE(goraggio) ピーアーク北綾瀬(店ID 100825)
  - 喰種全台: /unit_list?model=L東京喰種&ballPrice=21.70&ps=S
  - 店全体 : /ranking?ps=S&gb=good   (本日の差玉 = 喰種台の実差玉補完)
毎晩タスクスケジューラ(GhoulReport_Daily 23:00)で実行。
"""
import io, sys, os, re, json, urllib.request, urllib.parse
if sys.stdout is not None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from datetime import datetime, timedelta

BASE = "https://daidata.goraggio.com/dedamajyoho-P-townDMMpachi/100825"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ghoul_history.json")
WINDOW_DAYS = 7          # 判定に使う直近日数
MOCHI_HOT = 3000         # この最大持玉以上を「好調」とみなす
SAMAI_HOT = 2000         # 実差玉がこれ以上でも「好調」
PLAYED_GAMES = 300       # このスタート以上を「稼働あり」


# 喰種島 台番ゾーン(公式ヒートマップより) — reference_piarc_heatmap
def zone(unit):
    if 1 <= unit <= 21:
        return "トーカ"
    if 22 <= unit <= 51:
        return "金木"
    if 52 <= unit <= 81:
        return "有馬"
    return "島外"


def notify(msg: str):
    sys.path.insert(0, r'C:\Users\womca')
    from notify_discord import notify as _notify
    _notify(msg)


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=20).read().decode('utf-8', 'ignore')


def parse_ghoul_units(html):
    """喰種全台の台別データ。col5=最大持玉, col1=累計スタート, col2=BB, col3=RB, col9=合成確率。"""
    out = []
    for r in re.split(r'<tr[ >]', html):
        m = re.search(r'detail\?unit=(\d+)"[^>]*class="Radius-Slot"', r)
        if not m:
            continue
        unit = int(m.group(1))
        cols = dict(re.findall(r'data-column-id="(\d+)">\s*([^<]*?)\s*</td>', r))

        def num(cid):
            v = re.sub(r'[^\d]', '', cols.get(cid, '') or '')
            return int(v) if v else 0

        def fnum(cid):
            m = re.search(r'[\d.]+', cols.get(cid, '') or '')
            try:
                return float(m.group()) if m else 0.0
            except ValueError:
                return 0.0
        out.append({
            'unit': unit, 'mochi': num('5'), 'games': num('1'),
            'bb': num('2'), 'rb': num('3'),
            'art': num('4'),        # ART(AT)回数 — CZ突破≒AT初当りの設定差指標
            'artp': fnum('8'),      # ART確率(1/X の X)。小さいほど良い=高設定寄り
            'synth': (cols.get('9', '') or '').strip(),
        })
    return out


def parse_ranking_all(html):
    """店全体の差玉ランキング全件(機種名, 台番, 差玉)。"""
    units = re.findall(r'summary-unit-no.*?<div>(\d+)番台', html, re.S)
    scores = re.findall(r'summary-score">\s*([\d,]+)', html)
    names = re.findall(r'ranking-card-unit-name.*?detail\?unit=\d+">\s*(L?[^<]+?)\s*</a>', html, re.S)
    out = []
    for u, s, nm in zip(units, scores, names):
        out.append({'unit': int(u), 'score': int(s.replace(',', '')), 'name': nm.strip()})
    return out


# ---------------- 履歴 I/O ----------------
def load_history():
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_history(hist):
    # 直近60日だけ残す
    keys = sorted(hist.keys())
    for k in keys[:-60]:
        hist.pop(k, None)
    with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)


def capture_today(hist):
    """当日のgoraggioスナップショットを取得し hist[today] に格納。データ無しなら格納しない。"""
    gh = fetch(BASE + "/unit_list?" + urllib.parse.urlencode(
        {'model': 'L東京喰種', 'ballPrice': '21.70', 'ps': 'S'}))
    units = parse_ghoul_units(gh)
    samai = {}
    try:
        rk = parse_ranking_all(fetch(BASE + "/ranking?ps=S&gb=good"))
        samai = {e['unit']: e['score'] for e in rk if '東京喰種' in e['name']}
    except Exception:
        pass

    played = [u for u in units if u['games'] >= PLAYED_GAMES]
    if not played:
        return False  # 当日データ未反映/定休 → 保存しない

    today = datetime.now().strftime('%Y-%m-%d')
    rec = {}
    for u in units:
        sm = samai.get(u['unit'])
        is_played = u['games'] >= PLAYED_GAMES
        is_hot = (u['mochi'] >= MOCHI_HOT) or (sm is not None and sm >= SAMAI_HOT)
        if not is_played and not is_hot:
            continue
        rec[str(u['unit'])] = {
            'hot': bool(is_hot), 'played': bool(is_played),
            'mochi': u['mochi'], 'rb': u['rb'], 'games': u['games'],
            'art': u.get('art', 0), 'artp': u.get('artp', 0.0),
            'samai': sm, 'synth': u['synth'], 'src': 'goraggio',
        }
    hist[today] = rec
    return True


# ---------------- 判定 ----------------
def judge(hist):
    """直近WINDOW_DAYS日を集計して 本命/対抗/避け を返す。"""
    dates = sorted(hist.keys())[-WINDOW_DAYS:]
    ndays = len(dates)
    latest = dates[-1] if dates else None
    # unit -> 集計
    agg = {}
    for d in dates:
        for us, r in hist[d].items():
            u = int(us)
            a = agg.setdefault(u, {'hot': 0, 'played': 0, 'mochi': [], 'recent': False})
            if r.get('hot'):
                a['hot'] += 1
            if r.get('played'):
                a['played'] += 1
            if r.get('mochi'):
                a['mochi'].append(r['mochi'])
            if d == latest and r.get('hot'):
                a['recent'] = True

    # 貯まってる日数が浅いうちは「1日でも好調」を本命候補に(閾値を緩める)
    consistent = 2 if ndays >= 3 else 1

    def avg(x):
        return int(sum(x) / len(x)) if x else 0

    def score(u, a):
        return a['hot'] * 10 + (5 if a['recent'] else 0) + avg(a['mochi']) / 1000.0

    honmei, taikou, sake = [], [], []
    for u, a in agg.items():
        if a['hot'] >= consistent:
            honmei.append((u, a))
        elif a['hot'] >= 1:
            taikou.append((u, a))
        elif a['played'] >= 2 and a['hot'] == 0:
            sake.append((u, a))
    honmei.sort(key=lambda x: -score(*x))
    taikou.sort(key=lambda x: -score(*x))
    sake.sort(key=lambda x: -x[1]['played'])
    return ndays, honmei[:5], taikou[:5], sake[:5], (lambda a: avg(a['mochi']))


def build_message(hist):
    ndays, honmei, taikou, sake, avgf = judge(hist)
    tomorrow = datetime.now() + timedelta(days=1)
    L = [
        "🩸【東京喰種 狙い台まとめ】",
        f"📅明日{tomorrow.month}/{tomorrow.day}の据え置き狙い（直近{ndays}日データで判定）",
        "🩸島ゾーン: 1-21トーカ / 22-51金木 / 52-81有馬",
    ]

    def fmt(items, mark):
        out = []
        for u, a in items:
            am = avgf(a)
            extra = []
            if a['hot']:
                extra.append(f"好調{a['hot']}/{ndays}日")
            if am:
                extra.append(f"平均持玉{am:,}")
            if a['played'] and not a['hot']:
                extra.append(f"稼働{a['played']}日/伸び無")
            out.append(f"{mark}{u}番({zone(u)}) " + " ".join(extra))
        return out

    if honmei or taikou or sake:
        if honmei:
            L += ["", "🎯本命(直近よく光る台):"] + fmt(honmei, "・")
        if taikou:
            L += ["", "🥈対抗:"] + fmt(taikou, "・")
        if sake:
            L += ["", "⛔避け(稼働あるのに伸び無):"] + fmt(sake, "・")
    else:
        L += ["", "※直近データ不足。数日ぶん貯まると本命/対抗が出ます。"]

    L += ["", "📌8の日(28/8): 末尾⑧本命だが店長はズラす傾向。朝の毎日仕掛けで答え合わせ必須。"]
    return "\n".join(L)


def main():
    hist = load_history()
    if "--no-capture" not in sys.argv:
        try:
            if capture_today(hist):
                save_history(hist)
        except Exception as e:
            if sys.stdout is not None:
                print(f"[capture失敗] {e}")
    msg = build_message(hist)
    send = "--dry-run" not in sys.argv
    if send:
        notify(msg)
    if sys.stdout is not None:
        print(msg)
        print("\n--- " + ("Discord送信済み" if send else "dry-run(未送信)") + " ---")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        try:
            notify(f"⚠️ ghoul_report.py 実行失敗\n{type(e).__name__}: {str(e)[:200]}")
        except Exception:
            pass
        if sys.stdout is not None:
            print(err)
        raise
