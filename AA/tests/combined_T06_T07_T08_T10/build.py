"""Combine T06 / T07 / T08 / T10 headline NAVs (20.8 bps, LBES cash) into one chart + stats, and add the pre-2019 period (T09 and the extras).
Reads only the tests' evidence/headline CSVs and tests/T09/extra/combined_daily_nav_20.8bps.csv + combined_stats.csv. Run: python build.py"""
import pandas as pd, numpy as np, json

T = '..'
H = lambda t, f: pd.read_csv(f'{T}/{t}/evidence/headline/{f}')
SER = [  # label, test file, run kind in that file's daily_nav, key
    ('Parent (hold)', 'T10', 'parent', 'parent'),
    ('T06 3-index switch (50/50 GOLDBEES+LiquidBees)', 'T10', 'switch', 't06'),
    ('T07 Stock rule', 'T07', 'segment', 't07'),
    ('T08 3-index + gold trend (80/20 or 20/80)', 'T08', 'strategy', 't08'),
    ('T10 FS >= 0.6', 'T10', 'rule', 't10')]
nav = {t: H(t, 'daily_nav.csv') for t in ['T07', 'T08', 'T10']}
st = {t: H(t, 'stats.csv') for t in ['T06', 'T07', 'T08', 'T10']}
books = ['SCMO_0003', 'SCMO_0007', 'SCMO_0010', 'SCMO_0029']


def metrics(s):
    s = s.dropna(); n = len(s); yrs = (n - 1) / 252; r = s.pct_change().dropna()
    dd = s / s.cummax() - 1; mdd = dd.min()
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    uw = 0; m = 0
    for v in dd.values:
        uw = uw + 1 if v < 0 else 0; m = max(m, uw)
    return dict(end_nav=s.iloc[-1] / s.iloc[0], cagr=cagr, max_dd=mdd, vol=r.std() * np.sqrt(252),
                ulcer=float(np.sqrt(((dd * 100) ** 2).mean())), days_below_10pct=int((dd <= -0.10).sum()),
                longest_underwater=m, calmar=cagr / abs(mdd), sessions=n)


rows = []; chart = {}; chk = []
for b in books:
    chart[b] = {}
    for label, t, run, key in SER:
        d = nav[t]; d = d[(d.book == b) & (d.cost_bps == 20.8) & (d.run == run)].set_index('date').nav
        chart[b][key] = d
        s_ = st[t]; s_ = s_[(s_.book == b) & (s_.kind == run) & (s_.cost_bps == 20.8) & (s_.window == 'full') & (s_.cash == 'lbes')].iloc[0]
        mf = metrics(d)
        chk.append((abs(s_.end_nav - d.iloc[-1]), abs(s_.cagr - mf['cagr']), abs(s_.max_dd - mf['max_dd'])))
        dl = d[d.index >= '2021-11-01']
        for win, s in [('full', d), ('live (2021-11-01 on)', dl / dl.iloc[0])]:
            m = metrics(s)
            m.update(book=b, series=label, key=key, window=win, start=s.index[0], end=s.index[-1],
                     trades=s_.trades if win == 'full' else None, invested_weeks=s_.invested_weeks if win == 'full' else None)
            rows.append(m)
S = pd.DataFrame(rows)
cols = ['book', 'window', 'series', 'start', 'end', 'end_nav', 'cagr', 'max_dd', 'vol', 'ulcer', 'calmar',
        'days_below_10pct', 'longest_underwater', 'trades', 'invested_weeks', 'sessions']
