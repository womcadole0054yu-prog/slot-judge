# -*- coding: utf-8 -*-
"""
build_ghoul_navi.py
喰種狙い台ナビ(スマホWeb)の静的HTMLを生成する。
- 狙い台: ghoul_report v3 の判定(goraggio実データ蓄積→直近N日)を再利用
- 匂わせ本命: slot-judge/hint.json の翌日チェーンから抽出
- デザイン: vol.14表紙(ghoul_cover.txt=data URI)背景・ダーク×血赤×金トロ金・フロストガラス
出力: slot-judge/ghoul_navi.html (自己完結)。毎晩ghoul_report後に生成→push[deploy]でNetlify更新。
"""
import sys, os, re, json
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ghoul_report as gr  # 判定ロジック再利用

HINT_PATH = os.path.join(HERE, 'hint.json')
COVER_PATH = os.path.join(HERE, 'ghoul_cover.txt')
OUT_PATH = os.path.join(HERE, 'ghoul_navi.html')


def mochi_of(agg_unit_records, unit):
    return 0


MIN_GAMES_AT = 1000  # AT確率を信頼する最低スタート数

def collect_targets():
    """直近N日を集計。据え置き狙いの本質＝設定なので、AT初当り(≒CZ突破)確率を主軸に
    本命/対抗/避けを返す。AT確率が良い(1/Xが小さい)台を上位に。持玉は補助。
    ※データ蓄積(capture)は毎晩ghoul_report.pyが担当。ここは読むだけ(日付ズレ防止)。"""
    hist = gr.load_history()
    dates = sorted(hist.keys())[-gr.WINDOW_DAYS:]
    ndays = len(dates)
    latest = dates[-1] if dates else None

    info = {}  # unit -> {artp(良い=小), peak, played, games}
    for d in dates:
        for us, r in hist[d].items():
            u = int(us)
            a = info.setdefault(u, {'artp': 0.0, 'peak': 0, 'played': 0, 'games': 0})
            ap = r.get('artp', 0) or 0
            g = r.get('games', 0) or 0
            if g >= MIN_GAMES_AT and ap > 0:
                a['artp'] = ap if a['artp'] == 0 else min(a['artp'], ap)
            a['peak'] = max(a['peak'], r.get('mochi', 0) or 0)
            a['games'] = max(a['games'], g)
            if r.get('played'):
                a['played'] += 1

    # AT確率あり→良い順(昇順) / 無し→持玉降順で後ろに付ける
    with_at = sorted([u for u, a in info.items() if a['artp'] > 0],
                     key=lambda u: info[u]['artp'])
    no_at = sorted([u for u, a in info.items() if a['artp'] == 0 and a['peak'] > 0],
                   key=lambda u: -info[u]['peak'])
    ranked = with_at + no_at
    honmei = ranked[:6]
    taikou = ranked[6:18]
    # 避け: 稼働あるのにAT確率が重い(>120) か、AT無しで持玉も低い
    sake = sorted([u for u, a in info.items()
                   if a['played'] >= 1 and ((a['artp'] > 120) or (a['artp'] == 0 and a['peak'] < 1200))],
                  key=lambda u: (info[u]['artp'] if info[u]['artp'] > 0 else 999, -info[u]['peak']),
                  reverse=True)[:12]
    return ndays, latest, honmei, taikou, sake, info


