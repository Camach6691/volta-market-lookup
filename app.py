"""
Volta Global — Market Lookup Tool  (v2 — Interactive Weights)
Adjust criterion weights live; scores and tiers update instantly.
"""

import re
import math
import streamlit as st
import pandas as pd
from rapidfuzz import fuzz, process

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Market Lookup · Volta Global",
    page_icon="🏢",
    layout="wide",
)

# ─── Styles ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background: #f0f2f6; }
  [data-testid="stSidebar"] { background: #1B2A4A !important; }
  [data-testid="stSidebar"] * { color: #e2e8f0 !important; }
  [data-testid="stSidebar"] .stSlider > div > div > div { background: #3b6cb7 !important; }
  [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
  [data-testid="stSidebar"] h3 { color: white !important; }
  [data-testid="stSidebar"] label { color: #a8b8d4 !important; font-size: 0.82rem !important; }
  [data-testid="stSidebar"] .stMetric label { color: #a8b8d4 !important; }
  [data-testid="stSidebar"] .stMetric [data-testid="metric-container"] > div { color: white !important; }
  [data-testid="stSidebar"] hr { border-color: #2d4a7a !important; }

  .tier-badge {
    display: inline-block; padding: 5px 18px; border-radius: 6px;
    font-size: 1.3rem; font-weight: 800; letter-spacing: 0.05em;
  }
  .tier-A { background:#d1fae5; color:#065f46; }
  .tier-B { background:#dbeafe; color:#1e40af; }
  .tier-C { background:#fef3c7; color:#92400e; }
  .tier-D { background:#ffe4e6; color:#9f1239; }
  .tier-E { background:#f3e8ff; color:#6b21a8; }
  .tier-x { background:#f1f5f9; color:#64748b; }

  .result-card {
    background:white; border-radius:12px; padding:20px 24px;
    margin-bottom:14px; border:1px solid #e2e8f0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }
  .msa-tag {
    display:inline-block; background:#f1f5f9; color:#475569;
    border-radius:4px; padding:2px 8px; font-size:0.78rem; margin-bottom:8px;
  }
  .metric-grid { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
  .metric-chip {
    background:#f8fafc; border:1px solid #e2e8f0; border-radius:5px;
    padding:4px 10px; font-size:0.79rem; color:#334155;
  }
  .metric-chip span { font-weight:600; color:#1B2A4A; }
  .score-bar-bg { background:#e2e8f0; border-radius:4px; height:7px; margin-top:4px; }
  .score-bar-fill { height:7px; border-radius:4px;
    background: linear-gradient(90deg, #1B2A4A, #3b6cb7); }
  .no-results { text-align:center; padding:60px 0; color:#94a3b8; }
  .rank-pill {
    display:inline-block; background:#f1f5f9; color:#64748b;
    border-radius:20px; padding:2px 10px; font-size:0.8rem;
  }
</style>
""", unsafe_allow_html=True)

# ─── Raw data ─────────────────────────────────────────────────────────────────
@st.cache_data
def load_raw():
    df = pd.read_csv("data/sub_markets.csv")
    # Score columns
    score_cols = ["Sc:Rate","Sc:Sat","Sc:HHI","Sc:Grw","Sc:Tax","Sc:Crm","Sc:Bas","Sc:Exit"]
    for c in score_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

RAW = load_raw()

CRITERIA = [
    ("CC Rate/SF",           "Sc:Rate", 20, "↑ Higher = better",  "CC rent $/mo/SF — revenue potential"),
    ("Saturation (SF/Cap)",  "Sc:Sat",  20, "↓ Lower = better",   "Storage SF per capita — less competition"),
    ("Median HHI",           "Sc:HHI",   5, "↑ Higher = better",  "Household income — willingness to pay"),
    ("Supply Growth",        "Sc:Grw",   5, "↓ Lower = better",   "New storage pipeline — future competition"),
    ("Commercial Tax Rate",  "Sc:Tax",  10, "↓ Lower = better",   "All-in effective commercial tax rate"),
    ("Crime Rate",           "Sc:Crm",   5, "↓ Lower = better",   "Violent + property crime per 100K"),
    ("Ind. Acq. Basis",      "Sc:Bas",  20, "↓ Lower = better",   "Industrial sale $/SF — conversion entry cost"),
    ("SS Exit (Stabilized)", "Sc:Exit", 15, "↑ Higher = better",  "Stabilized Class A CC exit $/SF"),
]

SCORE_COLS = [c[1] for c in CRITERIA]
DEFAULT_WEIGHTS = {c[1]: c[2] for c in CRITERIA}

# Default tier percentile cutoffs matching the Excel model:
# Tier A = top 25% · B = next 20% · C = next 25% · D = next 15% · E = bottom 15%
DEFAULT_TIERS = {"A": 25, "B": 20, "C": 25, "D": 15}  # E = remainder

# ─── Scoring function ─────────────────────────────────────────────────────────
def recalculate(df: pd.DataFrame, weights: dict, tier_pcts: dict) -> pd.DataFrame:
    """Recompute Score and Tier using custom weights.

    ALL markets are ranked. Missing score columns are filled with 0 (low penalty).
    A '_missing' column tracks which criteria labels were absent for each row.
    """
    out = df.copy()
    total_w = sum(weights.values()) or 1
    active_cols = [col for col in SCORE_COLS if weights.get(col, 0) > 0]

    # Build a label map so we can show human-readable names for missing criteria
    col_to_label = {c[1]: c[0] for c in CRITERIA}

    # Track which criteria are missing per row
    def get_missing(row):
        missing = [col_to_label[c] for c in active_cols if pd.isna(row[c])]
        return ", ".join(missing) if missing else ""
    out["_missing"] = out.apply(get_missing, axis=1)

    # Fill missing scores with 0 (lowest possible score = penalty for missing data)
    score_df = out[active_cols].fillna(0)

    # Weighted composite score for ALL rows
    out["Score"] = sum(score_df[col] * (weights[col] / total_w) for col in active_cols)

    # Rank all rows (1 = best)
    out["Rank"] = out["Score"].rank(ascending=False, method="min").astype("Int64")

    # Tier: percentile cutoffs applied to all rows
    n_total = len(out)
    a_cut = math.ceil(n_total * tier_pcts["A"] / 100)
    b_cut = math.ceil(n_total * (tier_pcts["A"] + tier_pcts["B"]) / 100)
    c_cut = math.ceil(n_total * sum([tier_pcts["A"], tier_pcts["B"], tier_pcts["C"]]) / 100)
    d_cut = math.ceil(n_total * sum(tier_pcts.values()) / 100)

    rank = out["Rank"]
    out["Tier"] = "E"
    out.loc[rank <= a_cut, "Tier"] = "A"
    out.loc[(rank > a_cut) & (rank <= b_cut), "Tier"] = "B"
    out.loc[(rank > b_cut) & (rank <= c_cut), "Tier"] = "C"
    out.loc[(rank > d_cut), "Tier"] = "E"
    out.loc[(rank > c_cut) & (rank <= d_cut), "Tier"] = "D"

    return out

# ─── Search ──────────────────────────────────────────────────────────────────
US_STATES = {
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in","ia",
    "ks","ky","la","me","md","ma","mi","mn","ms","mo","mt","ne","nv","nh","nj",
    "nm","ny","nc","nd","oh","ok","or","pa","ri","sc","sd","tn","tx","ut","vt",
    "va","wa","wv","wi","wy"
}

def build_search_index(df):
    df = df.copy()
    df["_search"] = (df["Market"].fillna("") + ", " +
                     df["ST"].fillna("") + "  " +
                     df["MSA"].fillna(""))
    return df

def extract_from_url(url: str):
    full = url.lower().replace('%20','-').replace('_','-').replace('+','-')
    pattern = r'([a-z][a-z0-9-]+)-(' + '|'.join(sorted(US_STATES)) + r')(?:[/\-\s]|$)'
    best = None
    for m in re.finditer(pattern, full):
        slug, state = m.group(1), m.group(2)
        if len(slug) < 3: continue
        best = (re.sub(r'-+', ' ', slug).title(), state.upper())
    return best or (None, None)

def extract_from_address(text: str):
    m = re.search(r',\s*([A-Za-z][A-Za-z\s]+?),?\s+([A-Z]{2})\b', text)
    if m: return m.group(1).strip(), m.group(2).strip()
    m2 = re.search(r'\b([A-Za-z][A-Za-z\s]+)\s+([A-Z]{2})\b', text)
    if m2 and m2.group(2).lower() in US_STATES:
        return m2.group(1).strip(), m2.group(2).strip()
    return None, None

def search_markets(query: str, df: pd.DataFrame, top_n=8):
    choices = df["_search"].tolist()
    hits = process.extract(query, choices, scorer=fuzz.WRatio, limit=top_n * 3)
    seen, rows = set(), []
    for _, score, idx in hits:
        if score < 40: continue
        row = df.iloc[idx].copy()
        key = row["Market"]
        if key not in seen:
            seen.add(key)
            row["_match"] = score
            rows.append(row)
        if len(rows) >= top_n: break
    return rows

# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚖️ Model Weights")
    st.markdown("*Drag to adjust — total auto-normalizes to 100%*")
    st.markdown("---")

    raw_weights = {}
    for label, col, default, direction, desc in CRITERIA:
        raw_weights[col] = st.slider(
            f"{label}  `{direction}`",
            min_value=0, max_value=50,
            value=default,
            step=1,
            help=desc,
            key=f"w_{col}",
        )

    total_raw = sum(raw_weights.values()) or 1
    weights = {k: v / total_raw * 100 for k, v in raw_weights.items()}

    st.markdown("---")
    # Show effective weights
    st.markdown("**Effective weights:**")
    for label, col, *_ in CRITERIA:
        pct = weights[col]
        bar_w = int(pct * 3)
        st.markdown(
            f"<div style='font-size:0.78rem;margin-bottom:2px;'>"
            f"<span style='color:#a8b8d4'>{label}</span> "
            f"<span style='color:white;float:right'>{pct:.0f}%</span></div>"
            f"<div style='background:#2d4a7a;border-radius:3px;height:5px;'>"
            f"<div style='background:#4a9eff;width:{pct*2:.0f}%;height:5px;border-radius:3px;'></div></div>",
            unsafe_allow_html=True
        )

    st.markdown("---")
    st.markdown("## 🏷️ Tier Cutoffs")
    st.markdown("*% of ranked markets per tier*")

    t_a = st.slider("Tier A (top %)", 5, 40, DEFAULT_TIERS["A"], step=1)
    t_b = st.slider("Tier B (%)",      5, 30, DEFAULT_TIERS["B"], step=1)
    t_c = st.slider("Tier C (%)",      5, 40, DEFAULT_TIERS["C"], step=1)
    t_d = st.slider("Tier D (%)",      5, 30, DEFAULT_TIERS["D"], step=1)
    t_e = 100 - t_a - t_b - t_c - t_d
    tier_pcts = {"A": t_a, "B": t_b, "C": t_c, "D": t_d}

    st.markdown(
        f"<div style='font-size:0.82rem;margin-top:6px;'>"
        f"A:{t_a}% · B:{t_b}% · C:{t_c}% · D:{t_d}% · E:{max(t_e,0)}%</div>",
        unsafe_allow_html=True
    )

    st.markdown("---")
    if st.button("↺ Reset to defaults", use_container_width=True):
        for label, col, default, *_ in CRITERIA:
            st.session_state[f"w_{col}"] = default
        st.rerun()

# ─── Recalculate with current weights ─────────────────────────────────────────
# Use cache keyed on weights + tier settings for speed
@st.cache_data(show_spinner=False)
def get_scored(weight_tuple, tier_tuple, _v=3):
    w = dict(weight_tuple)
    t = dict(tier_tuple)
    df = recalculate(RAW, w, t)
    return build_search_index(df)

weight_tuple = tuple(sorted(raw_weights.items()))
tier_tuple   = tuple(sorted(tier_pcts.items()))
DF = get_scored(weight_tuple, tier_tuple)

# ─── Header ──────────────────────────────────────────────────────────────────
st.markdown("""
<div style="background:#1B2A4A;border-radius:12px;padding:22px 32px 16px;margin-bottom:20px;">
  <h1 style="color:white;margin:0;font-size:1.6rem;font-weight:700;">🏢 Market Lookup</h1>
  <p style="color:#a8b8d4;margin:6px 0 0;font-size:0.92rem;">
    Volta Global · Self-Storage Market Intelligence · 5,175 sub-markets · Adjust weights in sidebar →
  </p>
</div>
""", unsafe_allow_html=True)

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab_search, tab_browse = st.tabs(["🔍 Search by Address or Link", "📊 Browse All Markets"])

# ─── TAB 1: Search ────────────────────────────────────────────────────────────
with tab_search:
    user_input = st.text_input(
        label="",
        placeholder="Paste a CoStar / Crexi link  —or—  type a city, address, or market name…",
        label_visibility="collapsed",
    )
    st.caption("Examples: 'Nashville, TN' · '2150 Market St, Denver, CO 80202' · https://crexi.com/properties/.../houston-tx-storage")

    def fmt(val, pct=False, dollar=False, k=False):
        if val is None or (isinstance(val, float) and pd.isna(val)): return "—"
        try:
            if pct:    return f"{float(val)*100:.1f}%"
            if dollar: return f"${float(val):,.0f}"
            if k:      return f"{float(val)/1000:.0f}k SF"
            return str(val)
        except: return "—"

    def render_result(row):
        tier   = str(row.get("Tier", "—"))
        market = row.get("Market","")
        msa    = row.get("MSA","")
        score  = row.get("Score")
        rank   = row.get("Rank")
        match_pct = int(row.get("_match", 0))

        score_pct = float(score) * 100 if (score is not None and not pd.isna(score)) else None
        badge_cls = f"tier-{tier}" if tier in "ABCDE" else "tier-x"

        score_bar = ""
        if score_pct is not None:
            score_bar = (
                f"<div style='font-size:0.78rem;color:#64748b;margin:8px 0 3px'>"
                f"Composite Score: <strong>{score_pct:.1f}%</strong></div>"
                f"<div class='score-bar-bg'><div class='score-bar-fill' style='width:{score_pct:.0f}%'></div></div>"
            )

        rank_txt = f'<div style="font-size:0.8rem;color:#64748b;margin-top:4px;">Rank #{int(rank):,} of {len(DF):,} ranked markets</div>' if (rank is not None and not pd.isna(rank)) else ""

        missing_data = row.get("_missing", "")
        missing_txt = (
            f'<div style="margin-top:8px;padding:6px 10px;background:#fffbeb;border:1px solid #fcd34d;'
            f'border-radius:6px;font-size:0.78rem;color:#92400e;">'
            f'⚠️ <strong>Incomplete data</strong> — scored 0 for: {missing_data}</div>'
        ) if missing_data else ""

        chips = "".join(
            f'<div class="metric-chip">{k}: <span>{v}</span></div>'
            for k, v in [
                ("CC Rate/SF",   fmt(row.get("CC Rate"), dollar=True)),
                ("SF/Capita",    fmt(row.get("SF/Cap")) + " sf"),
                ("Med HHI",      fmt(row.get("Med HHI"), dollar=True)),
                ("Sup Growth",   fmt(row.get("Sup Gr%"), pct=True)),
                ("SF Dev",       fmt(row.get("SF Dev"), k=True)),
                ("Yld/Basis",    fmt(row.get("Yld/Basis"), pct=True)),
                ("Tax Rate",     fmt(row.get("Tax"), pct=True)),
                ("Crime Index",  fmt(row.get("Crime"))),
            ] if v != "— sf" and v != "—"
        )

        match_badge = f'<span style="float:right;font-size:0.75rem;color:#94a3b8">{match_pct}% match</span>' if match_pct else ""

        st.markdown(f"""
        <div class="result-card">
          {match_badge}
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px;">
            <div class="tier-badge {badge_cls}">Tier {tier}</div>
            <div>
              <div style="font-size:1.05rem;font-weight:700;color:#1B2A4A">{market}</div>
              <div class="msa-tag">{msa}</div>
            </div>
          </div>
          {score_bar}
          {rank_txt}
          {missing_txt}
          <hr style="border:none;border-top:1px solid #f1f5f9;margin:10px 0">
          <div class="metric-grid">{chips}</div>
        </div>
        """, unsafe_allow_html=True)

    if user_input and user_input.strip():
        raw_in = user_input.strip()
        is_url = raw_in.startswith("http") or "costar.com" in raw_in.lower() or "crexi.com" in raw_in.lower()

        query = raw_in
        note  = None

        if is_url:
            city, state = extract_from_url(raw_in)
            if city and state:
                query = f"{city}, {state}"
                note  = f"📍 Detected: **{city}, {state}** — showing sub-markets"
            else:
                note = "⚠️ Couldn't auto-detect city from this URL. Try pasting the address directly."
        else:
            city, state = extract_from_address(raw_in)
            if city and state: query = f"{city}, {state}"

        if note: st.info(note)

        with st.spinner("Searching…"):
            results = search_markets(query, DF)

        if results:
            st.markdown(f"#### Results for *{query}*")
            for row in results:
                render_result(row)
        else:
            st.markdown('<div class="no-results"><div style="font-size:2rem">🔍</div><div>No matches found — try a different city or MSA name</div></div>', unsafe_allow_html=True)

    else:
        # Idle state: tier summary using current weights
        col1, col2, col3, col4, col5 = st.columns(5)
        for col, tier, bg, fg in [
            (col1, "A", "#d1fae5", "#065f46"),
            (col2, "B", "#dbeafe", "#1e40af"),
            (col3, "C", "#fef3c7", "#92400e"),
            (col4, "D", "#ffe4e6", "#9f1239"),
            (col5, "E", "#f3e8ff", "#6b21a8"),
        ]:
            n = (DF["Tier"] == tier).sum()
            with col:
                st.markdown(
                    f"<div style='background:{bg};border-radius:10px;padding:16px;text-align:center;'>"
                    f"<div style='font-size:1.6rem;font-weight:800;color:{fg}'>Tier {tier}</div>"
                    f"<div style='font-size:1.1rem;font-weight:600;color:{fg}'>{n:,}</div>"
                    f"<div style='font-size:0.75rem;color:{fg};opacity:0.75'>markets</div></div>",
                    unsafe_allow_html=True
                )
        st.caption("← Adjust weights in the sidebar — tier counts update in real time")

# ─── TAB 2: Browse ───────────────────────────────────────────────────────────
with tab_browse:
    st.markdown("#### All Markets — Sorted by Current Score")

    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        tier_filter = st.multiselect(
            "Filter by Tier", ["A","B","C","D","E"],
            default=["A","B"],
            key="tier_filter"
        )
    with c2:
        state_opts = sorted(DF["ST"].dropna().unique())
        state_filter = st.multiselect("Filter by State", state_opts, key="state_filter")
    with c3:
        search_filter = st.text_input("Search market name", "", key="browse_search")

    view = DF.copy()
    if tier_filter:
        view = view[view["Tier"].isin(tier_filter)]
    if state_filter:
        view = view[view["ST"].isin(state_filter)]
    if search_filter:
        mask = view["Market"].str.contains(search_filter, case=False, na=False)
        view = view[mask]

    view = view.sort_values("Score", ascending=False)

    # Display table
    display_cols = {
        "Tier": "Tier",
        "Rank": "Rank",
        "Market": "Sub-Market",
        "ST": "State",
        "MSA": "MSA",
        "Score": "Score",
        "CC Rate": "CC Rate/SF",
        "SF/Cap": "SF/Cap",
        "Med HHI": "Med HHI",
        "Sup Gr%": "Sup Growth%",
        "Yld/Basis": "Yld/Basis",
    }
    tbl = view[list(display_cols.keys())].rename(columns=display_cols).reset_index(drop=True)
    tbl["Score"] = tbl["Score"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—")
    tbl["Yld/Basis"] = view["Yld/Basis"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—").values
    tbl["Sup Growth%"] = view["Sup Gr%"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—").values
    tbl["Med HHI"] = view["Med HHI"].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "—").values

    def color_tier(val):
        colors = {"A": "background-color:#d1fae5;color:#065f46;font-weight:700",
                  "B": "background-color:#dbeafe;color:#1e40af;font-weight:700",
                  "C": "background-color:#fef3c7;color:#92400e;font-weight:700",
                  "D": "background-color:#ffe4e6;color:#9f1239;font-weight:700",
                  "E": "background-color:#f3e8ff;color:#6b21a8;font-weight:700"}
        return colors.get(val, "")

    styled = tbl.style.map(color_tier, subset=["Tier"])
    st.dataframe(styled, height=520, use_container_width=True)
    st.caption(f"Showing {len(tbl):,} markets (of {len(DF):,} total)")

    # Download
    csv = view[list(display_cols.keys())].to_csv(index=False)
    st.download_button(
        "⬇️ Download filtered results as CSV",
        data=csv,
        file_name="volta_markets_filtered.csv",
        mime="text/csv",
    )