S[cols].to_csv('combined_stats.csv', index=False)
wide = pd.concat({b: pd.DataFrame(chart[b]) for b in books}, axis=1)
wide.columns = [f'{a}__{k}' for a, k in wide.columns]
wide.to_csv('combined_daily_nav.csv')
print('cross-check vs each test stats.csv, max abs diff: end_nav %.2e cagr %.2e max_dd %.2e' % tuple(max(c[i] for c in chk) for i in range(3)))
p = st['T06']
p = p[(p.kind == 'strategy') & (p.cost_bps == 20.8) & (p.window == 'full') & (p.cash == 'lbes')]
p[['book', 'end_nav', 'cagr', 'max_dd', 'vol', 'ulcer', 'calmar', 'sessions', 'trades']].to_csv('t06_as_published_to_2026-10-22.csv', index=False)
A = S[S.window == 'full'].groupby('series', sort=False)[['cagr', 'max_dd', 'vol', 'ulcer', 'calmar', 'end_nav']].mean().reset_index()
A.to_csv('combined_stats_mean_of_4_books.csv', index=False)
SHORT = {'parent': 'Parent', 't06': 'T06', 't07': 'T07', 't08': 'T08', 't10': 'T10'}
post = {'title': 'Parent vs T06 / T07 / T08 / T10',
        'sub': 'NAV = 1.000 at 2019-01-02 (SCMO_0007: 2019-01-04). 20.8 bps round-trip cost, LiquidBees (extended LBES) as cash, window to 2026-10-30, price return. Log scale.',
        'notes': "T06 takes its series from T10's \"switch\" run (the identical rule on T06's engine, extended from T06's 2026-10-22 end to 2026-10-30).",
        'windows': [['full', 'Full (2019 →)'], ['live', 'Live (2021-11-01 →, rebased)']],
        'books': books, 'series': [dict(key=k, label=l, short=SHORT[k]) for l, t, r, k in SER], 'dates': list(wide.index.astype(str)),
        'nav': {b: {k: [None if pd.isna(v) else round(float(v), 5) for v in chart[b][k].reindex(wide.index)] for l, t, r, k in SER} for b in books},
        'stats': json.loads(S[cols].to_json(orient='records')), 'mean': json.loads(A.to_json(orient='records'))}

# ---- before 2019: T09 (three-index switch, tested against random timing) and the descriptive extras, 20.8 bps ----
X = f'{T}/T09/extra'
PRE = [  # key, label, short, group, shown by default
    ('threeindex_timed', 'T09 3-index switch, MAUc1-timed sleeve (80/20 or 20/80)', '3-index timed', 'rule'),
    ('threeindex_fixed50', 'T09 3-index switch, 50/50 GOLDBEES+LiquidBees', '3-index 50/50', 'rule'),
    ('sc100_timed', 'Smallcap 100 switch, MAUc1-timed sleeve', 'SC100 timed', 'rule'),
    ('sc100_fixed50', 'Smallcap 100 switch, 50/50 sleeve', 'SC100 50/50', 'rule'),
    ('index_rule_timed', 'Per-index rule, MAUc1-timed sleeve', 'Per-index timed', 'rule'),
    ('index_rule_fixed50', 'Per-index rule, 50/50 sleeve', 'Per-index 50/50', 'rule'),
    ('hold_proxy', 'Hold the proxy portfolio (always invested)', 'Hold proxy', 'reference'),
    ('constant_mix', 'Constant mix at the rule\'s average share, 50/50 non-proxy', 'Const mix', 'reference'),
    ('constant_mix_timed', 'Constant mix, MAUc1-timed non-proxy', 'Const mix timed', 'reference'),
    ('sleeve_only', '50/50 GOLDBEES + LiquidBees only', 'Sleeve 50/50', 'reference'),
    ('sleeve_only_timed', 'MAUc1-timed GOLDBEES + LiquidBees only', 'Sleeve timed', 'reference'),
    ('nifty100_alone', 'Nifty 100 alone', 'Nifty100', 'reference'),
    ('midcap100_alone', 'Midcap 100 alone', 'Midcap100', 'reference'),
    ('smallcap100_alone', 'Smallcap 100 alone', 'SC100 alone', 'reference')]
