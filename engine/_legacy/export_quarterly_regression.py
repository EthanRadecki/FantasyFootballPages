import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
import statsmodels.api as sm
import os

# ── Paths ─────────────────────────────────────────────────────────────────────
MATCHUP_PATH = r"C:\Users\radec\OneDrive\Desktop\Projects\Fantasy_Web\static\data\matchup_data.csv"
STATS_PATH   = r"C:\Users\radec\OneDrive\Desktop\Projects\Fantasy_Web\static\data\preach_manager_stats.csv"
OUTPUT_DIR   = r"C:\Users\radec\OneDrive\Desktop\Projects\Portfolio_Images"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Quarter definitions ───────────────────────────────────────────────────────
QUARTERS = {
    'Q1 (Wks 1-3)':   ['Week 1', 'Week 2', 'Week 3'],
    'Q2 (Wks 4-6)':   ['Week 4', 'Week 5', 'Week 6'],
    'Q3 (Wks 7-9)':   ['Week 7', 'Week 8', 'Week 9'],
    'Q4 (Wks 10-13)': ['Week 10', 'Week 11', 'Week 12', 'Week 13'],
}

# ── Load data ─────────────────────────────────────────────────────────────────
matchups = pd.read_csv(MATCHUP_PATH)
stats    = pd.read_csv(STATS_PATH, encoding='latin-1')

matchups = matchups[matchups['Is_Playoff'] == 'No']

EXCLUDE = {'Thomas Sullivan', 'William Serafin'}
matchups = matchups[~matchups['Team_Name'].isin(EXCLUDE)]
stats    = stats[~stats['Manager'].isin(EXCLUDE)]

# ── Build quarterly averages per manager per season ───────────────────────────
records = []
for (manager, season), grp in matchups.groupby(['Team_Name', 'Season_Year']):
    row = {'Manager': manager, 'Season': season}
    for q_label, weeks in QUARTERS.items():
        q_games = grp[grp['Week'].isin(weeks)]
        row[q_label] = q_games['Team_Score'].mean() if len(q_games) > 0 else np.nan
    records.append(row)

quarterly_df = pd.DataFrame(records)

playoff_lookup = stats[['Manager', 'Year', 'Playoffs']].rename(columns={'Year': 'Season'})
merged = quarterly_df.merge(playoff_lookup, on=['Manager', 'Season'], how='inner')
merged = merged.dropna()

# ── Logistic Regression via statsmodels (for p-values) ───────────────────────
q_cols = list(QUARTERS.keys())
X = merged[q_cols].values
y = merged['Playoffs'].values

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
X_sm = sm.add_constant(X_scaled)

model  = sm.Logit(y, X_sm)
result = model.fit(disp=0)

coefficients = result.params[1:]   # exclude intercept
p_values     = result.pvalues[1:]
odds_ratios  = np.exp(coefficients)
auc          = roc_auc_score(y, result.predict(X_sm))

print("\nQuarterly Logistic Regression Results:")
print(f"Model AUC: {auc:.3f}")
for q, coef, pval, oddr in zip(q_cols, coefficients, p_values, odds_ratios):
    print(f"  {q}: coef={coef:.3f}, p={pval:.3f}, odds ratio={oddr:.3f}")

# ── Correlations ──────────────────────────────────────────────────────────────
correlations = [merged[q].corr(merged['Playoffs']) for q in q_cols]

# ── Color gradient: red (low) → bone (mid) → green (high) ────────────────────
def bar_color(vals, alpha=0.8):
    """Light green (low) → dark green (high), never red for positive values"""
    mn, mx = min(vals), max(vals)
    colors = []
    for v in vals:
        p = (v - mn) / (mx - mn) if mx != mn else 0.5
        # Light green rgba(180,220,180) → dark green rgba(40,120,70)
        r = int(180 + (40  - 180) * p)
        g = int(220 + (120 - 220) * p)
        b = int(180 + (70  - 180) * p)
        colors.append(f'rgba({r},{g},{b},{alpha})')
    return colors

# ── Build figure ──────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=1, cols=2,
    horizontal_spacing=0.14,
    subplot_titles=['', '']   # handled via annotations
)

# Chart 1: Coefficients + p-values
fig.add_trace(go.Bar(
    x=q_cols,
    y=coefficients,
    marker=dict(
        color=bar_color(coefficients, 0.8),
        line=dict(color=bar_color(coefficients, 1.0), width=1.5)
    ),
    text=[
        f"{c:+.3f}{'***' if p<0.01 else '**' if p<0.05 else '*' if p<0.1 else ''}  p={p:.3f}"
        for c, p in zip(coefficients, p_values)
    ],
    textposition='outside',
    textangle=0,
    textfont=dict(color='#1e1a14', size=12),
    showlegend=False,
), row=1, col=1)

fig.add_hline(y=0, line=dict(color='#6b5f50', width=1.5, dash='dash'), row=1, col=1)

# Chart 2: Correlations
fig.add_trace(go.Bar(
    x=q_cols,
    y=correlations,
    marker=dict(
        color=bar_color(correlations, 0.8),
        line=dict(color=bar_color(correlations, 1.0), width=1.5)
    ),
    text=[f"{v:+.3f}" for v in correlations],
    textposition='outside',
    textfont=dict(color='#1e1a14', size=12),
    showlegend=False,
), row=1, col=2)

fig.add_hline(y=0, line=dict(color='#6b5f50', width=1.5, dash='dash'), row=1, col=2)

AXIS_STYLE = dict(
    gridcolor='rgba(200,185,165,0.3)',
    linecolor='rgba(200,185,165,0.5)',
    tickfont=dict(color='#6b5f50', size=13),
    title_font=dict(color='#6b5f50', size=14),
    zerolinecolor='rgba(200,185,165,0.5)',
)

fig.update_layout(
    plot_bgcolor='rgba(255,255,255,0.0)',
    paper_bgcolor='#f5f0e8',
    font=dict(family='Segoe UI, system-ui, sans-serif', color='#1e1a14', size=14),
    title=dict(
        text='Which Quarter Matters Most for Playoffs? — Preach Fantasy',
        font=dict(size=20, color='#1e1a14', family='Segoe UI, system-ui, sans-serif'),
        x=0.5, xanchor='center', y=0.97
    ),
    margin=dict(l=70, r=50, t=160, b=80),
    annotations=[
        dict(text=f'Model AUC: {auc:.2f}  |  * p<0.1  ** p<0.05  *** p<0.01',
             x=0.5, y=1.17, xref='paper', yref='paper', showarrow=False,
             font=dict(size=12, color='#6b5f50')),
        dict(text='Logistic Regression Coefficients',
             x=0.225, y=1.08, xref='paper', yref='paper', showarrow=False,
             xanchor='center',
             font=dict(size=14, color='#1e1a14')),
        dict(text='Pearson Correlation with Playoff Appearance',
             x=0.775, y=1.08, xref='paper', yref='paper', showarrow=False,
             xanchor='center',
             font=dict(size=14, color='#1e1a14')),
    ]
)

fig.update_xaxes(**AXIS_STYLE)
fig.update_yaxes(**AXIS_STYLE)
fig.update_yaxes(title_text='Coefficient', range=[0, 1.05], row=1, col=1)
fig.update_yaxes(title_text='Pearson Correlation', range=[0, 0.52], row=1, col=2)

# ── Export ────────────────────────────────────────────────────────────────────
fig.write_image(
    os.path.join(OUTPUT_DIR, 'preach_quarterly_regression.png'),
    width=1200, height=620, scale=2
)
print(f"\nSaved -> preach_quarterly_regression.png")