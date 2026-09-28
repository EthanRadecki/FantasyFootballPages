import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch
from sklearn.preprocessing import StandardScaler
from scipy.spatial.distance import euclidean
import os
import sys

# ── Paths ─────────────────────────────────────────────────────────────────────
MATCHUP_PATH  = r"C:\Users\radec\OneDrive\Desktop\Projects\Fantasy_Web\static\data\matchup_data.csv"
STATS_PATH    = r"C:\Users\radec\OneDrive\Desktop\Projects\Fantasy_Web\static\data\preach_manager_stats.csv"
OUTPUT_DIR    = r"C:\Users\radec\OneDrive\Desktop\Projects\Portfolio_Images"
OUTPUT_FILE   = os.path.join(OUTPUT_DIR, "preach_similarity_grid.png")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Add Fantasy_Web to path so we can import the analyzer
sys.path.insert(0, r"C:\Users\radec\OneDrive\Desktop\Projects\Fantasy_Web")

# ── Re-use existing analyzer logic ───────────────────────────────────────────
from historical_similarity import HistoricalSimilarityAnalysis

analyzer = HistoricalSimilarityAnalysis(
    matchup_data_path=MATCHUP_PATH,
    manager_stats_path=STATS_PATH,
    current_season=2025
)

playoff_teams_2025 = [
    'Ben Castaldo',
    'Cole Maney',
    'Ryan P McQuaid',
    'Baylen Slansky',
    'Carmine Pittelli Jr.',
    'Ethan Radecki',
    'Anthony Kelly',
    'Charlie Gorman',
]

custom_weights = {
    'Late_Season_PF/G': 2.0,
    'PF/G': 1.7,
    'Win%': 1.4,
    'LR_zscore': 1.1,
    'Dominance_Score': 0.9,
    'Draft_Slot': 0.6,
    'Point_Differential': 0.4,
}

results = analyzer.analyze_playoff_teams(playoff_teams_2025, feature_weights=custom_weights)

# ── Palette ───────────────────────────────────────────────────────────────────
BONE       = '#f5f0e8'
DARK       = '#1e1a14'
MID        = '#6b5f50'
BORDER     = 'rgba(200,185,165,0.6)'
SLATE      = '#4a7fa8'
TERRA      = '#c0623a'
GREEN      = '#4a8c6e'
CARD_BG    = '#ece7de'
MATCH_COLORS = ['#4a7fa8', '#6b5f50', '#8a7a6a']  # rank 1,2,3

def result_text_color(sim_team):
    if sim_team['Champ_W'] == 1:
        return 'CHAMPION', '#c8a951'
    elif sim_team['Champ_App'] == 1:
        return 'Runner-Up', MID
    elif sim_team['Playoffs'] == 1:
        elim = sim_team.get('Elimination_Round')
        year = int(sim_team['Year'])
        if pd.notna(elim):
            elim = int(elim)
            if year == 2020:
                rnames = {1:'Rd of 14', 2:'Quarters', 3:'Semis', 4:'Finals'}
            else:
                rnames = {1:'Quarters', 2:'Semis', 3:'Finals'}
            return f"Lost in {rnames.get(elim, f'Rd {elim}')}", TERRA
        return 'Made Playoffs', GREEN
    return 'Missed Playoffs', TERRA

