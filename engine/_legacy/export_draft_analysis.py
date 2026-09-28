import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

# ── Paths ─────────────────────────────────────────────────────────────────────
CSV_PATH   = r"C:\Users\radec\OneDrive\Desktop\Projects\Fantasy_Web\static\data\preach_manager_stats.csv"
OUTPUT_DIR = r"C:\Users\radec\OneDrive\Desktop\Projects\Portfolio_Images"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Load & process (mirrors Flask route logic) ────────────────────────────────
df = pd.read_csv(CSV_PATH, encoding='latin-1')
df = df[df['Draft_Slot'] <= 14].copy()

manager_avg = df.groupby('Manager')['Dominance_Score'].mean().to_dict()
df['Manager_Quality'] = df['Manager'].map(manager_avg)

draft_stats = []
for slot in range(1, 15):
    slot_data = df[df['Draft_Slot'] == slot]
    if len(slot_data) == 0:
        continue
    playoff_rate     = slot_data['Playoffs'].mean() * 100
    avg_dominance    = slot_data['Dominance_Score'].mean()
    expected         = slot_data['Manager_Quality'].mean()
    overperformance  = avg_dominance - expected
    draft_stats.append({
        'slot':           slot,
        'playoff_rate':   round(playoff_rate, 1),
        'overperformance': round(overperformance, 2),
    })

slots        = [d['slot'] for d in draft_stats]
playoff_rates = [d['playoff_rate'] for d in draft_stats]
overperfs    = [d['overperformance'] for d in draft_stats]

# ── Shared layout base ────────────────────────────────────────────────────────
TITLE_STYLE = dict(
    font=dict(size=16, color='#1e1a14', family='Segoe UI, system-ui, sans-serif'),
    x=0.5,
    xanchor='center'
)

LAYOUT_BASE = dict(
    plot_bgcolor='rgba(255,255,255,0.0)',
    paper_bgcolor='#f5f0e8',
    font=dict(family='Segoe UI, system-ui, sans-serif', color='#1e1a14', size=13),
    xaxis=dict(
        gridcolor='rgba(200,185,165,0.3)',
        linecolor='rgba(200,185,165,0.5)',
        tickfont=dict(color='#6b5f50'),
        title_font=dict(color='#6b5f50'),
    ),
    yaxis=dict(
        gridcolor='rgba(200,185,165,0.3)',
        linecolor='rgba(200,185,165,0.5)',
        tickfont=dict(color='#6b5f50'),
        title_font=dict(color='#6b5f50'),
    ),
    margin=dict(l=60, r=40, t=70, b=60),
)

# ── Chart 1: Playoff Rate by Draft Slot ──────────────────────────────────────
def gradient_color(val, min_val, max_val, alpha=0.75):
    """Red (bad/low) → bone white (mid) → green (good/high)"""
    p = (val - min_val) / (max_val - min_val) if max_val != min_val else 0.5
    if p <= 0.5:
        t = p / 0.5
        r = int(192 + (245 - 192) * t)
        g = int(58  + (240 - 58)  * t)
        b = int(58  + (232 - 58)  * t)
    else:
        t = (p - 0.5) / 0.5
        r = int(245 + (74  - 245) * t)
        g = int(240 + (168 - 240) * t)
        b = int(232 + (58  - 232) * t)
    return f'rgba({r},{g},{b},{alpha})'

bar_colors    = [gradient_color(r, min(playoff_rates), max(playoff_rates), 0.75) for r in playoff_rates]
border_colors = [gradient_color(r, min(playoff_rates), max(playoff_rates), 1.0)  for r in playoff_rates]

fig1 = go.Figure(go.Bar(
    x=slots,
    y=playoff_rates,
    marker=dict(color=bar_colors, line=dict(color=border_colors, width=1.5)),
    text=[f"{r}%" for r in playoff_rates],
    textposition='outside',
    textfont=dict(color='#1e1a14', size=11),
))
fig1.update_layout(
    plot_bgcolor='rgba(255,255,255,0.0)',
    paper_bgcolor='#f5f0e8',
    font=dict(family='Segoe UI, system-ui, sans-serif', color='#1e1a14', size=13),
    title=dict(text="Playoff Rate by Draft Slot — Preach Fantasy", **TITLE_STYLE),
    xaxis=dict(title='Draft Slot', dtick=1, gridcolor='rgba(200,185,165,0.3)', linecolor='rgba(200,185,165,0.5)', tickfont=dict(color='#6b5f50'), title_font=dict(color='#6b5f50')),
    yaxis=dict(title='Playoff Rate (%)', range=[0, 110], gridcolor='rgba(200,185,165,0.3)', linecolor='rgba(200,185,165,0.5)', tickfont=dict(color='#6b5f50'), title_font=dict(color='#6b5f50')),
    margin=dict(l=60, r=40, t=70, b=60),
)
fig1.write_image(
    os.path.join(OUTPUT_DIR, "preach_draft_playoff_rate.png"),
    width=1200, height=500, scale=2
)
print("Saved → preach_draft_playoff_rate.png")

# ── Chart 2: Manager-Adjusted Performance ────────────────────────────────────
bar_colors2   = [gradient_color(v, min(overperfs), max(overperfs), 0.75) for v in overperfs]
border_colors2 = [gradient_color(v, min(overperfs), max(overperfs), 1.0)  for v in overperfs]

fig2 = go.Figure(go.Bar(
    x=slots,
    y=overperfs,
    marker=dict(color=bar_colors2, line=dict(color=border_colors2, width=1.5)),
    text=[f"{v:+.2f}" for v in overperfs],
    textposition='outside',
    textfont=dict(color='#1e1a14', size=11),
))
fig2.add_hline(
    y=0,
    line=dict(color='#6b5f50', width=1.5, dash='dash'),
)
fig2.update_layout(
    plot_bgcolor='rgba(255,255,255,0.0)',
    paper_bgcolor='#f5f0e8',
    font=dict(family='Segoe UI, system-ui, sans-serif', color='#1e1a14', size=13),
    title=dict(text="Manager-Adjusted Performance by Draft Slot — Preach Fantasy", **TITLE_STYLE),
    xaxis=dict(title='Draft Slot', dtick=1, gridcolor='rgba(200,185,165,0.3)', linecolor='rgba(200,185,165,0.5)', tickfont=dict(color='#6b5f50'), title_font=dict(color='#6b5f50')),
    yaxis=dict(title='Dominance Score Over/Under Expected', gridcolor='rgba(200,185,165,0.3)', linecolor='rgba(200,185,165,0.5)', tickfont=dict(color='#6b5f50'), title_font=dict(color='#6b5f50')),
    margin=dict(l=60, r=40, t=70, b=60),
)
fig2.write_image(
    os.path.join(OUTPUT_DIR, "preach_draft_adjusted_performance.png"),
    width=1200, height=500, scale=2
)
print("Saved → preach_draft_adjusted_performance.png")