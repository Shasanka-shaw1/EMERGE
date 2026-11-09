"""EMERGE - frontend-only demo of an uncertainty-aware emergency route & ETA system.

UI follows the "Emergency Route Intelligence" Figma Make design. Everything is simulated:
no models, no routing, no backend. Routes are generated deterministically from the chosen
start/hospital so every combination demos reliably.
"""
import datetime as dt
import math
import random

import folium
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="EMERGE · Emergency Route Intelligence", page_icon="🚑", layout="wide",
                   initial_sidebar_state="expanded")

# ----------------------------------------------------------------------------- data
STARTS = {"gps": ("Esplanade, Dharmatala", (22.5646, 88.3510))}
MANUAL_DEFAULT = (22.5420, 88.3650)  # Park Circus
HOSPITALS = {
    "SSKM Hospital (IPGMER)": dict(pos=(22.5385, 88.3436), area="Bhowanipore", beds=7, phone="033 2204 1101"),
    "AMRI Hospital, Dhakuria": dict(pos=(22.5106, 88.3664), area="Dhakuria", beds=4, phone="033 6606 3800"),
    "Apollo Gleneagles Hospital": dict(pos=(22.5740, 88.4018), area="Canal Circular Road", beds=9, phone="033 2320 3040"),
    "CMRI Hospital, Alipore": dict(pos=(22.5326, 88.3320), area="Alipore", beds=5, phone="033 4038 4038"),
    "Medica Superspecialty Hospital": dict(pos=(22.4963, 88.3968), area="Mukundapur", beds=6, phone="033 6652 0000"),
}
N, TRIG, INC, SEG, REJ, M = 100, 30, 50, (44, 56), 72, 80   # path sizes / simulation trigger indices
STEP, TICK, HOLD_INC, HOLD_RR = 2, 0.8, 6, 7                # points per tick, seconds per tick, pause ticks
BLUE, GREEN, RED, AMBER, GREY = "#2563eb", "#16a873", "#ef4444", "#e49b4f", "#b6c2cf"
PAST_TRIPS = [
    dict(date="18 Oct, 09:14", hospital="SSKM Hospital (IPGMER)", route="Via AJC Bose Road", dist="4.9 km", time="13 min",
         est="12–16 min", ok=True),
    dict(date="03 Oct, 16:50", hospital="AMRI Hospital, Dhakuria", route="Via Gariahat Road", dist="6.2 km", time="18 min",
         est="14–17 min", ok=False),
]

# ----------------------------------------------------------------------------- geometry
KM_LAT, KM_LON = 111.2, 102.7  # km per degree near Kolkata


def km(a, b):
    return math.hypot((b[1] - a[1]) * KM_LON, (b[0] - a[0]) * KM_LAT)


def bearing(a, b):
    return math.degrees(math.atan2((b[1] - a[1]) * KM_LON, (b[0] - a[0]) * KM_LAT)) % 360


def resample(pts, n):
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + km(a, b))
    out, j = [], 0
    for k in range(n):
        t = cum[-1] * k / (n - 1)
        while j < len(pts) - 2 and cum[j + 1] < t:
            j += 1
        f = (t - cum[j]) / ((cum[j + 1] - cum[j]) or 1)
        out.append((pts[j][0] + (pts[j + 1][0] - pts[j][0]) * f, pts[j][1] + (pts[j + 1][1] - pts[j][1]) * f))
    return out


def path_info(path):
    cum = [0.0]
    for a, b in zip(path, path[1:]):
        cum.append(cum[-1] + km(a, b))
    brg = [bearing(path[i], path[min(i + 2, len(path) - 1)]) for i in range(len(path))]
    return dict(path=path, cum=cum, brg=brg)


def make_routes(s, h):
    dl, dn = h[0] - s[0], h[1] - s[1]
    fast = [s, (s[0] + .4 * dl, s[1]), (s[0] + .4 * dl, s[1] + .55 * dn), (s[0] + .85 * dl, s[1] + .55 * dn),
            (s[0] + .85 * dl, s[1] + dn), h]
    chord = math.hypot(dn * KM_LON, dl * KM_LAT) or 1
    bl, bn = -dn * KM_LON / chord * .2 * chord / KM_LAT, dl * KM_LAT / chord * .2 * chord / KM_LON  # perpendicular bulge
    rel = [s, (s[0], s[1] + .3 * dn), (s[0] + .35 * dl + bl, s[1] + .3 * dn + bn),
           (s[0] + .35 * dl + bl, s[1] + .8 * dn + bn), (s[0] + dl, s[1] + .8 * dn), h]
    return {"fast": path_info(resample(fast, N)), "rel": path_info(resample(rel, N))}


def make_alt(path):
    """Detour from the position where the incident is announced that rejoins the route after it."""
    inc = path[SEG[0]:SEG[1] + 1]
    a, b = path[TRIG], path[REJ]
    ch = math.hypot((b[1] - a[1]) * KM_LON, (b[0] - a[0]) * KM_LAT) or 1
    pl, pn = -(b[1] - a[1]) * KM_LON / ch / KM_LAT, (b[0] - a[0]) * KM_LAT / ch / KM_LON  # unit perpendicular (deg/km)
    best = None
    for sign in (1, -1):
        for off in (.5, .7, .9, 1.2, 1.6):
            o = (sign * off * pl, sign * off * pn)
            alt = resample([a, (a[0] + o[0], a[1] + o[1]), (b[0] + o[0], b[1] + o[1]), b] + path[REJ + 1:], M)
            clear = min(km(p, q) for p in alt[2:] for q in inc)
            if clear >= .35:
                return path_info(alt)
            best = best or path_info(alt)
    return best


def instruction(info, idx, dest):
    brg, cum = info["brg"], info["cum"]
    rem = cum[-1] - cum[idx]
    if rem < .35:
        return "hospital", "Continue towards the hospital", dest
    for j in range(idx + 1, len(brg)):
        d = (brg[j] - brg[idx] + 540) % 360 - 180
        if abs(d) > 35:
            dist = (cum[j] - cum[idx]) * 1000
            if dist < 700:
                return ("left" if d < 0 else "right"), f"Turn {'left' if d < 0 else 'right'}", \
                    f"in {int(round(dist / 10) * 10)} m · then {rem - dist / 1000:.1f} km to go"
            break
    return "straight", "Continue straight", f"for {rem:.1f} km"


# ----------------------------------------------------------------------------- simulated ETA model
def eta_for(kind, exp_min, wide):
    lo_k, hi_k = (.18, .22) if kind == "fast" else (.10, .10)
    lo, hi = round(exp_min * (1 - lo_k * wide)), round(exp_min * (1 + hi_k * wide))
    score = round(100 * (1 - (hi - lo) / (2 * exp_min)))
    return dict(exp=round(exp_min, 1), lo=lo, hi=hi, score=score)


def route_etas(routes, wide):
    f = routes["fast"]["cum"][-1] / 18 * 60  # ~18 km/h average city speed (illustrative)
    return {"fast": eta_for("fast", f, wide), "rel": eta_for("rel", f * 1.04, wide)}


def rng(lo, hi):
    return f"{lo}–{hi} min"


def hosp_sorted(frm):
    return sorted(HOSPITALS, key=lambda n: km(frm, HOSPITALS[n]["pos"]))


def quick_eta(frm, h):
    d = km(frm, h["pos"]) * 1.35
    e = d / 20 * 60
    return d, round(e), round(e * .82), round(e * 1.22)


def clock(minutes):
    return (dt.datetime.now() + dt.timedelta(minutes=minutes)).strftime("%H:%M")


# ----------------------------------------------------------------------------- state
S = st.session_state
for k, v in dict(screen="overview", phase="idle", route="rel", hosp=None, hosp_manual=False, manual=MANUAL_DEFAULT,
                 manual_last=None, idx=0, hold=0, nav=None, book=None, plan=None, history=[]).items():
    S.setdefault(k, v)


def goto(screen):
    S.screen, S.phase, S.idx, S.hold = screen, "idle", 0, 0
    if screen != "arrival":
        S.book = None
        S.nav = None


def start_pos():
    manual = S.get("loc_mode", "gps").startswith("Choose") or S.get("s_gps")
    return (("Selected on map", S.manual) if manual else STARTS["gps"]), manual


def begin_navigation(routes, etas, hosp, wide):
    if (S.book or {}).get("stage") != "started":
        return  # no navigation before OTP verification
    kind = S.route
    info = routes[kind]
    S.nav = dict(kind=kind, info=info, alt=make_alt(info["path"]), eta=etas[kind], etas=etas, hosp=hosp, wide=wide,
                 snap=None, started=dt.datetime.now())
    S.screen, S.phase, S.idx, S.hold = "navigation", "navigating_initial", 0, 0


