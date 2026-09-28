import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

# ── Paths ─────────────────────────────────────────────────────────────────────
MATCHUP_PATH = r"C:\Users\radec\OneDrive\Desktop\Projects\Fantasy_Web\static\data\matchup_data.csv"
OUTPUT_DIR   = r"C:\Users\radec\OneDrive\Desktop\Projects\Portfolio_Images"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Load & filter ─────────────────────────────────────────────────────────────
df = pd.read_csv(MATCHUP_PATH)

# Regular season only
df = df[df['Week'].str.contains(r'^Week \d+', na=False, regex=True)].copy()

# Exclude one-season managers
EXCLUDE = {'Thomas Sullivan', 'William Serafin'}
df = df[~df['Team_Name'].isin(EXCLUDE)]

# Remove bad scores
df = df[df['Team_Score'] > 0]

# ── Calculate league median per week/season ───────────────────────────────────
medians = (
    df.groupby(['Season_Year', 'Week'])['Team_Score']
    .median()
    .reset_index()
    .rename(columns={'Team_Score': 'League_Median'})
)

df = df.merge(medians, on=['Season_Year', 'Week'], how='left')

# ── Predicted win = scored above median that week ─────────────────────────────
df['Predicted_Win'] = (df['Team_Score'] > df['League_Median']).astype(int)
df['Actual_Win']    = (df['Outcome'] == 'Win').astype(int)
df['Luck']          = df['Actual_Win'] - df['Predicted_Win']

# ── Aggregate all-time luck per manager ───────────────────────────────────────
luck_summary = (
    df.groupby('Team_Name')
    .agg(
        Total_Luck=('Luck', 'sum'),
        Actual_Wins=('Actual_Win', 'sum'),
        Predicted_Wins=('Predicted_Win', 'sum'),
        Games=('Actual_Win', 'count')
    )
    .reset_index()
)

# Shorten names for display
def short_name(name):
    parts = name.split()
    return f"{parts[0]} {parts[-1][0]}." if len(parts) > 1 else name

luck_summary['Display_Name'] = luck_summary['Team_Name'].apply(short_name)

# Sort by luck score (most lucky at top)
luck_summary = luck_summary.sort_values('Total_Luck', ascending=True)

# ── Colors ────────────────────────────────────────────────────────────────────
def bar_color(val, alpha=0.85):
    if val > 0:
        # Scale green intensity
        intensity = min(abs(val) / 8, 1.0)
        r = int(180 - (180 - 40)  * intensity)
        g = int(220 - (220 - 130) * intensity)
        b = int(180 - (180 - 60)  * intensity)
    elif val < 0:
        # Scale red intensity
        intensity = min(abs(val) / 8, 1.0)
        r = int(220 - (220 - 150) * intensity)
        g = int(180 - (180 - 50)  * intensity)
        b = int(180 - (180 - 50)  * intensity)
    else:
        r, g, b = 200, 190, 175
    return f'rgba({r},{g},{b},{alpha})'

colors       = [bar_color(v, 0.85) for v in luck_summary['Total_Luck']]
border_colors = [bar_color(v, 1.0)  for v in luck_summary['Total_Luck']]

# ── Build figure ──────────────────────────────────────────────────────────────
fig = go.Figure()

fig.add_trace(go.Bar(
    x=luck_summary['Total_Luck'],
    y=luck_summary['Display_Name'],
    orientation='h',
    marker=dict(
        color=colors,
        line=dict(color=border_colors, width=1.5)
    ),
    text=[
        f"{'+' if v > 0 else ''}{v} wins  ({row.Actual_Wins}W actual vs {row.Predicted_Wins}W expected)"
        for v, (_, row) in zip(luck_summary['Total_Luck'], luck_summary.iterrows())
    ],
    textposition='outside',
    textfont=dict(color='#1e1a14', size=11),
    hovertemplate=(
        '<b>%{y}</b><br>'
        'Luck: %{x:+d} wins<br>'
        'Actual: %{customdata[0]}W<br>'
        'Expected: %{customdata[1]}W<br>'
        'Games: %{customdata[2]}<extra></extra>'
    ),
    customdata=luck_summary[['Actual_Wins', 'Predicted_Wins', 'Games']].values,
    showlegend=False,
))

fig.add_vline(
    x=0,
    line=dict(color='#6b5f50', width=2, dash='dash'),
)

fig.update_layout(
    plot_bgcolor='rgba(255,255,255,0.0)',
    paper_bgcolor='#f5f0e8',
    font=dict(family='Segoe UI, system-ui, sans-serif', color='#1e1a14', size=13),
    title=dict(
        text='All-Time Schedule Luck — Preach Fantasy (2020–2025)',
        font=dict(size=20, color='#1e1a14', family='Segoe UI, system-ui, sans-serif'),
        x=0.5, xanchor='center', y=0.97
    ),
    xaxis=dict(
        title='Gifted Wins (vs Expected)',
        title_font=dict(color='#6b5f50', size=13),
        gridcolor='rgba(200,185,165,0.3)',
        linecolor='rgba(200,185,165,0.5)',
        tickfont=dict(color='#6b5f50', size=12),
        zerolinecolor='rgba(200,185,165,0.5)',
        range=[
            min(luck_summary['Total_Luck']) - 5,
            max(luck_summary['Total_Luck']) + 5
        ]
    ),
    yaxis=dict(
        gridcolor='rgba(200,185,165,0.3)',
        linecolor='rgba(200,185,165,0.5)',
        tickfont=dict(color='#1e1a14', size=13),
    ),
    margin=dict(l=90, r=20, t=80, b=60),
    height=600,
)

# Subtitle
fig.add_annotation(
    text='Luck = Actual Wins − Expected Wins  |  Expected wins based on weekly score vs league median',
    x=0.5, y=1.04, xref='paper', yref='paper',
    showarrow=False, xanchor='center',
    font=dict(size=11, color='#6b5f50')
)

# ── Export ────────────────────────────────────────────────────────────────────
fig.write_image(
    os.path.join(OUTPUT_DIR, 'preach_luck_analysis.png'),
    width=1400, height=600, scale=2
)
print("Saved → preach_luck_analysis.png")