def draw_team_card(ax, manager, data, seed):
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    # Card background
    bg = FancyBboxPatch((0.01, 0.01), 0.98, 0.98,
                        boxstyle="round,pad=0.02",
                        facecolor=CARD_BG, edgecolor='#c8b89a',
                        linewidth=1.5, zorder=0)
    ax.add_patch(bg)

    # ── Header ────────────────────────────────────────────────────────────────
    ax.text(0.05, 0.955, f"#{seed}", fontsize=12, fontweight='bold',
            color=SLATE, va='top', ha='left')
    short = manager.replace(' Jr.', '').replace('Ryan P ', 'Ryan ')
    ax.text(0.17, 0.955, short, fontsize=14, fontweight='bold',
            color=DARK, va='top', ha='left')

    # Current season stats row
    cf = data['current_features']
    stats_str = f"W%: {cf['Win%']:.2f}   PF/G: {cf['PF/G']:.1f}   Late Season: {cf['Late_Season_PF/G']:.1f}"
    ax.text(0.17, 0.895, stats_str, fontsize=9, color=MID, va='top', ha='left',
            fontfamily='monospace')

    # Header divider
    ax.axhline(y=0.845, xmin=0.03, xmax=0.97, color='#b8a890', linewidth=1.0)

    # ── Three match blocks ────────────────────────────────────────────────────
    # Each block occupies 1/3 of the remaining space (0.0 to 0.84)
    # Block tops at: 0.82, 0.54, 0.26  height per block ~0.26
    block_tops  = [0.825, 0.545, 0.265]
    block_height = 0.24
    similar = data['similar_teams']

    for i, (_, sim) in enumerate(similar.iterrows()):
        top = block_tops[i]
        bot = top - block_height
        mid_y = (top + bot) / 2
        color = MATCH_COLORS[i]

        # Rank badge — vertically centred in block
        badge = FancyBboxPatch((0.03, mid_y - 0.055), 0.10, 0.11,
                               boxstyle="round,pad=0.01",
                               facecolor=color, edgecolor='none', zorder=1)
        ax.add_patch(badge)
        ax.text(0.08, mid_y, f'#{i+1}', fontsize=10, fontweight='bold',
                color='white', va='center', ha='center', zorder=2)

        # Team name + year
        ax.text(0.17, top - 0.010, f"{sim['Team']}  ({int(sim['Year'])})",
                fontsize=10, fontweight='bold', color=DARK, va='top', ha='left')

        # Manager name
        ax.text(0.17, top - 0.065, sim['Manager'],
                fontsize=8.5, color=MID, va='top', ha='left', style='italic')

        # Stats line
        s = f"W%: {sim['Win%']:.2f}   PF/G: {sim['PF/G']:.1f}   Late: {sim['Late_Season_PF/G']:.1f}"
        ax.text(0.17, top - 0.118, s,
                fontsize=8, color=DARK, va='top', ha='left', fontfamily='monospace')

        # Result
        rtxt, rcol = result_text_color(sim)
        ax.text(0.17, top - 0.170, rtxt,
                fontsize=9, color=rcol, va='top', ha='left', fontweight='bold')

        # Similarity score — right aligned, vertically centred
        ax.text(0.96, mid_y + 0.02, f"{sim['similarity_score']:.0f}%",
                fontsize=14, fontweight='bold', color=color, va='center', ha='right')
        ax.text(0.96, mid_y - 0.04, 'match',
                fontsize=8, color=MID, va='center', ha='right')

        # Divider below block (not after last)
        if i < 2:
            ax.axhline(y=bot + 0.01, xmin=0.03, xmax=0.97,
                       color='#c8b89a', linewidth=0.7, linestyle='--')

# ── Build figure ──────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(24, 14), facecolor=BONE)
fig.suptitle('Historical Team Similarity Analysis — Preach Fantasy 2025 Playoffs',
             fontsize=20, fontweight='bold', color=DARK, y=0.97,
             fontfamily='DejaVu Sans')
fig.text(0.5, 0.935, 'Each card shows the 3 most statistically similar teams from league history, ranked by weighted Euclidean distance across 7 performance features.',
         ha='center', fontsize=10, color=MID, fontfamily='DejaVu Sans')

gs = gridspec.GridSpec(2, 4, figure=fig,
                       hspace=0.12, wspace=0.06,
                       left=0.02, right=0.98,
                       top=0.91, bottom=0.03)

seeds = [1, 2, 3, 4, 5, 6, 7, 8]
managers_ordered = [
    'Ben Castaldo', 'Cole Maney', 'Ryan P McQuaid', 'Baylen Slansky',
    'Carmine Pittelli Jr.', 'Ethan Radecki', 'Anthony Kelly', 'Charlie Gorman'
]

for idx, manager in enumerate(managers_ordered):
    row, col = divmod(idx, 4)
    ax = fig.add_subplot(gs[row, col])
    if manager in results:
        draw_team_card(ax, manager, results[manager], seeds[idx])
    else:
        ax.axis('off')
        ax.text(0.5, 0.5, f'No data\n{manager}', ha='center', va='center', color=MID)

# ── Export ────────────────────────────────────────────────────────────────────
fig.savefig(OUTPUT_FILE, dpi=200, bbox_inches='tight',
            facecolor=BONE, edgecolor='none')
plt.close(fig)
print(f"Saved → {OUTPUT_FILE}")