# ----------------------------------------------------------------------------- styling
CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
html,body,.stApp,button,input,select,textarea{font-family:'DM Sans',system-ui,-apple-system,sans-serif}
.stApp{background:#f5f7f9;color:#0f172a}
h1,h2,h3,.disp{font-family:'Manrope','DM Sans',sans-serif}
#MainMenu,footer,[data-testid="stAppDeployButton"],[data-testid="stMainMenu"]{display:none!important}
header[data-testid="stHeader"]{background:transparent;height:0}
.block-container{padding:0 2.2rem 3rem;max-width:1500px}
section[data-testid="stSidebar"]{background:#fff;border-right:1px solid #e2e8f0;width:260px!important;min-width:260px!important}
section[data-testid="stSidebar"]>div{padding-top:0}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"]{display:none}
.logo{display:flex;align-items:center;gap:12px;margin:8px 0 28px}
.mark{width:40px;height:40px;border-radius:12px;background:#2563eb;color:#fff;font:700 20px Manrope;display:grid;place-items:center;box-shadow:0 8px 18px rgba(30,64,175,.22)}
.word{font:700 18px Manrope;letter-spacing:.12em;color:#020617}
.wtag{font-size:9px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:#94a3b8}
.eyebrow{font-size:10px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:#94a3b8;margin:0}
.sbhead{font-size:10px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:#94a3b8;margin:0 0 6px 10px}
[class*="st-key-nav_"] button{justify-content:flex-start;border:none;background:transparent;color:#64748b;font-size:14px;font-weight:600;padding:.7rem .75rem;border-radius:12px;box-shadow:none;width:100%}
[class*="st-key-nav_"] button:hover{background:#f8fafc;color:#0f172a}
.livecard{background:#020617;color:#fff;border-radius:16px;padding:16px;margin-top:8px}
.livecard b{font-size:12px;display:flex;align-items:center;gap:8px}.livecard span{display:block;font-size:11px;color:#94a3b8;margin-top:10px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#34d399}
.user{display:flex;align-items:center;gap:12px;margin-top:14px}
.avatar{width:36px;height:36px;border-radius:50%;background:#dbeafe;color:#1d4ed8;font:700 12px 'DM Sans';display:grid;place-items:center}
.topbar{display:flex;justify-content:space-between;align-items:center;padding:22px 0 18px}
.topbar h1{margin:0;font-size:1.65rem;font-weight:600;letter-spacing:-.01em;color:#020617;padding:0}
.topbar p{margin:4px 0 0;font-size:12px;color:#94a3b8}
.sys{display:inline-flex;align-items:center;gap:8px;border:1px solid #e2e8f0;background:#fff;border-radius:999px;padding:7px 14px;font-size:12px;font-weight:500;color:#475569}
.sys i{width:8px;height:8px;border-radius:50%;background:#10b981}
.bell{display:inline-grid;place-items:center;width:40px;height:40px;border:1px solid #e2e8f0;background:#fff;border-radius:12px;margin-left:8px;position:relative}
.bell:after{content:'';position:absolute;top:10px;right:11px;width:7px;height:7px;border-radius:50%;background:#ef4444;box-shadow:0 0 0 2px #fff}
[class*="st-key-panel"]{background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:20px 22px;box-shadow:0 8px 30px rgba(15,23,42,.035)}
.st-key-hero{background:#020617;color:#fff;border-radius:28px;padding:34px 36px;position:relative;overflow:hidden;box-shadow:0 18px 40px rgba(15,23,42,.14)}
.st-key-hero:before{content:'';position:absolute;right:-70px;top:-100px;width:300px;height:300px;border-radius:50%;background:rgba(37,99,235,.32);filter:blur(60px)}
.st-key-hero h2{font-size:2.5rem;font-weight:600;line-height:1.15;max-width:640px;margin:0;color:#fff;padding:0}
.herotag{display:inline-flex;align-items:center;gap:8px;border-radius:999px;background:rgba(255,255,255,.1);color:#dbeafe;font-size:11px;font-weight:600;padding:6px 12px;margin-bottom:18px}
.herotxt{max-width:520px;margin:14px 0 6px;font-size:14px;line-height:1.7;color:#cbd5e1}
.st-key-cta .stButton>button{background:#ef4444;color:#fff;border:none;border-radius:12px;padding:.85rem 1.4rem;font-size:13px;font-weight:700;box-shadow:0 10px 22px rgba(239,68,68,.3);margin-top:12px}
.st-key-cta .stButton>button:hover{background:#f87171;color:#fff}
.stButton>button{border-radius:12px;font-weight:700;font-size:13px;border:1px solid #e2e8f0;padding:.6rem 1rem;color:#334155;background:#fff}
.stButton>button:hover{border-color:#cbd5e1;background:#f8fafc;color:#0f172a}
.stButton>button[kind="primary"]{background:#2563eb;border:none;color:#fff;box-shadow:0 8px 18px rgba(30,64,175,.18)}
.stButton>button[kind="primary"]:hover{background:#1d4ed8;color:#fff}
.stButton>button:focus-visible{outline:3px solid rgba(37,99,235,.25)}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:16px 18px;margin-bottom:10px}
.card.sel{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,.12)}
.card.selg{border-color:#10b981;box-shadow:0 0 0 3px rgba(16,185,129,.12)}
.row{display:flex;align-items:center;gap:12px}.sp{justify-content:space-between}
.ico{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;flex:none}
.ico.b{background:#eff6ff;color:#2563eb}.ico.g{background:#ecfdf5;color:#059669}.ico.s{background:#f1f5f9;color:#64748b}.ico.r{background:#fef2f2;color:#ef4444}.ico.bs{background:#2563eb;color:#fff}
.ttl{font:600 15px Manrope;color:#0f172a}.ttl.xl{font-size:20px}.mut{font-size:11px;color:#94a3b8;margin-top:3px}
.pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 10px;font-size:10px;font-weight:700}
.pill i{width:6px;height:6px;border-radius:50%}
.pill.green{background:#ecfdf5;color:#047857}.pill.green i{background:#10b981}
.pill.blue{background:#eff6ff;color:#1d4ed8}.pill.blue i{background:#3b82f6}
.pill.amber{background:#fffbeb;color:#b45309}.pill.amber i{background:#f59e0b}
.pill.red{background:#fef2f2;color:#b91c1c}.pill.red i{background:#ef4444}
.mets{display:grid;background:#f8fafc;border-radius:12px;padding:12px 0;text-align:center}
.mets>div{border-left:1px solid #f1f5f9}.mets>div:first-child{border-left:none}
.mets b{font-size:14px;color:#0f172a;display:block}.mets b.g{color:#059669}.mets small{font-size:10px;color:#94a3b8;display:block;margin-top:4px}
.foot{border-top:1px solid #f1f5f9;margin-top:14px;padding-top:12px;font-size:10px;color:#64748b}
.alert{border-radius:16px;padding:16px 18px;margin-bottom:12px;border:1px solid;animation:slide .4s ease}
.alert h3{margin:6px 0 4px;font-size:17px;font-weight:600}.alert p{margin:2px 0;font-size:13px;line-height:1.6}
.al-red{background:#fef2f2;border-color:#fecaca;color:#7f1d1d}.al-amber{background:#fffbeb;border-color:#fde68a;color:#78350f}
.al-green{background:#ecfdf5;border-color:#a7f3d0;color:#064e3b}.al-blue{background:#eff6ff;border-color:#bfdbfe;color:#1e3a8a}
@keyframes slide{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
@keyframes blink{50%{opacity:.3}}
.dots span{animation:blink 1s infinite;font-weight:800}.dots span:nth-child(2){animation-delay:.2s}.dots span:nth-child(3){animation-delay:.4s}
.bar{position:relative;height:8px;background:#e2e8f0;border-radius:8px;margin:10px 0 4px}.bar i{position:absolute;top:0;height:8px;border-radius:8px}
.cap{display:flex;justify-content:space-between;font-size:10px;color:#94a3b8}
.prog{height:6px;border-radius:6px;background:#f1f5f9;overflow:hidden}.prog i{display:block;height:100%;border-radius:6px;background:#2563eb}
.stat{font:700 24px Manrope;color:#0f172a}.statl{font-size:12px;font-weight:600;color:#475569;margin-top:2px}.statt{font-size:10px;color:#059669;margin-top:10px}
.sum{text-align:center}.sum b{font:700 22px Manrope;display:block}.sum small{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#94a3b8}
.fc{border-radius:16px;border:1px solid #e2e8f0;background:#fff;padding:18px}.fc.best{border-color:#6ee7b7;background:rgba(236,253,245,.6)}
.fc b.d{font:700 24px Manrope;display:block;margin-top:14px}
.tl{border-left:2px solid #e2e8f0;margin-left:8px;padding-left:18px}.tl div{margin-bottom:12px;position:relative;font-size:13px}
.tl div:before{content:'';position:absolute;left:-25px;top:4px;width:10px;height:10px;border-radius:50%;background:#2563eb;border:2px solid #fff}
.tl .r:before{background:#ef4444}.tl .g:before{background:#10b981}.tl small{color:#94a3b8;font-size:11px}
.done{width:80px;height:80px;border-radius:50%;background:#d1fae5;color:#059669;display:grid;place-items:center;margin:8px auto 0;box-shadow:0 0 0 8px #ecfdf5}
.hist{display:grid;grid-template-columns:1.5fr 1fr .8fr .8fr;gap:12px;align-items:center;padding:16px 4px;border-top:1px solid #f1f5f9}
.legend-lite{display:flex;gap:16px;font-size:10px;font-weight:700;color:#64748b;margin:6px 0 0}
.legend-lite i{display:inline-block;width:20px;height:4px;border-radius:3px;margin-right:6px;vertical-align:middle}
/* navigation screen: floating cards over the map */
.st-key-navwrap{position:relative;height:740px!important;max-height:740px;border-radius:24px;overflow:hidden;box-shadow:0 8px 30px rgba(15,23,42,.1)}
.st-key-nav_instr{position:absolute;top:16px;left:16px;width:min(370px,calc(100% - 90px));z-index:50;gap:.6rem}
.st-key-nav_close{position:absolute;top:16px;right:16px;z-index:50;width:auto}
.st-key-nav_close button{width:44px;height:44px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,.15)}
.st-key-nav_bottom{position:absolute;bottom:16px;left:50%;transform:translateX(-50%);width:min(740px,calc(100% - 32px));z-index:50}
.st-key-nav_alert{position:absolute;top:76px;right:16px;width:min(430px,calc(100% - 32px));z-index:60}
.float{background:#fff;border-radius:22px;padding:18px 20px;box-shadow:0 20px 40px rgba(15,23,42,.22)}
.float.sm{border-radius:16px;padding:14px;box-shadow:0 10px 24px rgba(15,23,42,.18)}
.instr{display:flex;align-items:center;gap:14px}.instr .ar{width:48px;height:48px;border-radius:12px;background:#2563eb;color:#fff;display:grid;place-items:center;font-size:26px}
.instr b{font:700 19px 'DM Sans';display:block}.instr small{font-size:12px;color:#94a3b8}
.etabig{font:700 32px Manrope;color:#2563eb;line-height:1}.etabig small{font-size:14px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}.two>div{border-radius:12px;padding:10px 12px}
.two small{display:block;font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.two b{font-size:18px}
</style>"""
MAP_CSS = """<style>
.leaflet-tile-pane{filter:grayscale(.6) brightness(1.05) contrast(.92)}
.leaflet-container{background:#edf1f3}
.nav-icon,.pin-icon{background:none!important;border:none!important}
.pulse{transform-origin:22px 22px;animation:pl 1.6s ease-out infinite}
@keyframes pl{0%{transform:scale(.55);opacity:.9}100%{transform:scale(1.3);opacity:0}}
.hpin{width:40px;height:40px;border-radius:50%;background:#fff;display:grid;place-items:center;box-shadow:0 6px 14px rgba(0,0,0,.25)}
.hpin i{width:28px;height:28px;border-radius:50%;background:#ef4444;display:grid;place-items:center}
.hpin.dark i{background:#1e293b;width:30px;height:30px}.hpin.dark{width:34px;height:34px}
.hlab{margin-top:3px;background:rgba(255,255,255,.96);border-radius:4px;padding:2px 7px;font:700 9px 'DM Sans',sans-serif;box-shadow:0 2px 6px rgba(0,0,0,.18);white-space:nowrap;text-align:center}
.me{width:16px;height:16px;border-radius:50%;background:#2563eb;border:3px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.35)}
.inc{width:46px;height:46px;border-radius:50%;background:#ef4444;display:flex;align-items:center;justify-content:center;font-size:22px;border:3px solid #fff;animation:ring 1.4s infinite}
@keyframes ring{70%{box-shadow:0 0 0 20px rgba(239,68,68,0)}100%{box-shadow:0 0 0 0 rgba(239,68,68,0)}}
.otp{font:800 44px Manrope;letter-spacing:.5em;text-indent:.5em;text-align:center;background:#eff6ff;color:#1d4ed8;border:2px dashed #93c5fd;border-radius:16px;padding:16px 0;margin:12px 0}
.steps{display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 16px}
.legend{position:fixed;z-index:9999;background:rgba(255,255,255,.96);padding:8px 12px;border-radius:12px;font:700 11px 'DM Sans',sans-serif;box-shadow:0 2px 10px rgba(0,0,0,.18);line-height:1.8}
.legend b{display:inline-block;width:22px;height:4px;border-radius:3px;margin-right:6px;vertical-align:middle}
</style>"""


def legend(pos):
    return (f'<div class="legend" style="{pos}"><b style="background:{BLUE}"></b>Fastest<br><b style="background:{GREEN}"></b>Reliable / new route<br>'
            f'<b style="background:{AMBER}"></b>Original route<br><b style="background:{RED}"></b>Busy road</div>')


st.markdown(CSS, unsafe_allow_html=True)

HOSP_SVG = ('<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" '
            'stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M9 8h6M12 5v6M8 21v-5h8v5"/></svg>')
SHIELD_T = ('<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" '
          'stroke-linejoin="round"><path d="M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10Z"/><path d="m9 12 2 2 4-5"/></svg>')
SHIELD = SHIELD_T.format(s=15)
CLOCK = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
         '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>')
ARROWS = {"left": "⬅", "right": "➡", "straight": "⬆", "hospital": HOSP_SVG.format(s=26), "stop": "⚠", "calc": "⟳"}


def hsvg(s=20):
    return HOSP_SVG.format(s=s)


def pill(txt, c="green"):
    return f'<span class="pill {c}"><i></i>{txt}</span>'


def mets(items):
    return (f'<div class="mets" style="grid-template-columns:repeat({len(items)},1fr)">' +
            "".join(f'<div><b class="{"g" if g else ""}">{v}</b><small>{l}</small></div>' for v, l, g in items) + '</div>')


def eta_bar(lo, hi, scale, color):
    return (f'<div class="bar"><i style="left:{lo / scale * 100:.0f}%;width:{max(hi - lo, .5) / scale * 100:.0f}%;background:{color}"></i></div>'
            f'<div class="cap"><span>best case {lo} min</span><span>worst case {hi} min</span></div>')


# ----------------------------------------------------------------------------- map helpers
def hospital_pin(pos, tip, selected=True, label=None):
    html = (f'<div style="display:flex;flex-direction:column;align-items:center"><div class="hpin {"" if selected else "dark"}">'
            f'<i style="color:#fff">{hsvg(15)}</i></div>{f"<div class=hlab>{label}</div>" if label else ""}</div>')
    return folium.Marker(pos, tooltip=tip, icon=folium.DivIcon(html=html, icon_size=(120, 60), icon_anchor=(60, 20), class_name="pin-icon"))


def me_pin(pos):
    return folium.Marker(pos, tooltip="You", icon=folium.DivIcon(html='<div class="me"></div>', icon_size=(16, 16), icon_anchor=(8, 8),
                                                                 class_name="pin-icon"))


def arrow(pos, b):
    svg = (f'<div style="transform:rotate({b:.0f}deg)"><svg width="44" height="44" viewBox="0 0 44 44">'
           '<circle class="pulse" cx="22" cy="22" r="20" fill="rgba(37,99,235,.35)"/>'
           '<circle cx="22" cy="22" r="14" fill="rgba(37,99,235,.18)"/>'
           '<path d="M22 6 L33 34 L22 28 L11 34 Z" fill="#2563eb" stroke="#fff" stroke-width="2.5" stroke-linejoin="round"/></svg></div>')
    return folium.Marker(pos, icon=folium.DivIcon(html=svg, icon_size=(44, 44), icon_anchor=(22, 22), class_name="nav-icon"))


def incident_pin(pos):
    return folium.Marker(pos, tooltip="Road looks too busy", icon=folium.DivIcon(html='<div class="inc">💥</div>', icon_size=(46, 46),
                                                                           icon_anchor=(23, 23), class_name="pin-icon"))


def line(path, color, w=7, op=.95, dash=None):
    return folium.PolyLine(path, color=color, weight=w, opacity=op, dash_array=dash, line_cap="round")


def zoom_for(a, b):
    span = max(abs(a[0] - b[0]) * 1.1, abs(a[1] - b[1]) * .95)
    return 15 if span < .008 else 14 if span < .02 else 13 if span < .045 else 12


def draw_map(key, items, center, zoom, height=560, click=False, leg="top:12px;right:12px", zoomctl=True):
    m = folium.Map(location=[22.55, 88.37], zoom_start=13, tiles="OpenStreetMap", control_scale=True, zoom_control=zoomctl)
    m.get_root().header.add_child(folium.Element(MAP_CSS))
    if leg:
        m.get_root().html.add_child(folium.Element(legend(leg)))
    fg = folium.FeatureGroup(name="live")
    for it in items:
        it.add_to(fg)
    return st_folium(m, feature_group_to_add=fg, center=center, zoom=zoom, key=key, height=height, use_container_width=True,
                     returned_objects=["last_clicked"] if click else [])


# ----------------------------------------------------------------------------- shell: sidebar + header
NAV = [("overview", "Overview", ":material/home:"), ("hospitals", "Find a hospital", ":material/map:"),
       ("planner", "Trip planner", ":material/calendar_month:"), ("history", "Trip history", ":material/history:")]
TITLES = {"overview": f"Good {'morning' if dt.datetime.now().hour < 12 else 'afternoon' if dt.datetime.now().hour < 17 else 'evening'}, Alex",
          "hospitals": "Choose a hospital", "booking": "Book an ambulance", "compare": "Compare routes", "navigation": "Live navigation", "arrival": "Arrival",
          "planner": "Plan a non-urgent trip", "history": "Trip history"}
active = "hospitals" if S.screen in ("hospitals", "booking", "compare", "navigation", "arrival") else S.screen
with st.sidebar:
    st.markdown('<div class="logo"><div class="mark">E</div><div><div class="word">EMERGE</div>'
                '<div class="wtag">Emergency Route Intelligence</div></div></div><p class="sbhead">Workspace</p>', unsafe_allow_html=True)
    st.markdown(f'<style>.st-key-nav_{active} button{{background:#eff6ff!important;color:#1d4ed8!important}}</style>', unsafe_allow_html=True)
    for sid, label, icon in NAV:
        st.button(label, icon=icon, key=f"nav_{sid}", on_click=goto, args=(sid,))
    with st.expander("Demo scenarios"):
        st.checkbox("GPS unavailable", key="s_gps")
        st.checkbox("Nearest hospital unreachable", key="s_unreach")
        st.checkbox("Traffic / weather data missing", key="s_missing")
    st.markdown('<div class="livecard"><b><i class="dot"></i> Live traffic connected</b><span>Predictions updated 34 seconds ago</span></div>'
                '<div class="user"><div class="avatar">AM</div><div><div style="font-size:14px;font-weight:600">Alex Morgan</div>'
                '<div style="font-size:11px;color:#94a3b8">Personal account</div></div></div>', unsafe_allow_html=True)

wide = 1.5 if S.get("s_missing") else 1.0
(start_label, start), manual_mode = start_pos()
if not S.hosp_manual or S.hosp not in HOSPITALS:
    S.hosp = hosp_sorted(start)[0]
hosp = S.hosp
hpos = HOSPITALS[hosp]["pos"]
routes = make_routes(start, hpos)
etas = route_etas(routes, wide)
unreachable = bool(S.get("s_unreach")) and hosp == hosp_sorted(start)[0]  # scenario: nearest hospital is cut off

if S.screen != "navigation":
    st.markdown(f'<div class="topbar"><div><h1>{TITLES[S.screen]}</h1><p>{dt.datetime.now().strftime("%A, %d %B · %H:%M")}</p></div>'
                f'<div style="display:flex;align-items:center"><span class="sys"><i></i> Systems normal</span><span class="bell">'
                f'<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                f'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg></span></div></div>', unsafe_allow_html=True)
else:
    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)


# ----------------------------------------------------------------------------- overview
def overview():
    with st.container(key="hero"):
        st.markdown('<div class="herotag"><i class="dot"></i> Your location is ready</div>'
                    '<h2>Fast, reliable routes when every minute matters.</h2>'
                    '<p class="herotxt">Live traffic intelligence and uncertainty-aware predictions help you reach the right care with confidence.</p>',
                    unsafe_allow_html=True)
        with st.container(key="cta"):
            if st.button("Start emergency navigation  →", icon=":material/route:"):
                goto("hospitals")
                st.rerun()
    st.markdown('<div style="height:18px"></div>', unsafe_allow_html=True)
    a, b = st.columns([1.45, .9], gap="medium")
    with a:
        with st.container(key="panel_pos"):
            st.markdown(f'<p class="eyebrow">Current position</p><div class="ttl xl" style="margin-top:4px">{start_label}</div>'
                        f'<div class="mut" style="margin-bottom:14px">Kolkata · Location accuracy 8 m</div>', unsafe_allow_html=True)
            items = [me_pin(start)] + [hospital_pin(h["pos"], n, n == hosp, n.split(",")[0].split(" (")[0] if n == hosp else None)
                                       for n, h in HOSPITALS.items()]
            draw_map("map_ov", items, (22.54, 88.385), 12, 330, leg=None)
            st.markdown(f'<div class="row sp" style="margin-top:12px"><div class="row" style="font-size:12px;font-weight:600;color:#475569">'
                        f'<span style="color:#2563eb">{hsvg(17)}</span> {len(HOSPITALS)} emergency departments nearby</div></div>', unsafe_allow_html=True)
            st.button("View nearby hospitals  →", key="ov_vh", on_click=goto, args=("hospitals",))
    with b:
        d, e, lo, hi = quick_eta(start, HOSPITALS[hosp])
        with st.container(key="panel_near"):
            st.markdown(f'<div class="row sp" style="align-items:flex-start"><div><p class="eyebrow">Nearest hospital</p>'
                        f'<div class="ttl" style="margin-top:8px;font-size:17px">{hosp}</div></div><div class="ico b">{hsvg()}</div></div>'
                        f'<div style="margin-top:16px">{mets([(f"{e} min", "Expected", False), (f"{d:.1f} km", "Distance", False), ("Low", "Traffic", True)])}</div>',
                        unsafe_allow_html=True)
        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
        with st.container(key="panel_plan"):
            st.markdown('<div class="row sp" style="align-items:flex-start"><div><p class="eyebrow">Planning ahead?</p>'
                        '<div class="ttl" style="margin-top:6px;font-size:17px">Schedule a non-urgent trip</div></div>'
                        '<div class="ico g"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
                        '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/></svg></div></div>'
                        '<p style="font-size:13px;line-height:1.7;color:#64748b;margin:14px 0">Find the best departure time using historical travel patterns and confidence ranges.</p>',
                        unsafe_allow_html=True)
            st.button("Open trip planner  →", key="ov_pl", on_click=goto, args=("planner",), width="stretch")


# ----------------------------------------------------------------------------- hospitals
def hospitals():
    left, right = st.columns([4, 7], gap="medium")
    with left:
        with st.container(key="panel_from"):
            st.markdown(f'<p class="eyebrow">From</p><div class="row" style="margin:6px 0 8px"><span style="color:#2563eb">📍</span>'
                        f'<div class="ttl" style="font-size:14px">{start_label}</div></div>', unsafe_allow_html=True)
            st.radio("loc", ["Use GPS (simulated)", "Choose on map"], key="loc_mode", horizontal=True, label_visibility="collapsed")
            if S.get("s_gps"):
                st.markdown('<div class="alert al-amber" style="margin:8px 0 0"><h3 style="margin:0">GPS signal unavailable</h3>'
                            '<p>Tap your starting point on the map to continue.</p></div>', unsafe_allow_html=True)
            elif manual_mode:
                st.caption("Tap anywhere on the map to set your start point.")
        st.markdown(f'<div class="row sp" style="margin:16px 2px 10px"><span style="font-size:12px;font-weight:600;color:#64748b">'
                    f'{len(HOSPITALS)} hospitals nearby</span><span style="font-size:11px;font-weight:700;color:#2563eb">Sort: Fastest</span></div>',
                    unsafe_allow_html=True)
        for i, n in enumerate(hosp_sorted(start)):
            h = HOSPITALS[n]
            d, e, lo, hi = quick_eta(start, h)
            sel = n == hosp
            cut = S.get("s_unreach") and i == 0
            st.markdown(f'<div class="card {"sel" if sel else ""}" style="margin-bottom:6px"><div class="row" style="align-items:flex-start">'
                        f'<div class="ico {"bs" if sel else "s"}">{hsvg(19)}</div><div style="flex:1"><div class="ttl">{n}</div>'
                        f'<div class="mut">{h["area"]}</div></div><div style="text-align:right"><div style="font-weight:700;font-size:14px">{e} min</div>'
                        f'<div class="mut">{d:.1f} km</div></div></div><div class="foot row sp"><span>P10–P90 <b style="color:#334155;margin-left:4px">'
                        f'{lo}–{hi} min</b></span>{pill("Unreachable", "red") if cut else pill("Available" if h["beds"] >= 6 else "Moderate", "green" if h["beds"] >= 6 else "amber")}'
                        f'</div></div>', unsafe_allow_html=True)
            if st.button("✓ Selected" if sel else "Select hospital", key=f"pick_{i}", width="stretch", type="primary" if sel else "secondary"):
                S.hosp, S.hosp_manual = n, True
                st.rerun()
        if unreachable:
            alt = [n for n in hosp_sorted(start) if n != hosp][0]
            st.markdown(f'<div class="alert al-red"><h3>{hosp} is currently unreachable</h3><p>Flooding has blocked all access roads. '
                        f'Nearest reachable hospital: <b>{alt}</b> ({km(start, HOSPITALS[alt]["pos"]) * 1.35:.1f} km).</p></div>', unsafe_allow_html=True)
            if st.button(f"Switch to {alt}", width="stretch"):
                S.hosp, S.hosp_manual = alt, True
                st.rerun()
        elif S.get("s_missing"):
            st.markdown('<div class="alert al-amber"><h3>Live traffic &amp; weather data unavailable</h3>'
                        '<p>Using historical averages. ETA confidence is <b>lower</b> than usual.</p></div>', unsafe_allow_html=True)
        if st.button("Book ambulance  →", type="primary", width="stretch", disabled=unreachable, key="to_compare"):
            S.screen = "booking"
            st.rerun()
    with right:
        items = [me_pin(start)] + [hospital_pin(h["pos"], n, n == hosp, n.split(",")[0].split(" (")[0]) for n, h in HOSPITALS.items()]
        mid = ((start[0] + hpos[0]) / 2, (start[1] + hpos[1]) / 2)
        res = draw_map("map_h", items, mid, min(zoom_for(start, hpos), 13), 720, click=manual_mode, leg=None)
        lc = (res or {}).get("last_clicked")
        if manual_mode and lc and (lc["lat"], lc["lng"]) != S.manual_last:
            S.manual, S.manual_last = (lc["lat"], lc["lng"]), (lc["lat"], lc["lng"])
            st.rerun()


# ----------------------------------------------------------------------------- compare
def range_chart():
    fig = go.Figure()
    for k, name, col in (("fast", "Fastest", BLUE), ("rel", "Most reliable", GREEN)):
        e = etas[k]
        fig.add_trace(go.Bar(y=[name], x=[e["hi"] - e["lo"]], base=[e["lo"]], orientation="h", marker_color=col, opacity=.85, width=.42,
                             hovertemplate=f"{e['lo']}–{e['hi']} min<extra></extra>", showlegend=False))
        fig.add_trace(go.Scatter(y=[name], x=[e["exp"]], mode="markers", marker=dict(symbol="diamond", size=13, color="#fff",
                                 line=dict(color="#0f172a", width=2)), hovertemplate=f"expected {e['exp']} min<extra></extra>", showlegend=False))
    fig.update_layout(height=170, margin=dict(l=0, r=10, t=6, b=34), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(title="minutes · bar = P10–P90 · ◆ = expected", gridcolor="#e2e8f0"), yaxis=dict(autorange="reversed"),
                      font=dict(family="DM Sans", size=11))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def compare():
    st.markdown(f'<div class="row sp" style="margin-bottom:14px"><div><p class="eyebrow">{hosp}</p><div class="ttl xl" style="margin-top:4px">'
                f'Choose the right route</div><div class="mut">Confidence ranges account for traffic uncertainty</div></div>'
                f'{pill("Historical averages" if S.get("s_missing") else "Live traffic", "amber" if S.get("s_missing") else "green")}</div>',
                unsafe_allow_html=True)
    other, chosen = ("fast", "rel") if S.route == "rel" else ("rel", "fast")
    col = {"fast": BLUE, "rel": GREEN}
    items = [line(routes[other]["path"], col[other], 5, .5, "10 8"), line(routes[chosen]["path"], col[chosen], 8),
             me_pin(start), hospital_pin(hpos, hosp)]
    draw_map("map_c", items, ((start[0] + hpos[0]) / 2, (start[1] + hpos[1]) / 2), zoom_for(start, hpos), 380, leg="bottom:24px;left:12px")
    fw = etas["fast"]
    if fw["hi"] - fw["lo"] >= 5:
        st.markdown(f'<div class="alert al-amber" style="margin-top:14px"><b>Wide ETA range on the fastest route</b><p>Arrival could vary by '
                    f'<b>{fw["hi"] - fw["lo"]} minutes</b>. The most reliable route is recommended for emergencies.</p></div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2, gap="medium")
    for c, k, title, desc, badge, bc, ic in ((c1, "fast", "Fastest route", "Lowest expected travel time", "Lowest expected time", "blue", "b"),
                                              (c2, "rel", "Most reliable", "Lowest worst-case (P90) time", "Recommended", "green", "g")):
        e, d = etas[k], routes[k]["cum"][-1]
        sel = S.route == k
        conf = "Low" if S.get("s_missing") else "High" if e["score"] >= 85 else "Moderate"
        with c:
            st.markdown(f'<div class="card {("sel" if k == "fast" else "selg") if sel else ""}" style="margin-top:14px;margin-bottom:6px">'
                        f'<div class="row sp" style="align-items:flex-start"><div class="row"><div class="ico {ic}">'
                        f'{CLOCK if k == "fast" else SHIELD_T.format(s=20)}'
                        f'</div><div><div class="ttl" style="font-size:16px">{title}</div><div class="mut">{desc}</div></div></div>{pill(badge, bc)}</div>'
                        f'<div style="margin-top:16px">{mets([(f"{e["exp"]} min", "Expected", False), (clock(e["exp"]), "Arrival", False), (rng(e["lo"], e["hi"]).replace(" min", ""), "P10–P90", False), (f"{d:.1f} km", "Distance", False)])}</div>'
                        f'{eta_bar(e["lo"], e["hi"], max(fw["hi"], 10) * 1.15, col[k])}'
                        f'<div class="foot">Reliability: <b style="color:#334155">{conf} · {e["score"]}%</b> &nbsp;·&nbsp; worst case <b style="color:#334155">{e["hi"]} min</b></div></div>',
                        unsafe_allow_html=True)
            if st.button("✓ Selected route" if sel else "Select route", key=f"sel_{k}", width="stretch", type="primary" if sel else "secondary"):
                S.route = k
                st.rerun()
    with st.container(key="panel_conf"):
        a, b = st.columns([3, 1], vertical_alignment="center")
        a.markdown(f'<div class="row"><div class="ico b" style="border-radius:50%;width:36px;height:36px">{SHIELD}</div><div>'
                   f'<div style="font-size:12px;font-weight:700">EMERGE confidence estimate</div><div class="mut">The most reliable route is chosen by its worst-case '
                   f'(90th percentile) time. 90% of journeys are expected to fall within the displayed range.</div></div></div>', unsafe_allow_html=True)
        if b.button("Start navigation  →", type="primary", width="stretch", key="go_nav"):
            begin_navigation(routes, etas, hosp, wide)
            st.rerun()
    range_chart()
    st.button("← Back to hospitals", key="back_h", on_click=goto, args=("hospitals",))


# ----------------------------------------------------------------------------- ambulance booking (frontend simulation only)
ARRIVE_S, START_S = 10, 3  # demo seconds: ambulance travel time, "Ride started" pause before route selection


def quote():
    r = random.Random(f"{hosp}{start}")  # stable across reruns
    return dict(type="Advanced Life Support (ALS)", avail=r.randint(2, 5), pickup=r.randint(5, 9), journey=etas["rel"]["exp"],
                cost=round((900 + 60 * routes["rel"]["cum"][-1]) / 10) * 10)


def stepper(i):
    names = ["Booked", "On the way", "Arrived", "Verified"]
    return '<div class="steps">' + "".join(pill(n, "green" if j < i else "blue" if j == i else "amber") for j, n in enumerate(names)) + "</div>"


def ambulance_card(b, status):
    return (f'<div class="card"><div class="row sp" style="align-items:flex-start"><div class="row"><div class="ico b">{hsvg(20)}</div><div>'
            f'<div class="ttl">{b["type"]}</div><div class="mut">Booking ID {b["id"]}</div></div></div>{pill(status)}</div>'
            f'<div style="margin-top:16px">{mets([(b["reg"], "Registration", False), (b["driver"], "Driver", False), (b["phone"], "Contact", False), (f"{b["pickup"]} min", "Est. arrival", True)])}</div></div>')


@st.fragment(run_every=1)
def tracking():
    b = S.book
    el = (dt.datetime.now() - b["t0"]).total_seconds()
    if el >= ARRIVE_S:
        b["stage"] = "otp"
        st.rerun()
    left = max(1, math.ceil(b["pickup"] * (1 - el / ARRIVE_S)))
    st.markdown(f'<div class="card"><div class="row sp"><div class="ttl">Ambulance heading to {start_label}</div><div class="mut">~{left} min away</div></div>'
                f'<div class="prog" style="margin-top:14px"><i style="width:{min(el / ARRIVE_S, 1) * 100:.0f}%"></i></div></div>', unsafe_allow_html=True)


@st.fragment(run_every=1)
def ride_started():
    if (dt.datetime.now() - S.book["t1"]).total_seconds() >= START_S:
        S.screen = "compare"  # hand over to the existing route comparison -> navigation
        st.rerun()
    st.markdown(f'<div style="text-align:center;max-width:560px;margin:0 auto"><div class="done"><svg width="38" height="38" viewBox="0 0 24 24" fill="none" '
                f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 4 4L19 6"/></svg></div>'
                f'<p class="eyebrow" style="color:#059669;margin-top:22px">OTP verified</p><h1 style="font-size:2.2rem;font-weight:600;margin:6px 0;padding:0">Ride started</h1>'
                f'<p style="font-size:14px;color:#64748b">Heading to {hosp}. Opening route selection…</p></div>', unsafe_allow_html=True)


def booking():
    b = S.book
    stage = b["stage"] if b else "details"
    _, mid, _ = st.columns([1, 3, 1])
    with mid:
        st.markdown(stepper({"details": 0, "assigned": 1, "otp": 2, "started": 3}[stage]), unsafe_allow_html=True)
        if stage == "details":
            q = quote()
            code, name = q["type"].split(" (")[1][:-1], q["type"].split(" (")[0]
            st.markdown(f'<div class="card"><div class="row sp" style="align-items:flex-start"><div class="row"><div class="ico bs">{hsvg(19)}</div><div>'
                        f'<p class="eyebrow">Destination</p><div class="ttl">{hosp}</div><div class="mut">{HOSPITALS[hosp]["area"]} · pickup: {start_label}</div></div></div>'
                        f'{pill(f"{q["avail"]} ambulances available")}</div>'
                        f'<div style="margin-top:16px">{mets([(code, name, False), (f"{q["pickup"]} min", "Ambulance arrival", True), (f"{q["journey"]} min", "Journey time", False), (f"₹{q["cost"]:,}", "Booking cost (demo)", False)])}</div>'
                        f'<div class="foot">Illustrative demo data. No payment is taken.</div></div>', unsafe_allow_html=True)
            if st.button("Book Ambulance", type="primary", width="stretch", key="book_now"):
                r = random.Random()
                S.book = dict(stage="assigned", id=f"AMB-{r.randint(100000, 999999)}", otp=f"{r.randint(0, 9999):04d}", t0=dt.datetime.now(), err=False,
                              reg=f"WB {r.randint(10, 99)} {r.choice('ABCDEFGH')}{r.choice('ABCDEFGH')} {r.randint(1000, 9999)}",
                              driver=r.choice(["Ramesh Das", "Sourav Ghosh", "Imran Sheikh", "Anil Mondal"]), phone=f"98{r.randint(30000000, 99999999)}", **q)
                st.rerun()
            st.button("← Back to hospitals", key="back_h2", on_click=goto, args=("hospitals",))
        elif stage == "assigned":
            st.markdown(ambulance_card(b, "Ambulance on the way"), unsafe_allow_html=True)
            tracking()
        elif stage == "otp":
            st.markdown('<div class="alert al-blue"><h3>Ambulance has arrived</h3><p>Share the code below with the driver to start your ride.</p></div>', unsafe_allow_html=True)
            st.markdown(ambulance_card(b, "Arrived"), unsafe_allow_html=True)
            st.markdown(f'<div class="card" style="text-align:center"><p class="eyebrow">Your ride OTP (simulated)</p><div class="otp">{b["otp"]}</div></div>', unsafe_allow_html=True)
            with st.form("otp_form", border=False):
                code = st.text_input("Enter 4-digit OTP", max_chars=4, placeholder="••••")
                if st.form_submit_button("Verify OTP", type="primary", width="stretch"):
                    if code.strip() == b["otp"]:
                        b["stage"], b["t1"] = "started", dt.datetime.now()
                        st.rerun()
                    b["err"] = True
            if b["err"]:
                st.error("Incorrect OTP. Please try again.")
        else:
            ride_started()


# ----------------------------------------------------------------------------- navigation (automatic simulation)
def tick(nav):
    """Advance the simulation one step. Returns True once the hospital is reached."""
    ph, info = S.phase, nav["info"]
    if ph == "navigating_initial":
        S.idx = min(S.idx + STEP, len(info["path"]) - 1)
        if S.idx >= TRIG:
            e, f = nav["eta"], info["cum"][TRIG] / info["cum"][-1]
            prev = (max(1, round(e["lo"] * (1 - f))), max(1, round(e["hi"] * (1 - f))))
            nav["snap"] = dict(prev=prev, upd=(prev[0] + 10, prev[1] + 12), alt=(prev[0] + 2, prev[1] + 1), elapsed=e["exp"] * f)
            S.phase, S.hold = "incident_detected", 0
    elif ph == "incident_detected":
        S.hold += 1
        if S.hold >= HOLD_INC:
            S.phase, S.hold = "rerouting", 0
    elif ph == "rerouting":
        S.hold += 1
        if S.hold >= HOLD_RR:
            S.phase, S.idx, S.hold = "navigating_alternative", 0, 0
    elif ph == "navigating_alternative":
        S.idx = min(S.idx + STEP, len(nav["alt"]["path"]) - 1)
        if S.idx >= len(nav["alt"]["path"]) - 1:
            sn = nav["snap"]
            total = round(sn["elapsed"] + (sn["alt"][0] + sn["alt"][1]) / 2)
            nav["result"] = dict(total=total, final=(round(sn["elapsed"] + sn["alt"][0]), round(sn["elapsed"] + sn["alt"][1])),
                                 arrived=dt.datetime.now())
            e = nav["eta"]
            S.history.insert(0, dict(date=dt.datetime.now().strftime("Today, %H:%M"), hospital=nav["hosp"], route="Rerouted · avoided busy road",
                                     dist=f"{nav['info']['cum'][-1]:.1f} km", time=f"{total} min", est=rng(e["lo"], e["hi"]),
                                     ok=e["lo"] <= total <= e["hi"]))
            S.phase, S.screen = "arrived", "arrival"
            return True
    return False


def nav_state(nav):
    ph, sn = S.phase, nav["snap"]
    on_alt = ph == "navigating_alternative"
    info = nav["alt"] if on_alt else nav["info"]
    f = info["cum"][S.idx] / info["cum"][-1]
    if on_alt:
        rem = (max(1, round(sn["alt"][0] * (1 - f))), max(1, round(sn["alt"][1] * (1 - f))))
    elif sn:
        rem = sn["upd"]
    else:
        e = nav["eta"]
        rem = (max(1, round(e["lo"] * (1 - f))), max(1, round(e["hi"] * (1 - f))))
    return info, on_alt, rem, info["cum"][-1] - info["cum"][S.idx]


def nav_map(nav, info, on_alt):
    path = nav["info"]["path"]
    cur, b = info["path"][S.idx], info["brg"][S.idx]
    items = []
    if S.phase == "navigating_initial":
        items += [line(path[:S.idx + 1], GREY, 9), line(path[S.idx:], BLUE, 8)]
    else:
        items += [line(path[:TRIG + 1], GREY, 9), line(path[TRIG:], AMBER, 6, .6, "12 10"),
                  line(path[SEG[0]:SEG[1] + 1], RED, 12, .95)]
        if on_alt:
            items += [line(info["path"][:S.idx + 1], GREY, 9), line(info["path"][S.idx:], GREEN, 9)]
        elif S.phase == "rerouting" and S.hold >= 3:
            items += [line(nav["alt"]["path"], GREEN, 9, .85, "4 10")]
        items += [folium.Circle(path[INC], radius=260, color=RED, fill=True, fill_opacity=.12, weight=1), incident_pin(path[INC])]
    items += [me_pin(path[0]), hospital_pin(path[-1], nav["hosp"]), arrow(cur, b)]
    draw_map("map_nav", items, cur, 16, 740, leg="bottom:64px;left:12px", zoomctl=False)


def nav_cards(nav, info, on_alt, rem, dist):
    sn, ph = nav["snap"], S.phase
    kind = "Fastest route" if nav["kind"] == "fast" else "Most reliable route"
    h = HOSPITALS[nav["hosp"]]
    # --- instruction card (+ reroute confirmation)
    with st.container(key="nav_instr"):
        if ph == "incident_detected":
            ic, t, s = "stop", "Reducing speed", "Road ahead looks too busy"
        elif ph == "rerouting":
            ic, t, s = "calc", "Calculating a new route", "Stay on the current road"
        else:
            ic, t, s = instruction(info, S.idx, nav["hosp"])
        st.markdown(f'<div class="float sm"><div class="instr"><div class="ar">{ARROWS[ic]}</div><div><b>{t}</b><small>{s}</small></div></div></div>',
                    unsafe_allow_html=True)
        if on_alt:
            st.markdown(f'<div class="float sm"><div class="row" style="align-items:flex-start"><div class="ico g">'
                        f'<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
                        f'<circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M8 19h3a3 3 0 0 0 3-3v-1a3 3 0 0 0-3-3h2a3 3 0 0 0 3-3V7"/></svg></div>'
                        f'<div>{pill("Safer route found")}<div class="ttl" style="margin-top:6px;font-size:15px">Navigation updated automatically</div>'
                        f'<div style="font-size:12px;color:#64748b;margin-top:3px;line-height:1.5">The original route looks too busy. A route with a '
                        f'lower worst-case ETA has been selected.</div></div></div>'
                        f'<div class="row sp" style="background:#ecfdf5;border-radius:12px;padding:10px 14px;margin-top:12px"><div><small style="color:#047857;font-size:10px">'
                        f'Updated ETA</small><div style="font-weight:700;color:#065f46">{rng(*rem)}</div></div><div style="text-align:right"><small style="color:#047857;font-size:10px">'
                        f'Time saved</small><div style="font-weight:700;color:#065f46">{sn["upd"][0] - sn["alt"][0]}–{sn["upd"][1] - sn["alt"][1]} min</div></div></div></div>',
                        unsafe_allow_html=True)
    with st.container(key="nav_close"):
        if st.button("✕", key="nav_x"):
            goto("overview")
            st.rerun()
    # --- incident / rerouting overlay
    if ph in ("incident_detected", "rerouting"):
        with st.container(key="nav_alert"):
            if ph == "incident_detected":
                st.markdown(f'<div class="float" style="border:1px solid #fecaca"><div class="row" style="align-items:flex-start;gap:14px">'
                            f'<div class="ico r" style="width:48px;height:48px;border-radius:16px;font-size:22px">⚠</div><div style="flex:1">'
                            f'<div class="row sp">{pill("Heavy traffic ahead", "amber")}<span class="mut">Just now</span></div>'
                            f'<div class="ttl xl" style="margin-top:10px">Road looks too busy</div>'
                            f'<p style="font-size:13px;line-height:1.7;color:#64748b;margin:6px 0 0">The road ahead on your current route looks too busy. '
                            f'Travel time on the affected road segment has increased.</p></div></div>'
                            f'<div class="two"><div style="background:#fef2f2"><small style="color:#ef4444">Previous ETA</small><b style="color:#b91c1c">{rng(*sn["prev"])}</b></div>'
                            f'<div style="background:#fff7ed"><small style="color:#c2410c">Updated ETA</small><b style="color:#c2410c">{rng(*sn["upd"])}</b></div></div></div>',
                            unsafe_allow_html=True)
            else:
                alt_txt = (f'<div class="two"><div style="background:#fff7ed"><small style="color:#c2410c">Previous route</small><b style="color:#c2410c">{rng(*sn["upd"])}</b></div>'
                           f'<div style="background:#ecfdf5"><small style="color:#047857">Alternative route</small><b style="color:#065f46">{rng(*sn["alt"])}</b></div></div>'
                           if S.hold >= 3 else "")
                st.markdown(f'<div class="float" style="border:1px solid #fde68a"><div class="row" style="align-items:flex-start;gap:14px">'
                            f'<div class="ico" style="width:48px;height:48px;border-radius:16px;background:#fffbeb;color:#d97706;font-size:22px">⟳</div><div>'
                            f'{pill("Re-routing", "amber")}<div class="ttl xl" style="margin-top:10px">Evaluating alternative routes'
                            f'<span class="dots"><span>.</span><span>.</span><span>.</span></span></div>'
                            f'<p style="font-size:13px;line-height:1.7;color:#64748b;margin:6px 0 0">Road conditions have changed. Evaluating alternative routes…</p>'
                            f'</div></div>{alt_txt}</div>', unsafe_allow_html=True)
    # --- bottom card
    with st.container(key="nav_bottom"):
        prog = info["cum"][S.idx] / info["cum"][-1]
        mid = round((rem[0] + rem[1]) / 2)
        status = {"navigating_initial": ("Navigating · " + kind, "blue"), "incident_detected": ("Road looks too busy", "red"),
                  "rerouting": ("Re-routing", "amber"), "navigating_alternative": ("Following alternative route", "green")}[ph]
        conf = "Low confidence" if nav["wide"] > 1 else "High confidence"
        st.markdown(f'<div class="float"><div class="row sp"><div class="row"><div class="ico r" style="width:48px;height:48px;border-radius:12px">{hsvg(22)}</div>'
                    f'<div><p class="eyebrow">Destination</p><div class="ttl" style="font-size:17px;margin-top:3px">{nav["hosp"]}</div>'
                    f'<div class="mut">Emergency entrance · {h["area"]}</div></div></div><div style="text-align:right"><div class="etabig">{mid} <small>min</small></div>'
                    f'<div class="mut">{dist:.1f} km · ETA {clock(mid)}</div></div></div>'
                    f'<div class="prog" style="margin-top:16px"><i style="width:{prog * 100:.0f}%"></i></div>'
                    f'<div class="row sp" style="margin-top:12px"><div class="row" style="font-size:11px;font-weight:600;color:#059669;gap:6px">{SHIELD} '
                    f'Arrival range {clock(rem[0])}–{clock(rem[1])} · {rng(*rem)} · {conf}</div>{pill(*status)}</div></div>', unsafe_allow_html=True)


@st.fragment(run_every=TICK)
def navigation():
    nav = S.nav
    if tick(nav):
        st.rerun()  # full-app rerun -> arrival screen, fragment timer stops
    info, on_alt, rem, dist = nav_state(nav)
    with st.container(key="navwrap"):
        nav_map(nav, info, on_alt)
        nav_cards(nav, info, on_alt, rem, dist)


# ----------------------------------------------------------------------------- arrival
def arrival():
    nav = S.nav
    sn, res, e = nav["snap"], nav["result"], nav["eta"]
    a = res["arrived"]
    st.markdown(f'<div style="text-align:center;max-width:760px;margin:0 auto"><div class="done"><svg width="38" height="38" viewBox="0 0 24 24" fill="none" '
                f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 4 4L19 6"/></svg></div>'
                f'<p class="eyebrow" style="color:#059669;margin-top:26px">Journey complete</p><h1 style="font-size:2.6rem;font-weight:600;margin:6px 0;padding:0">'
                f'You’ve arrived safely</h1><p style="font-size:14px;color:#64748b">{nav["hosp"]} · Emergency entrance</p></div>', unsafe_allow_html=True)
    l, r = st.columns([5, 6], gap="medium")
    with l:
        with st.container(key="panel_sum"):
            st.markdown(f'<div class="row sp" style="border-bottom:1px solid #f1f5f9;padding-bottom:16px"><div><div class="mut">{a.strftime("%A, %d %B")}</div>'
                        f'<div class="ttl xl" style="margin-top:4px">Journey summary</div></div>{pill("Rerouted safely", "blue")}</div>'
                        f'<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:22px;padding:22px 0 8px">'
                        f'<div class="sum"><b>{res["total"]} min</b><small>Total journey</small></div>'
                        f'<div class="sum"><b>{a.strftime("%H:%M")}</b><small>Arrival time</small></div>'
                        f'<div class="sum"><b>{rng(e["lo"], e["hi"]).replace(" min", "")}</b><small>Original ETA (min)</small></div>'
                        f'<div class="sum"><b>{rng(*res["final"]).replace(" min", "")}</b><small>Final ETA (min)</small></div></div>'
                        f'<div class="tl" style="margin-top:14px"><div><b>Navigation started</b><br><small>{"Fastest" if nav["kind"] == "fast" else "Most reliable"} route · ETA {rng(e["lo"], e["hi"])}</small></div>'
                        f'<div class="r"><b>Busy road encountered</b><br><small>Road looks too busy · ETA rose to {rng(*sn["upd"])}</small></div>'
                        f'<div class="g"><b>Automatic reroute</b><br><small>Lower worst-case ETA ({sn["alt"][1]} min vs {sn["upd"][1]} min) selected</small></div>'
                        f'<div class="g"><b>Arrived at {nav["hosp"]}</b><br><small>Route followed: original route → alternative safer route</small></div></div>'
                        f'<div class="card" style="background:#f8fafc;margin:8px 0 0"><div class="row"><div class="ico g" style="border-radius:50%;width:36px;height:36px">{SHIELD}</div>'
                        f'<div><div style="font-size:12px;font-weight:700">Why we rerouted</div><div class="mut">The original route looked too busy. An alternative route '
                        f'with a lower worst-case ETA was selected automatically.</div></div></div></div>', unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        b1.button("Return to overview", type="primary", width="stretch", on_click=goto, args=("overview",))
        b2.button("View trip history", width="stretch", on_click=goto, args=("history",))
    with r:
        p, al = nav["info"]["path"], nav["alt"]["path"]
        items = [line(p, AMBER, 5, .7, "10 12"), line(p[SEG[0]:SEG[1] + 1], RED, 10), line(al, GREEN, 9), me_pin(p[0]), hospital_pin(p[-1], nav["hosp"]),
                 incident_pin(p[INC])]
        draw_map("map_done", items, ((p[0][0] + p[-1][0]) / 2, (p[0][1] + p[-1][1]) / 2), zoom_for(p[0], p[-1]), 640, leg="bottom:24px;left:12px")


# ----------------------------------------------------------------------------- planner
def profile(h):
    g = lambda c, w, a: a * math.exp(-((h - c) / w) ** 2)
    return 1 + g(8.25, .8, 1.0) + g(10, .5, .35) + g(13, .7, .5) + g(18, 1.2, 1.2)


def planner():
    times = [f"{h:02d}:{m:02d}" for h in range(6, 22) for m in (0, 30)]
    names = list(HOSPITALS)
    left, right = st.columns([1, 2.2], gap="medium")
    with left:
        with st.container(key="panel_form"):
            st.markdown(f'<p class="eyebrow">Trip details</p><div class="ttl xl" style="margin:6px 0 16px">Best Departure Time Planner</div>'
                        f'<div class="card" style="padding:12px"><div class="row"><div class="ico s" style="width:36px;height:36px;color:#2563eb">📍</div><div>'
                        f'<p class="eyebrow" style="font-size:9px">Starting point</p><div style="font-size:13px;font-weight:600;margin-top:3px">{start_label}</div></div></div></div>',
                        unsafe_allow_html=True)
            dest = st.selectbox("Destination hospital", names, index=2)
            c1, c2 = st.columns(2)
            earliest = c1.selectbox("Earliest departure", times, index=times.index("08:00"))
            latest = c2.selectbox("Latest departure", times, index=times.index("10:00"))
            if st.button("Find Best Departure Time  →", type="primary", width="stretch"):
                if latest <= earliest:
                    st.error("Latest departure must be after the earliest departure.")
                else:
                    S.plan = dict(dest=dest, e=earliest, l=latest)
    p = S.plan
    with right:
        if not p:
            st.markdown('<div class="card" style="padding:28px;text-align:center;color:#64748b">Choose a hospital and a time window, then click '
                        '<b>Find Best Departure Time</b> to see predicted travel times for each departure.</div>', unsafe_allow_html=True)
            return
        base = km(start, HOSPITALS[p["dest"]]["pos"]) * 1.4 / 30 * 60
        rows = []
        for t in times[times.index(p["e"]):times.index(p["l"]) + 1]:
            h = int(t[:2]) + int(t[3:]) / 60
            m, exp = profile(h), base * profile(h)
            sp = .1 + .1 * (m - 1)
            rows.append(dict(t=t, exp=round(exp, 1), lo=round(exp * (1 - sp)), hi=round(exp * (1 + 1.3 * sp))))
        best = min(rows, key=lambda r: r["exp"])
        worst = max(rows, key=lambda r: r["exp"])
        avg = sum(r["exp"] for r in rows) / len(rows)
        x = [r["t"] for r in rows]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=[r["hi"] for r in rows], line=dict(width=0), hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=[r["lo"] for r in rows], fill="tonexty", fillcolor="rgba(37,99,235,.14)", line=dict(width=0),
                                 name="P10–P90 uncertainty", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=[r["exp"] for r in rows], mode="lines+markers", name="Expected travel time",
                                 line=dict(color=BLUE, width=3), marker=dict(size=8)))
        fig.add_trace(go.Scatter(x=[best["t"]], y=[best["exp"]], mode="markers", name="Recommended",
                                 marker=dict(symbol="star", size=22, color="#10b981", line=dict(color="#fff", width=2))))
        fig.update_layout(height=330, margin=dict(l=0, r=0, t=6, b=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          yaxis=dict(title="minutes", gridcolor="#e2e8f0"), xaxis=dict(title="departure time"), font=dict(family="DM Sans", size=11),
                          legend=dict(orientation="h", y=1.14))
        with st.container(key="panel_chart"):
            st.markdown(f'<div class="row sp" style="align-items:flex-start"><div><p class="eyebrow">Travel-time forecast</p><div class="ttl xl" style="margin-top:6px">'
                        f'Best time to leave</div><div class="mut">Predictions for {p["dest"]}</div></div>{pill("Recommendation ready")}</div>', unsafe_allow_html=True)
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        i = rows.index(best)
        picks = rows[max(0, min(i - 1, len(rows) - 3)):][:3]
        cols = st.columns(len(picks), gap="small")
        for c, q in zip(cols, picks):
            isb = q is best
            c.markdown(f'<div class="fc {"best" if isb else ""}" style="margin-top:12px"><div class="row sp"><b style="font-size:12px">{q["t"]}</b>'
                       f'{pill("Best time") if isb else ""}</div><b class="d">{q["exp"]} min</b><div class="mut">P10–P90 · {rng(q["lo"], q["hi"])}</div>'
                       f'<div class="foot" style="font-weight:600">{"Light" if q["exp"] < avg * .9 else "Moderate" if q["exp"] < avg * 1.1 else "Heavy"} traffic</div></div>',
                       unsafe_allow_html=True)
        st.markdown(f'<div class="alert al-green" style="margin-top:14px"><b>Recommended departure: {best["t"]}</b><p>Expected travel time <b>{best["exp"]} min</b> '
                    f'(range {rng(best["lo"], best["hi"])}). Saves <b>{worst["exp"] - best["exp"]:.1f} min</b> versus leaving at {worst["t"]} and '
                    f'<b>{avg - best["exp"]:.1f} min</b> versus the window average.</p><p>Why: traffic on the route to {p["dest"]} is lightest then and the ETA range '
                    f'is narrowest, so you arrive on time with the least risk.</p></div>', unsafe_allow_html=True)
        with st.expander("All departure options"):
            body = "".join(f'<div class="hist" style="grid-template-columns:1fr 1fr 1fr;{"background:#ecfdf5;font-weight:700" if q is best else ""}">'
                           f'<span>{q["t"]}{" ★" if q is best else ""}</span><span>{rng(q["lo"], q["hi"])}</span><span>{q["exp"]} min</span></div>' for q in rows)
            st.markdown('<div class="hist" style="grid-template-columns:1fr 1fr 1fr;border:none;font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase">'
                        f'<span>Departure</span><span>ETA range</span><span>Expected</span></div>{body}', unsafe_allow_html=True)
        if st.button("Confirm and Start Trip  →", type="primary", key="confirm_trip"):
            S.hosp, S.hosp_manual, S.route = p["dest"], True, "rel"
            S.book = dict(stage="started")  # non-urgent trip: no ambulance needed
            S.screen = "compare"
            st.rerun()


# ----------------------------------------------------------------------------- history
def history():
    trips = S.history + PAST_TRIPS
    c = st.columns(3, gap="medium")
    for col, (v, l, t, k) in zip(c, [(str(12 + len(S.history)), "Journeys completed", f"+{3 + len(S.history)} this month", "g"),
                                     ("92%", "ETA accuracy", "Within confidence range", "g"),
                                     ("12.4 min", "Average journey", "2.1 min faster", "g")]):
        with col:
            with st.container(key=f"panel_stat_{l[:3]}"):
                st.markdown(f'<div class="stat">{v}</div><div class="statl">{l}</div><div class="statt">{t}</div>', unsafe_allow_html=True)
    st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
    with st.container(key="panel_hist"):
        st.markdown('<p class="eyebrow">Recent activity</p><div class="ttl" style="margin:4px 0 6px;font-size:17px">Previous journeys</div>', unsafe_allow_html=True)
        for i, t in enumerate(trips):
            st.markdown(f'<div class="hist"><div class="row"><div class="ico {"b" if i == 0 else "s"}" style="width:44px;height:44px">{hsvg(19)}</div>'
                        f'<div><div style="font-size:14px;font-weight:700">{t["hospital"]}</div><div class="mut">{t["date"]}</div></div></div>'
                        f'<div><div style="font-size:12px;font-weight:600">{t["route"]}</div><div class="mut">{t["dist"]}</div></div>'
                        f'<div><div style="font-size:14px;font-weight:700">{t["time"]}</div><div class="mut">Estimate {t["est"]}</div></div>'
                        f'<div>{pill("Within range") if t["ok"] else pill("Outside range", "amber")}</div></div>', unsafe_allow_html=True)


# ----------------------------------------------------------------------------- router
if S.screen in ("compare", "navigation") and (S.book or {}).get("stage") != "started":
    S.screen = "booking"  # guard: navigation requires a verified ambulance ride
{"overview": overview, "booking": booking, "hospitals": hospitals, "compare": compare, "navigation": navigation, "arrival": arrival,
 "planner": planner, "history": history}[S.screen]()