SHOW = {'threeindex_timed', 'threeindex_fixed50', 'sc100_timed', 'index_rule_timed', 'hold_proxy'}  # the others are one click away in the legend
pn = pd.read_csv(f'{X}/combined_daily_nav_20.8bps.csv').set_index('date')
ps = pd.read_csv(f'{X}/combined_stats.csv')
prows = []; pchart = {}; pchk = []
for b in books:
    pchart[b] = {}
    for key, label, short, grp in PRE:
        d = pn[pn.book == b][key]
        pchart[b][key] = d
        s_ = ps[(ps.book == b) & (ps.run == key) & (ps.cost_bps == 20.8)].iloc[0]
        m = metrics(d)
        pchk.append((abs(s_.end_nav - d.iloc[-1]), abs(s_.cagr - m['cagr']), abs(s_.max_dd - m['max_dd'])))
        m.update(book=b, series=label, key=key, window='full', start=d.index[0], end=d.index[-1], trades=s_.trades, invested_weeks=None)
        prows.append(m)
PS = pd.DataFrame(prows)
PS[cols].to_csv('pre2019_stats.csv', index=False)
pwide = pd.concat({b: pd.DataFrame(pchart[b]) for b in books}, axis=1)
pwide.columns = [f'{a}__{k}' for a, k in pwide.columns]
pwide.to_csv('pre2019_daily_nav.csv')
print('pre-2019 cross-check vs T09/extra/combined_stats.csv, max abs diff: end_nav %.2e cagr %.2e max_dd %.2e' % tuple(max(c[i] for c in pchk) for i in range(3)))
PA = PS.groupby('series', sort=False)[['cagr', 'max_dd', 'vol', 'ulcer', 'calmar', 'end_nav']].mean().reset_index()
PA.to_csv('pre2019_stats_mean_of_4_books.csv', index=False)
pre = {'title': 'Proxy portfolio, 2011-11-25 → 2019-01-02: T09 and the extra rules',
       'sub': 'NAV = 1.000 at 2011-11-25. 20.8 bps round-trip cost, LiquidBees (LBES) as cash, window to 2019-01-02, price return. Log scale. The legend shows the six rules and holding the proxy; the other references (dashed) are one click away.',
       'notes': "Before 2019 the parents' holdings do not exist, so each book is a proxy: Nifty 100, Midcap 100 and Smallcap 100 at that parent's own average band mix (for example SCMO_0003: 9.6% / 19.7% / 70.7%), reset on entry and at the first session of each quarter while held. GOLDBEES before 2014-07-01 is the MAUc1-based proxy. Only the three-index switch (T09) was tested against random timing (all six criteria failed); the Smallcap 100 and per-index rules and every reference are descriptive. The Smallcap 100 rule holds the whole proxy while Smallcap 100 is BUY; the per-index rule holds each index at the book's weight while its own signal is BUY. A sleeve is the GOLDBEES + LiquidBees part: 50/50, or 80/20 or 20/80 by the weekly MAUc1 signal. Constant mix: the rule's average equity share (46% for the three-index switch, books differ slightly), rebalanced at each weekly decision.",
       'windows': [['full', 'Full (2011-11-25 →)']],
       'books': books, 'series': [dict(key=k, label=l, short=s, ref=(g == 'reference'), on=(k in SHOW)) for k, l, s, g in PRE], 'dates': list(pwide.index.astype(str)),
       'nav': {b: {k: [None if pd.isna(v) else round(float(v), 5) for v in pchart[b][k]] for k, l, s, g in PRE} for b in books},
       'stats': json.loads(PS[cols].to_json(orient='records')), 'mean': json.loads(PA.to_json(orient='records'))}

data = {'post': post, 'pre': pre}
open('index.html', 'w', encoding='utf-8').write(open('template.html', encoding='utf-8').read().replace('__DATA__', json.dumps(data)))
pd.set_option('display.width', 250)
f = S[S.window == 'full']
print(f[['book', 'series', 'cagr', 'max_dd', 'vol', 'calmar', 'end_nav', 'trades']].round(4).to_string())
print(A.round(4).to_string())
print(PA.round(4).to_string())