def parse_hint_machines():
    """hint.json から『最新の解読済み実戦日』(今日以降の最大jissen_date)のチェーンを機種単位に集約。"""
    today = datetime.now().strftime('%Y-%m-%d')
    with open(HINT_PATH, encoding='utf-8') as f:
        data = json.load(f)
    future = [c.get('jissen_date', '') for c in data.get('chains', []) if c.get('jissen_date', '') >= today]
    tomorrow = max(future) if future else (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    seen, out = set(), []
    for ch in data.get('chains', []):
        if ch.get('jissen_date') != tomorrow:
            continue
        path = ch.get('path', [])
        if not path:
            continue
        machine = path[-1]
        if machine in seen:
            continue
        seen.add(machine)
        note = ch.get('note', '')
        stars = 3 if '⭐⭐⭐' in note or '★★★' in note else (2 if '⭐⭐' in note or '★★' in note else 1)
        need_check = '要確認' in note
        out.append({'machine': machine, 'stars': stars, 'check': need_check, 'note': note})
    # 星→要確認→の順で並べ、上位4件
    out.sort(key=lambda m: (-m['stars'], m['check']))
    return out[:4], tomorrow


def why_line(note):
    """noteから根拠の短文を作る(先頭の記号や定型を削って要約)。"""
    t = re.sub(r'^[🎯🌟⭐★☆\s]*', '', note)
    t = re.split(r'。|\[|【', t)
    frag = t[1] if len(t) > 1 and t[0].startswith(('本命', '対抗', '参考')) else t[0]
    return frag.strip()[:34]


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def chip(unit, zone, cls, crown=False, sub=''):
    c = cls + (' crown' if crown else '')
    inner = f"{unit}" + (f"<small>{esc(sub)}</small>" if sub else "")
    return f'<div class="n {c}">{inner}</div>'


def zone_block(label, chips):
    return (f'<div class="zone"><span class="zlabel">{esc(label)}</span>'
            f'<div class="nums">{"".join(chips)}</div></div>')


def build():
    ndays, latest, honmei, taikou, sake, info = collect_targets()
    machines, tomorrow = parse_hint_machines()
    td = datetime.now() + timedelta(days=1)

    def atsub(u):
        d = info.get(u, {})
        ap, g = d.get('artp', 0), d.get('games', 0)
        if ap > 0:
            gs = f"·{g/1000:.1f}k" if g else ''
            return f"1/{int(round(ap))}{gs}"     # AT確率·ゲーム数(信頼度)
        return f"{d.get('peak', 0):,}" if d.get('peak', 0) >= 3000 else ''

    # ---- 本命(AT初当り確率が良い順。上位2つは王冠) ----
    hon_chips = []
    for i, u in enumerate(honmei[:8]):
        crown = i < 2
        hon_chips.append(chip(u, gr.zone(u), 'n-honmei', crown=crown, sub=atsub(u)))
    honmei_html = (f'<div class="zone"><span class="zlabel">AT初当り(CZ)確率が良い順＝設定期待</span>'
                   f'<div class="nums">{"".join(hon_chips)}</div></div>'
                   if hon_chips else '<div class="tier-note">本日データ待ち（今夜23時に生成）</div>')

    # ---- 対抗(ゾーン別) ----
    def by_zone(units, z):
        return [u for u in units if gr.zone(u) == z]
    taikou_zblocks = []
    for zlabel in ('有馬', '金木', 'トーカ'):
        us = by_zone(taikou, zlabel)
        if us:
            taikou_zblocks.append(zone_block(f'{zlabel}パネル',
                [chip(u, zlabel, 'n-taikou', sub=atsub(u)) for u in us[:10]]))
    taikou_html = "".join(taikou_zblocks) or '<div class="tier-note">—</div>'

    # ---- 避け ----
    sake_chips = [chip(u, gr.zone(u), 'n-sake') for u in sake[:12]]
    sake_html = f'<div class="nums">{"".join(sake_chips)}</div>' if sake_chips else '<div class="tier-note">—</div>'

    # ---- 匂わせ ----
    mrows = []
    for m in machines:
        top = ' top' if m['stars'] >= 3 else ''
        right = ('<span class="flag">要確認</span>' if m['check']
                 else f'<span class="stars">{"★"*m["stars"]}</span>')
        mrows.append(
            f'<div class="m{top}"><div class="name">{esc(m["machine"])}'
            f'<span class="why">{esc(why_line(m["note"]))}</span></div>{right}</div>')
    machines_html = "".join(mrows) or '<div class="tier-note">明日の匂わせ未登録</div>'
    check_note = ('獣王など「要確認」機種は現物未設置の可能性。導入日なら新台初日で最有力、無ければ喰種が実質本命。'
                  if any(m['check'] for m in machines) else
                  '匂わせ本命は据え置き傾向と合わせて狙う。')

    stamp = f"データ：{latest or '—'} 実績（据え置き狙い・直近{ndays}日 r=0.83）" if latest else "データ：本日分待ち（今夜23時生成）"

    html = TEMPLATE
    for k, v in {
        '__DBADGE__': f"{td.month}/{td.day}",
        '__STAMP__': esc(stamp),
        '__HONMEI__': honmei_html,
        '__TAIKOU__': taikou_html,
        '__SAKE__': sake_html,
        '__MACHINES__': machines_html,
        '__CHECKNOTE__': esc(check_note),
        '__GENTS__': datetime.now().strftime('%Y/%m/%d %H:%M'),
    }.items():
        html = html.replace(k, v)

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"生成: {OUT_PATH} ({len(html):,} bytes)")
    print(f"  本命{len(honmei)} 対抗{len(taikou)} 避け{len(sake)} / 匂わせ{len(machines)}件 / データ日={latest} 直近{ndays}日")


