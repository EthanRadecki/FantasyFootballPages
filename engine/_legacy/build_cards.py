"""
Generates one 1080x1920 PNG per week (14 total) for the 2026 schedule
reveal video, meant to be dropped directly into Canva's timeline as the
base visual for each week's scene.

Uses schedule_2026.csv for the actual matchups, but overrides the
conference labels with the correct mapping (confirmed by Ethan) since
the CSV's Team_A_Conf/Team_B_Conf columns are inverted for all 14
managers relative to every other conference reference on the site.
That CSV should get fixed at the source too, this override is just so
the video doesn't ship the wrong colors.

Visual language borrows directly from schedule_release.html's palette
(--bone/--ink/--rep/--dem/--gold) and fonts (Anton headlines, IBM Plex
Mono labels) so the video feels like part of the same release, not a
separate product.

Requires Playwright (not wkhtmltoimage):
    pip install playwright
    playwright install chromium
"""

import csv
from pathlib import Path
from playwright.sync_api import sync_playwright

CSV_PATH = "GitHubRepoData/schedule_2026.csv"
OUT_DIR = Path("/home/claude/reveal_cards/out")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Correct conference mapping (schedule_2026.csv has this exactly
# backwards for every manager -- confirmed with Ethan).
REP = {"Anthony Kelly", "Ben Castaldo", "Brandon Hancock", "Carmine Pittelli",
       "Charlie Gorman", "Quin Gegwich", "Ryan McQuaid"}
DEM = {"Ethan Radecki", "Andrew Root", "Max Malich", "Deniz Bileydi",
       "Baylen Slansky", "Cole Maney", "Aidan Quigley"}

RIVALRY_PAIRS = {
    frozenset(["Ethan Radecki", "Andrew Root"]),
    frozenset(["Max Malich", "Deniz Bileydi"]),
    frozenset(["Ryan McQuaid", "Anthony Kelly"]),
    frozenset(["Baylen Slansky", "Brandon Hancock"]),
    frozenset(["Cole Maney", "Carmine Pittelli"]),
    frozenset(["Quin Gegwich", "Ben Castaldo"]),
    frozenset(["Charlie Gorman", "Aidan Quigley"]),
}

WEEK_THEME_TAG = {
    "Standard": None,
    "Rivalry Week": "RIVALRY WEEK",
    "Closest Rivalries Week": "CLOSEST RIVALRIES",
    "Interconference Week": "INTERCONFERENCE",
    "Lopsided History Week": "LOPSIDED HISTORY",
    "Big Game Week": "BIG GAME WEEK",
}

def conf(name):
    return "REP" if name in REP else "DEM"

def load_weeks():
    with open(CSV_PATH, newline="") as f:
        rows = list(csv.DictReader(f))
    weeks = {}
    for r in rows:
        weeks.setdefault(int(r["Week"]), {"type": r["Week_Type"], "games": []})
        weeks[int(r["Week"])]["games"].append((r["Team_A"], r["Team_B"]))
    return weeks

CARD_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@500;700;800&family=IBM+Plex+Mono:wght@600;700&display=swap" rel="stylesheet">
<style>
:root{{
  --bone:#f5f0e8; --ink:#1e1a14; --ink-soft:#6b5f50;
  --rep:#a8434a; --rep-dark:#7c2f34;
  --dem:#3f6583; --dem-dark:#2c495f;
  --gold:#b8892f; --gold-dark:#8f6a1f;
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{width:1080px;height:1920px;background:var(--ink);font-family:'Inter',sans-serif;
     display:flex;align-items:center;justify-content:center;}}
.frame{{width:1080px;height:1920px;background:var(--bone);position:relative;
        display:flex;flex-direction:column;padding:70px 64px;overflow:hidden;}}
.frame::before{{
  content:'';position:absolute;top:-200px;right:-200px;width:600px;height:600px;
  border-radius:50%;background:radial-gradient(circle,rgba(184,137,47,0.16),transparent 70%);
}}
.week-label{{font-family:'IBM Plex Mono',monospace;font-size:30px;font-weight:700;
  letter-spacing:6px;color:var(--ink-soft);text-transform:uppercase;position:relative;z-index:1;}}
.week-num{{font-family:'Anton',sans-serif;font-size:170px;line-height:0.9;color:var(--ink);
  margin-top:6px;position:relative;z-index:1;}}
.theme-tag{{display:inline-block;margin-top:22px;padding:14px 30px;border-radius:100px;
  font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:28px;letter-spacing:3px;
  background:var(--gold);color:var(--bone);position:relative;z-index:1;width:fit-content;}}
.games{{flex:1;display:flex;flex-direction:column;justify-content:center;gap:22px;margin-top:50px;position:relative;z-index:1;}}
.game{{display:flex;align-items:center;background:rgba(30,26,20,0.04);border-radius:24px;
  padding:26px 34px;gap:0;position:relative;}}
.game.rivalry{{background:rgba(184,137,47,0.14);border:5px solid var(--gold);}}
.game.rivalry .tname{{color:var(--gold-dark);}}
.team{{flex:1;display:flex;align-items:center;gap:16px;}}
.team.right{{justify-content:flex-end;text-align:right;}}
.dot{{width:22px;height:22px;border-radius:50%;flex-shrink:0;}}
.dot.REP{{background:var(--rep);}}
.dot.DEM{{background:var(--dem);}}
.tname{{font-family:'Inter',sans-serif;font-weight:800;font-size:34px;color:var(--ink);
  white-space:nowrap;}}
.vs{{font-family:'Anton',sans-serif;font-size:32px;color:var(--ink-soft);padding:0 22px;
  flex-shrink:0;}}
.footer{{font-family:'IBM Plex Mono',monospace;font-size:24px;letter-spacing:3px;
  color:var(--ink-soft);text-align:center;margin-top:36px;position:relative;z-index:1;}}
</style></head>
<body>
<div class="frame">
  <div class="week-label">WEEK</div>
  <div class="week-num">{week_num:02d}</div>
  {theme_html}
  <div class="games">
    {games_html}
  </div>
  <div class="footer">PREACH FANTASY &middot; 2026 SEASON</div>
</div>
</body></html>
"""

GAME_TEMPLATE = """<div class="game{rivalry_class}">
  <div class="team">
    <span class="dot {conf_a}"></span>
    <span class="tname">{team_a}</span>
  </div>
  <div class="vs">VS</div>
  <div class="team right">
    <span class="tname">{team_b}</span>
    <span class="dot {conf_b}"></span>
  </div>
</div>
"""

def build_week_html(week_num, week_data):
    theme = WEEK_THEME_TAG.get(week_data["type"])
    theme_html = f'<div class="theme-tag">{theme}</div>' if theme else ''
    games_html_parts = []
    for team_a, team_b in week_data["games"]:
        is_rivalry = frozenset([team_a, team_b]) in RIVALRY_PAIRS
        games_html_parts.append(GAME_TEMPLATE.format(
            rivalry_class=" rivalry" if is_rivalry else "",
            conf_a=conf(team_a), conf_b=conf(team_b),
            team_a=team_a, team_b=team_b,
        ))
    return CARD_TEMPLATE.format(
        week_num=week_num, theme_html=theme_html,
        games_html="\n".join(games_html_parts),
    )

def main():
    weeks = load_weeks()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        for week_num in sorted(weeks):
            html = build_week_html(week_num, weeks[week_num])
            html_path = OUT_DIR / f"week_{week_num:02d}.html"
            png_path = OUT_DIR / f"week_{week_num:02d}.png"
            html_path.write_text(html)
            page.goto(html_path.resolve().as_uri())
            # Wait for the Google Fonts to actually finish loading so the
            # screenshot doesn't capture a fallback font mid-swap.
            page.evaluate("() => document.fonts.ready")
            page.screenshot(path=str(png_path))
            print(f"Rendered {png_path}")
        browser.close()

if __name__ == "__main__":
    main()
