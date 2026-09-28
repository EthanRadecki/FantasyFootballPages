import pandas as pd
import plotly.graph_objects as go
import os

# ── Paths ────────────────────────────────────────────────────────────────────
CSV_PATH    = r"C:\Users\radec\OneDrive\Desktop\Projects\Fantasy_Web\static\data\matchup_data.csv"
OUTPUT_DIR  = r"C:\Users\radec\OneDrive\Desktop\Projects\Portfolio_Images"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "preach_h2h_matrix.png")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Load & filter ─────────────────────────────────────────────────────────────
df = pd.read_csv(CSV_PATH)

# Keep only actual playoff games (Is_Playoff == Yes) + all regular season
# Exclude consolation games: keep rows where Is_Playoff == 'No' (reg season)
# or Is_Playoff == 'Yes' (real playoffs)
df = df[df['Is_Playoff'].isin(['Yes', 'No'])]

# Remove junk scores (forfeits/byes with 0 or negative scores)
df = df[(df['Team_Score'] > 0) & (df['Opponent_Score'] > 0)]

# ── Build H2H records ─────────────────────────────────────────────────────────
# Only use one row per matchup (where Team is the row team)
records = {}  # (team, opponent) -> [wins, total]

for _, row in df.iterrows():
    team = row['Team_Name']
    opp  = row['Opponent_Name']
    win  = 1 if row['Outcome'] == 'Win' else 0
    key  = (team, opp)
    if key not in records:
        records[key] = [0, 0]
    records[key][0] += win
    records[key][1] += 1

# ── Get sorted manager list (exclude one-season managers) ────────────────────
EXCLUDE = {'Thomas Sullivan', 'William Serafin'}
managers = sorted([m for m in df['Team_Name'].unique() if m not in EXCLUDE])

# ── Build matrix arrays ───────────────────────────────────────────────────────
n = len(managers)
z        = []   # win %  (None for self)
text     = []   # display text in cell
hover   = []   # hover text

for row_mgr in managers:
    z_row, t_row, h_row = [], [], []
    for col_mgr in managers:
        if row_mgr == col_mgr:
            z_row.append(None)
            t_row.append("")
            h_row.append("")
        else:
            key = (row_mgr, col_mgr)
            if key in records and records[key][1] > 0:
                wins  = records[key][0]
                total = records[key][1]
                pct   = wins / total
                z_row.append(pct)
                t_row.append(f"{wins}-{total - wins}")
                h_row.append(
                    f"<b>{row_mgr}</b> vs {col_mgr}<br>"
                    f"Record: {wins}W – {total - wins}L<br>"
                    f"Win %: {pct:.0%}"
                )
            else:
                z_row.append(None)
                t_row.append("—")
                h_row.append(f"No matchups: {row_mgr} vs {col_mgr}")
    z.append(z_row)
    text.append(t_row)
    hover.append(h_row)

# ── Shorten names for axis labels ─────────────────────────────────────────────
def short(name):
    parts = name.split()
    return f"{parts[0]} {parts[-1][0]}." if len(parts) > 1 else name

short_names = [short(m) for m in managers]

# ── Build figure ──────────────────────────────────────────────────────────────
# Diagonal overlay — self cells in neutral charcoal
diag_z = [[None]*n for _ in range(n)]
diag_text = [['']*n for _ in range(n)]
for i in range(n):
    diag_z[i][i] = 1
    diag_text[i][i] = '✕'

fig = go.Figure()
fig.add_trace(go.Heatmap(
    z=z,
    x=short_names,
    y=short_names,
    text=text,
    hovertext=hover,
    hovertemplate="%{hovertext}<extra></extra>",
    texttemplate="%{text}",
    textfont=dict(size=10, color='#1e1a14'),
    colorscale=[
        [0,   'rgba(192,58,58,0.85)'],   # red    — low win %
        [0.5, 'rgba(245,240,232,1)'],    # bone white — even
        [1,   'rgba(74,168,90,0.85)'],   # green  — high win %
    ],
    zmin=0,
    zmax=1,
    zmid=0.5,
    colorbar=dict(
        title=dict(text="Win %", font=dict(color='#1e1a14', size=12)),
        tickformat=".0%",
        tickfont=dict(color='#6b5f50'),
        outlinecolor='rgba(200,185,165,0.5)',
        outlinewidth=1,
    ),
    xgap=2,
    ygap=2,
))

# Diagonal overlay trace
fig.add_trace(go.Heatmap(
    z=diag_z,
    x=short_names,
    y=short_names,
    text=diag_text,
    texttemplate="%{text}",
    textfont=dict(size=12, color='rgba(200,185,165,0.7)'),
    colorscale=[[0, '#3a3530'], [1, '#3a3530']],  # flat charcoal
    showscale=False,
    hoverinfo='skip',
    xgap=2,
    ygap=2,
))

fig.update_layout(
    title=dict(
        text="All-Time Head-to-Head Matrix — Preach Fantasy (2020–2025)",
        font=dict(size=16, color='#1e1a14', family='Segoe UI, system-ui, sans-serif'),
        x=0.5,
        xanchor='center'
    ),
    plot_bgcolor='rgba(255,255,255,0.0)',
    paper_bgcolor='#f5f0e8',
    font=dict(family='Segoe UI, system-ui, sans-serif', color='#1e1a14', size=12),
    xaxis=dict(
        tickfont=dict(color='#6b5f50', size=10),
        tickangle=-35,
        linecolor='rgba(200,185,165,0.5)',
        side='bottom',
    ),
    yaxis=dict(
        tickfont=dict(color='#6b5f50', size=10),
        linecolor='rgba(200,185,165,0.5)',
        autorange='reversed',
    ),
    margin=dict(l=110, r=80, t=70, b=110),
    width=1200,
    height=900,
)

# ── Export ────────────────────────────────────────────────────────────────────
fig.write_image(OUTPUT_FILE, width=1200, height=900, scale=2)
print(f"Saved → {OUTPUT_FILE}")