TEMPLATE = r"""<title>北綾瀬 喰種狙い台ナビ</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
  :root{
    --bg:#0b0708;--card:#180d10;--line:#2a171b;--ink:#f3e9e9;--sub:#b79aa0;--mute:#7a626a;
    --blood:#d21f2e;--blood-deep:#8f1420;--gold:#e6b84a;--amber:#e08a2b;--cool-bg:#141b22;
    --hot-bg:#2a0f12;--amber-bg:#241608;--radius:16px;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#060404;color:var(--ink);
    font-family:"Hiragino Kaku Gothic ProN","Yu Gothic","YuGothic","Meiryo",system-ui,sans-serif;
    -webkit-font-smoothing:antialiased;line-height:1.5;padding:env(safe-area-inset-top) 0 40px;min-height:100vh;}
  body::before{content:"";position:fixed;inset:0;z-index:-2;
    background:
      radial-gradient(92% 55% at 50% -8%,rgba(210,31,46,.30),transparent 60%),
      radial-gradient(70% 42% at 86% 10%,rgba(143,20,32,.24),transparent 55%),
      radial-gradient(85% 55% at 8% 34%,rgba(120,10,20,.20),transparent 60%),
      #060404;}
  body::after{content:"";position:fixed;inset:0;z-index:-1;
    background:
      linear-gradient(180deg,transparent 0%,rgba(6,4,4,.45) 62%,#060404 100%),
      repeating-linear-gradient(118deg,rgba(210,31,46,.045) 0 2px,transparent 2px 24px);}
  .wrap{max-width:460px;margin:0 auto;padding:0 16px;position:relative;z-index:1}
  header{padding:44px 4px 16px;display:flex;align-items:flex-end;justify-content:space-between;gap:12px}
  .brand{display:flex;flex-direction:column;gap:4px}
  .brand .k{font-size:12px;letter-spacing:.22em;color:#ff5661;font-weight:700;text-shadow:0 2px 10px #000}
  .brand h1{font-size:25px;font-weight:800;letter-spacing:.01em;line-height:1.12;text-shadow:0 2px 16px rgba(0,0,0,.85),0 0 30px rgba(0,0,0,.6)}
  .brand h1 .drip{color:var(--blood);text-shadow:0 0 18px rgba(210,31,46,.6)}
  .datebadge{text-align:right;flex-shrink:0;background:linear-gradient(160deg,var(--blood),var(--blood-deep));
    color:#fff;border-radius:12px;padding:8px 12px;box-shadow:0 4px 14px -4px #d21f2e66;}
  .datebadge .d{font-size:19px;font-weight:800;line-height:1}
  .datebadge .l{font-size:10px;letter-spacing:.14em;opacity:.85;margin-top:3px}
  .stamp{font-size:11.5px;color:var(--mute);padding:0 4px 14px;display:flex;align-items:center;gap:6px}
  .dot{width:6px;height:6px;border-radius:50%;background:var(--gold);box-shadow:0 0 8px var(--gold)}
  .card{background:rgba(16,9,11,.68);-webkit-backdrop-filter:blur(14px) saturate(1.15);backdrop-filter:blur(14px) saturate(1.15);
    border:1px solid rgba(120,42,50,.30);border-radius:var(--radius);padding:16px 15px;margin-bottom:14px;
    box-shadow:0 14px 34px -18px #000,inset 0 1px 0 rgba(255,255,255,.05)}
  .card h2{font-size:13px;letter-spacing:.04em;color:var(--sub);font-weight:700;display:flex;align-items:center;gap:8px;margin-bottom:14px}
  .card h2 b{color:var(--ink);font-size:15px;font-weight:800}
  .tier{margin-bottom:15px}.tier:last-child{margin-bottom:0}
  .tier-head{display:flex;align-items:baseline;gap:8px;margin-bottom:9px}
  .badge{font-size:11px;font-weight:800;padding:3px 9px;border-radius:999px;letter-spacing:.06em;flex-shrink:0}
  .b-honmei{background:var(--hot-bg);color:#ff6b76;border:1px solid #4a1a20}
  .b-taikou{background:var(--amber-bg);color:var(--amber);border:1px solid #4a3110}
  .b-sake{background:var(--cool-bg);color:#8fa6bb;border:1px solid #2b3945}
  .tier-note{font-size:11.5px;color:var(--mute)}
  .rack{display:flex;flex-wrap:wrap;gap:14px}
  .zone{display:flex;flex-direction:column;gap:5px}
  .zlabel{font-size:10px;letter-spacing:.1em;color:var(--mute);padding-left:2px}
  .nums{display:flex;flex-wrap:wrap;gap:6px}
  .n{min-width:54px;height:42px;padding:0 4px;display:flex;flex-direction:column;align-items:center;justify-content:center;
    border-radius:10px;font-weight:800;font-size:16px;font-variant-numeric:tabular-nums;position:relative}
  .n small{font-size:8.5px;font-weight:600;letter-spacing:.01em;opacity:.78;margin-top:1px;white-space:nowrap}
  .n-honmei{background:linear-gradient(165deg,#d21f2e,#7c1019);color:#fff;box-shadow:0 3px 10px -3px #d21f2e88}
  .n-honmei.crown{background:linear-gradient(165deg,#e6b84a,#a37a1e);color:#241205;box-shadow:0 3px 12px -2px #e6b84a99}
  .n-taikou{background:#241608;color:var(--amber);border:1px solid #4a3110}
  .n-sake{background:var(--cool-bg);color:#7f97ab;border:1px solid #2b3945;opacity:.85;font-size:14px;height:34px;min-width:32px}
  .hl{background:var(--hot-bg);border:1px solid #3a151a;border-radius:12px;padding:10px 12px;font-size:12.5px;color:#f0c9cd;margin-top:13px;display:flex;gap:8px;align-items:flex-start}
  .hl b{color:var(--gold)}
  .machines{display:flex;flex-direction:column;gap:8px}
  .m{display:flex;align-items:center;gap:11px;padding:11px 12px;border-radius:12px;background:#160c0e;border:1px solid var(--line)}
  .m.top{border-color:#4a1a20;background:linear-gradient(100deg,#220d10,#160c0e)}
  .m .name{font-weight:800;font-size:15px;flex:1}
  .m .why{font-size:11px;color:var(--mute);font-weight:500;display:block;margin-top:2px}
  .stars{font-size:12px;letter-spacing:1px;color:var(--gold);flex-shrink:0}
  .flag{font-size:10px;font-weight:800;color:#ffb84d;background:#3a2708;border:1px solid #5a3d10;padding:2px 7px;border-radius:999px;flex-shrink:0;white-space:nowrap}
  .actions{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:4px}
  .btn{display:flex;align-items:center;justify-content:center;gap:7px;height:52px;border-radius:14px;font-weight:800;font-size:15px;text-decoration:none;border:none;cursor:pointer;font-family:inherit}
  .btn-primary{background:linear-gradient(160deg,#d21f2e,#8f1420);color:#fff;box-shadow:0 6px 18px -6px #d21f2e88}
  .btn-ghost{background:#180d10;color:var(--ink);border:1px solid var(--line)}
  .btn:active{transform:translateY(1px)}.btn:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
  footer{text-align:center;font-size:11px;color:var(--mute);padding:20px 8px 0;line-height:1.7}
  footer b{color:var(--sub)}
</style>
<div class="wrap">
  <header>
    <div class="brand"><span class="k">ピーアーク北綾瀬</span><h1>東京喰種 <span class="drip">狙い台ナビ</span></h1></div>
    <div class="datebadge"><div class="d">__DBADGE__</div><div class="l">実戦</div></div>
  </header>
  <div class="stamp"><span class="dot"></span>__STAMP__</div>
  <section class="card">
    <h2>🩸 <b>喰種 狙い台</b>（有馬 / 金木 / トーカ）</h2>
    <div class="tier"><div class="tier-head"><span class="badge b-honmei">本命</span><span class="tier-note">前日持玉上位＝据え置き最有力</span></div>__HONMEI__</div>
    <div class="tier"><div class="tier-head"><span class="badge b-taikou">対抗</span><span class="tier-note">好調ゾーン継続</span></div><div class="rack">__TAIKOU__</div></div>
    <div class="tier"><div class="tier-head"><span class="badge b-sake">避け</span><span class="tier-note">稼働あるのに伸びない台</span></div>__SAKE__</div>
    <div class="hl">🔥<div>順位は<b>AT初当り(CZ)確率</b>基準＝設定を映す指標(<b>1/X</b>が小さいほど期待大)。併記の<b>◯k</b>=総ゲーム数で信頼度(多いほど確か)。据え置き型(r=0.83)で翌日も残る公算。持玉は結果でブレるため補助。</div></div>
  </section>
  <section class="card">
    <h2>🔮 <b>とみー匂わせ本命</b></h2>
    <div class="machines">__MACHINES__</div>
    <div class="hl" style="background:var(--amber-bg);border-color:#4a3110;color:#f0d6a8">⚠️<div>__CHECKNOTE__</div></div>
  </section>
  <div class="actions">
    <a class="btn btn-primary" href="https://p-ark.pt.teramoba2.com/extends/1494/heatmap" target="_blank" rel="noopener">📊 ヒートマップ</a>
    <button class="btn btn-ghost" id="reload" type="button">↻ 更新</button>
  </div>
  <footer>据え置き型（前日好調台＝翌日も好調 <b>r=0.83</b>）＋goraggio実データで自動判定。<br>毎晩23時 <b>ghoul_report</b> が自動更新。生成: __GENTS__</footer>
</div>
<script>
  document.getElementById('reload').addEventListener('click',function(){location.reload(true);});
</script>
"""

if __name__ == '__main__':
    build()
