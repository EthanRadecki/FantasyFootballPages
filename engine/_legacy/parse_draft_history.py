import pandas as pd
import re

# =============================================================================
# Preach Fantasy — Draft History Parser
# Seasons: 2020-2025 | All seasons included
# =============================================================================
# Outputs:
#   draft_history.csv              — skill positions only (RB/WR/TE/QB)
#   draft_history_all_positions.csv— all positions including K and D/ST
# =============================================================================

# ── Draft slot lookup — source of truth for all seasons ─────────────────────
# Format: slot_number -> {season: manager_name}
# 2020 is 15-team; 2021-2025 are 14-team

SLOT_LOOKUP = {
    1:  {2020: "Anthony Kelly",      2021: "Andrew Root",       2022: "Charlie Gorman",    2023: "Ryan McQuaid",      2024: "Andrew Root",      2025: "Ryan McQuaid"},
    2:  {2020: "Andrew Root",        2021: "Deniz Bileydi",     2022: "Ryan McQuaid",      2023: "Ethan Radecki",     2024: "Quin Gegwich",     2025: "Andrew Root"},
    3:  {2020: "Charlie Gorman",     2021: "Ben Castaldo",      2022: "Carmine Pittelli",  2023: "Baylen Slansky",    2024: "Ben Castaldo",     2025: "Deniz Bileydi"},
    4:  {2020: "Baylen Slansky",     2021: "Charlie Gorman",    2022: "Quin Gegwich",      2023: "Quin Gegwich",      2024: "Anthony Kelly",    2025: "Ben Castaldo"},
    5:  {2020: "Brandon Hancock",    2021: "Baylen Slansky",    2022: "Ethan Radecki",     2023: "Aidan Quigley",     2024: "Deniz Bileydi",    2025: "Brandon Hancock"},
    6:  {2020: "Cole Maney",         2021: "Ryan McQuaid",      2022: "Cole Maney",        2023: "Ben Castaldo",      2024: "Baylen Slansky",   2025: "Ethan Radecki"},
    7:  {2020: "Ryan McQuaid",       2021: "Cole Maney",        2022: "Brandon Hancock",   2023: "Charlie Gorman",    2024: "Cole Maney",       2025: "Aidan Quigley"},
    8:  {2020: "Max Malich",         2021: "Ethan Radecki",     2022: "Anthony Kelly",     2023: "Anthony Kelly",     2024: "Brandon Hancock",  2025: "Baylen Slansky"},
    9:  {2020: "Carmine Pittelli",   2021: "Carmine Pittelli",  2022: "Aidan Quigley",     2023: "Max Malich",        2024: "Carmine Pittelli", 2025: "Anthony Kelly"},
    10: {2020: "Ethan Radecki",      2021: "Aidan Quigley",     2022: "Baylen Slansky",    2023: "Deniz Bileydi",     2024: "Charlie Gorman",   2025: "Cole Maney"},
    11: {2020: "Quin Gegwich",       2021: "Max Malich",        2022: "Max Malich",        2023: "Cole Maney",        2024: "Ethan Radecki",    2025: "Charlie Gorman"},
    12: {2020: "Deniz Bileydi",      2021: "Brandon Hancock",   2022: "Ben Castaldo",      2023: "Brandon Hancock",   2024: "Max Malich",       2025: "Max Malich"},
    13: {2020: "Ben Castaldo",       2021: "Quin Gegwich",      2022: "Deniz Bileydi",     2023: "Carmine Pittelli",  2024: "Ryan McQuaid",     2025: "Carmine Pittelli"},
    14: {2020: "Thomas Sullivan",    2021: "Anthony Kelly",     2022: "Andrew Root",       2023: "Andrew Root",       2024: "Aidan Quigley",    2025: "Quin Gegwich"},
    15: {2020: "William Serafin"},   # slot 15 only exists in 2020 (15-team league)
}

# Build reverse lookup: season -> {fantasy_team_name -> draft_slot}
# We'll use this to assign slots from team names in the raw data

# ── Fantasy team name → manager name per season ──────────────────────────────
# Used to identify which manager owns which fantasy team that season

TEAM_TO_MANAGER = {
    2020: {
        "Team Kelly":                   "Anthony Kelly",
        "N.Y. Routensss":               "Andrew Root",
        "San Giacomos Frannys Fanny":   "Charlie Gorman",
        "Goodwill Hunting V2":          "Baylen Slansky",
        "Fourth Reich \u2720":          "Brandon Hancock",
        "STATION GRITS":                "Cole Maney",
        "New York Jets":                "Ryan McQuaid",
        ". Can you Digg it":            "Max Malich",
        "North Korea Dingus MAGA":      "Carmine Pittelli",
        "Slant Boy v2":                 "Ethan Radecki",
        "Hot Rod":                      "Quin Gegwich",
        "Chicago We got um":            "Deniz Bileydi",
        "Jungle Le Monke":              "Ben Castaldo",
        "The South Will Rise":          "Thomas Sullivan",
        "Team Serafin":                 "William Serafin",
    },
    # 2021: offline draft — order is fixed below, team names map to corrected slots
    2021: {
        "N.Y. Routensss":               "Andrew Root",
        "Chicago We got um":            "Deniz Bileydi",
        "I shoot blanks n shit":        "Ben Castaldo",
        "San Giacomos Frannys Fanny":   "Charlie Gorman",
        "AND I...AM ...IRON MAN":       "Baylen Slansky",
        "Darnold Trump":                "Ryan McQuaid",
        "Nicholas Cruz's":              "Cole Maney",
        "Kittle Me This":               "Ethan Radecki",
        "Fresh Prince Of Helaire":      "Carmine Pittelli",
        "Tony Fkn Romo":                "Aidan Quigley",
        ". Hockenshit":                 "Max Malich",
        "The Minutemen \ufe3b\u30c7\u2550\u4e00": "Brandon Hancock",
        "Mixon a Half Ch\u00fabb":       "Quin Gegwich",
        "Mixon a Half Ch\xfabb":        "Quin Gegwich",
        "Mixon a Half Chûbb":           "Quin Gegwich",
        "Zay Sutherland":               "Anthony Kelly",
    },
    2022: {
        "San Giacomos Frannys Fanny":   "Charlie Gorman",
        "Mike White":                   "Ryan McQuaid",
        "Broncos Country Lets Ride!":   "Carmine Pittelli",
        "AnaKen skyWalker":             "Quin Gegwich",
        "Tiger King":                   "Ethan Radecki",
        "Nicholas Cruz's":              "Cole Maney",
        "The Minutemen \ufe3b\u30c7\u2550\u4e00": "Brandon Hancock",
        "Rolls With butter":            "Anthony Kelly",
        "Tony Fkn Romo":                "Aidan Quigley",
        "U SHOULDVE GONE FOR THE HEAD": "Baylen Slansky",
        ". Dan Washburn":               "Max Malich",
        "The Less Fourtunette":         "Ben Castaldo",
        "Chi Town Murder Suicide?":     "Deniz Bileydi",
        "N.Y. Routensss":               "Andrew Root",
    },
    2023: {
        "The Koo Dynasty":              "Ryan McQuaid",
        "Oh He Likes Cooking!":         "Ethan Radecki",
        "THERE IS NO DOOR NUMBER FOUR": "Baylen Slansky",
        "Allgeier Season":              "Quin Gegwich",
        "Tony Fkn Romo":                "Aidan Quigley",
        "Pickett to Pickens":           "Ben Castaldo",
        "San Giacomos Frannys Fanny":   "Charlie Gorman",
        "Rolls With butter":            "Anthony Kelly",
        "Run Gibbs Fraud Ford":         "Max Malich",
        "Free Kyle Pitts":              "Deniz Bileydi",
        "Addison Square Garden":        "Cole Maney",
        "The Minutemen \ufe3b\u30c7\u2550\u4e00": "Brandon Hancock",
        "Thank You Max!":               "Carmine Pittelli",
        "N.Y. Routensss":               "Andrew Root",
    },
    2024: {
        "N.Y. Routensss":               "Andrew Root",
        "JOSH JACOBS FAN CLUB":         "Quin Gegwich",
        "LeGoon":                       "Ben Castaldo",
        "Rolls With Butter":            "Anthony Kelly",
        "Set Pitts Free":               "Deniz Bileydi",
        "STATION GRITS":                "Baylen Slansky",
        "Glass of Charbonnet":          "Cole Maney",
        "The Minutemen \ufe3b\u30c7\u2550\u4e00": "Brandon Hancock",
        "Kittle Me This":               "Carmine Pittelli",
        "Tee Time":                     "Charlie Gorman",
        "Oh He Likes Cooking!":         "Ethan Radecki",
        "Dent.":                        "Max Malich",
        "LaPorta Potty":                "Ryan McQuaid",
        "Tony Fkn Romo":                "Aidan Quigley",
    },
    2025: {
        "Make Fantasy Great Again":     "Ryan McQuaid",
        "N.Y. Routensss":               "Andrew Root",
        "RPMs backup team":             "Deniz Bileydi",
        "A$AP Monke":                   "Ben Castaldo",
        "The Minutemen":                "Brandon Hancock",
        "Oh He Likes Cooking!":         "Ethan Radecki",
        "Talking Tua Freshman":         "Aidan Quigley",
        "STATION GRITS":                "Baylen Slansky",
        "Rolls With Butter":            "Anthony Kelly",
        "Shakir to death":              "Cole Maney",
        "Worthy of a Warren(t)":        "Charlie Gorman",
        "(Dan wash)Burn":               "Max Malich",
        "LaPorta Potty":                "Carmine Pittelli",
        "Theres Always This Year":      "Quin Gegwich",
    },
}

# Build manager -> draft_slot lookup per season from SLOT_LOOKUP
def build_manager_slot_map(season):
    result = {}
    for slot, season_map in SLOT_LOOKUP.items():
        if season in season_map:
            result[season_map[season]] = slot
    return result

# ── 2021 corrected pick order (offline draft) ────────────────────────────────
# ESPN shows wrong order; real round 1 order was:
CORRECTED_2021_ROUND1_ORDER = [
    "N.Y. Routensss",
    "Chicago We got um",
    "I shoot blanks n shit",
    "San Giacomos Frannys Fanny",
    "AND I...AM ...IRON MAN",
    "Darnold Trump",
    "Nicholas Cruz's",
    "Kittle Me This",
    "Fresh Prince Of Helaire",
    "Tony Fkn Romo",
    ". Hockenshit",
    "The Minutemen \ufe3b\u30c7\u2550\u4e00",
    "Mixon a Half Ch\xfabb",
    "Zay Sutherland",
]

# ── Core parser ───────────────────────────────────────────────────────────────

def parse_draft(raw_text, season, league_size=14):
    lines = [l.strip() for l in raw_text.strip().split('\n') if l.strip()]

    team_to_manager = TEAM_TO_MANAGER[season]
    manager_to_slot = build_manager_slot_map(season)

    records = []
    current_round = None
    i = 0

    while i < len(lines):
        line = lines[i]

        # Detect round header
        if line.startswith("Round "):
            current_round = int(line.split()[1])
            i += 1
            continue

        # Skip column headers
        if line in ("NO.", "Player", "Team"):
            i += 1
            continue

        # Detect pick number within round
        if line.isdigit() and i + 2 < len(lines):
            pick_in_round = int(line)
            player_line   = lines[i + 1]
            team_line     = lines[i + 2]

            # Parse player name and position from player_line
            # Format: "First Last NFLTeam, POS"
            match = re.match(r"^(.+?)\s+[A-Za-z]{2,3},\s+(\S+)$", player_line)
            if match:
                player_name = match.group(1).strip()
                position    = match.group(2).strip()
            else:
                player_name = player_line
                position    = "UNK"

            # Overall pick number (sequential across whole draft)
            overall_pick = (current_round - 1) * league_size + pick_in_round

            # Manager from team name
            manager = team_to_manager.get(team_line, team_line)

            # Draft slot from authoritative lookup table
            draft_slot = manager_to_slot.get(manager, None)

            # 2021 special case: ESPN pick order is wrong for round 1
            # Use corrected order to assign slots via team name position
            if season == 2021:
                # Normalise for matching (strip unicode quirks)
                corrected_slots = {t: idx + 1 for idx, t in enumerate(CORRECTED_2021_ROUND1_ORDER)}
                draft_slot = corrected_slots.get(team_line, draft_slot)

            records.append({
                "season":        season,
                "round":         current_round,
                "draft_slot":    draft_slot,
                "overall_pick":  overall_pick,
                "pick_in_round": pick_in_round,
                "player_name":   player_name,
                "position":      position,
                "manager":       manager,
                "fantasy_team":  team_line,
            })
            i += 3
            continue

        i += 1

    return pd.DataFrame(records)

# ── Raw draft text ────────────────────────────────────────────────────────────

raw_2020 = """
Round 1
NO.
Player
Team
1
Christian McCaffrey Car, RB
Team Kelly
2
Saquon Barkley NYG, RB
N.Y. Routensss
3
Ezekiel Elliott Dal, RB
San Giacomos Frannys Fanny
4
Dalvin Cook Min, RB
Goodwill Hunting V2
5
Alvin Kamara NO, RB
Fourth Reich ✠
6
Michael Thomas NO, WR
STATION GRITS
7
Clyde Edwards-Helaire KC, RB
New York Jets
8
Derrick Henry Ten, RB
. Can you Digg it
9
Miles Sanders Phi, RB
North Korea Dingus MAGA
10
Kenyan Drake Ari, RB
Slant Boy v2
11
Julio Jones Atl, WR
Hot Rod
12
DeAndre Hopkins Ari, WR
Chicago We got um
13
Josh Jacobs LV, RB
Jungle Le Monke
14
Austin Ekeler LAC, RB
The South Will Rise
15
Aaron Jones GB, RB
Team Serafin
Round 2
NO.
Player
Team
1
Tyreek Hill KC, WR
Team Serafin
2
Nick Chubb Cle, RB
The South Will Rise
3
Davante Adams GB, WR
Jungle Le Monke
4
Lamar Jackson Bal, QB
Chicago We got um
5
Joe Mixon Cin, RB
Hot Rod
6
Chris Godwin TB, WR
Slant Boy v2
7
Travis Kelce KC, TE
North Korea Dingus MAGA
8
George Kittle SF, TE
. Can you Digg it
9
Mike Evans TB, WR
New York Jets
10
Kenny Golladay Det, WR
STATION GRITS
11
Patrick Mahomes KC, QB
Fourth Reich ✠
12
Allen Robinson II Chi, WR
Goodwill Hunting V2
13
Adam Thielen Min, WR
San Giacomos Frannys Fanny
14
DJ Moore Car, WR
N.Y. Routensss
15
JuJu Smith-Schuster Pit, WR
Team Kelly
Round 3
NO.
Player
Team
1
Amari Cooper Dal, WR
Team Kelly
2
Tyler Lockett Sea, WR
N.Y. Routensss
3
David Johnson Hou, RB
San Giacomos Frannys Fanny
4
Chris Carson Sea, RB
Goodwill Hunting V2
5
Courtland Sutton Den, WR
Fourth Reich ✠
6
Odell Beckham Jr. Cle, WR
STATION GRITS
7
Le'Veon Bell KC, RB
New York Jets
8
A.J. Brown Ten, WR
. Can you Digg it
9
Robert Woods LAR, WR
North Korea Dingus MAGA
10
Keenan Allen LAC, WR
Slant Boy v2
11
Melvin Gordon III Den, RB
Hot Rod
12
Todd Gurley II Atl, RB
Chicago We got um
13
Cooper Kupp LAR, WR
Jungle Le Monke
14
Calvin Ridley Atl, WR
The South Will Rise
15
T.Y. Hilton Ind, WR
Team Serafin
Round 4
NO.
Player
Team
1
James Conner Pit, RB
Team Serafin
2
Deshaun Watson Hou, QB
The South Will Rise
3
Jarvis Landry Cle, WR
Jungle Le Monke
4
Mark Andrews Bal, TE
Chicago We got um
5
DJ Chark Jr. Jax, WR
Hot Rod
6
Kareem Hunt Cle, RB
Slant Boy v2
7
Terry McLaurin Wsh, WR
North Korea Dingus MAGA
8
Jonathan Taylor Ind, RB
. Can you Digg it
9
Dak Prescott Dal, QB
New York Jets
10
Zach Ertz Phi, TE
STATION GRITS
11
DeVante Parker Mia, WR
Fourth Reich ✠
12
DK Metcalf Sea, WR
Goodwill Hunting V2
13
Russell Wilson Sea, QB
San Giacomos Frannys Fanny
14
Cam Akers LAR, RB
N.Y. Routensss
15
Kyler Murray Ari, QB
Team Kelly
Round 5
NO.
Player
Team
1
D'Andre Swift Det, RB
Team Kelly
2
Darren Waller LV, TE
N.Y. Routensss
3
Tyler Boyd Cin, WR
San Giacomos Frannys Fanny
4
Devin Singletary Buf, RB
Goodwill Hunting V2
5
Mark Ingram II FA, RB
Fourth Reich ✠
6
David Montgomery Chi, RB
STATION GRITS
7
Marquise Brown Bal, WR
New York Jets
8
Stefon Diggs Buf, WR
. Can you Digg it
9
Ronald Jones II TB, RB
North Korea Dingus MAGA
10
Michael Gallup Dal, WR
Slant Boy v2
11
Matt Ryan Atl, QB
Hot Rod
12
Raheem Mostert SF, RB
Chicago We got um
13
Tom Brady TB, QB
Jungle Le Monke
14
A.J. Green Cin, WR
The South Will Rise
15
Deebo Samuel SF, WR
Team Serafin
Round 6
NO.
Player
Team
1
Evan Engram NYG, TE
Team Serafin
2
Tarik Cohen Chi, RB
The South Will Rise
3
Carson Wentz Ind, QB
Jungle Le Monke
4
Will Fuller V Hou, WR
Chicago We got um
5
Phillip Lindsay Den, RB
Hot Rod
6
Tyler Higbee LAR, TE
Slant Boy v2
7
Drew Brees NO, QB
North Korea Dingus MAGA
8
Kerryon Johnson Det, RB
. Can you Digg it
9
Julian Edelman NE, WR
New York Jets
10
Darrell Henderson Jr. LAR, RB
STATION GRITS
11
Marvin Jones Jr. Det, WR
Fourth Reich ✠
12
Jared Cook FA, TE
Goodwill Hunting V2
13
Rob Gronkowski TB, TE
San Giacomos Frannys Fanny
14
Aaron Rodgers GB, QB
N.Y. Routensss
15
Brandin Cooks Hou, WR
Team Kelly
Round 7
NO.
Player
Team
1
Hayden Hurst Atl, TE
Team Kelly
2
Diontae Johnson Pit, WR
N.Y. Routensss
3
Jamison Crowder NYJ, WR
San Giacomos Frannys Fanny
4
Josh Allen Buf, QB
Goodwill Hunting V2
5
Hunter Henry LAC, TE
Fourth Reich ✠
6
James White NE, RB
STATION GRITS
7
J.K. Dobbins Bal, RB
New York Jets
8
Preston Williams Mia, WR
. Can you Digg it
9
Christian Kirk Ari, WR
North Korea Dingus MAGA
10
Matthew Stafford LAR, QB
Slant Boy v2
11
Austin Hooper Cle, TE
Hot Rod
12
Sterling Shepard NYG, WR
Chicago We got um
13
Noah Fant Den, TE
Jungle Le Monke
14
T.J. Hockenson Det, TE
The South Will Rise
15
Daniel Jones NYG, QB
Team Serafin
Round 8
NO.
Player
Team
1
Darius Slayton NYG, WR
Team Serafin
2
Jordan Howard Phi, RB
The South Will Rise
3
Matt Breida Mia, RB
Jungle Le Monke
4
Tevin Coleman SF, RB
Chicago We got um
5
Ryquell Armstead Jax, RB
Hot Rod
6
John Brown Buf, WR
Slant Boy v2
7
Emmanuel Sanders NO, WR
North Korea Dingus MAGA
8
Henry Ruggs III LV, WR
. Can you Digg it
9
Golden Tate FA, WR
New York Jets
10
Zack Moss Buf, RB
STATION GRITS
11
Marlon Mack Ind, RB
Fourth Reich ✠
12
Curtis Samuel Car, WR
Goodwill Hunting V2
13
Bears D/ST Chi, D/ST
San Giacomos Frannys Fanny
14
Latavius Murray NO, RB
N.Y. Routensss
15
Robby Anderson Car, WR
Team Kelly
Round 9
NO.
Player
Team
1
Jerry Jeudy Den, WR
Team Kelly
2
CeeDee Lamb Dal, WR
N.Y. Routensss
3
Alexander Mattison Min, RB
San Giacomos Frannys Fanny
4
Steelers D/ST Pit, D/ST
Goodwill Hunting V2
5
49ers D/ST SF, D/ST
Fourth Reich ✠
6
Tony Pollard Dal, RB
STATION GRITS
7
Chris Herndon NYJ, TE
New York Jets
8
Duke Johnson FA, RB
. Can you Digg it
9
Nyheim Hines Ind, RB
North Korea Dingus MAGA
10
Chris Thompson Jax, RB
Slant Boy v2
11
Mecole Hardman KC, WR
Hot Rod
12
Justin Jefferson Min, WR
Chicago We got um
13
Bills D/ST Buf, D/ST
Jungle Le Monke
14
Mike Williams LAC, WR
The South Will Rise
15
Antonio Gibson Wsh, RB
Team Serafin
Round 10
NO.
Player
Team
1
Larry Fitzgerald Ari, WR
Team Serafin
2
Breshad Perriman NYJ, WR
The South Will Rise
3
Justin Tucker Bal, K
Jungle Le Monke
4
Patriots D/ST NE, D/ST
Chicago We got um
5
Ryan Tannehill Ten, QB
Hot Rod
6
Anthony Miller Chi, WR
Slant Boy v2
7
Colts D/ST Ind, D/ST
North Korea Dingus MAGA
8
Jared Goff Det, QB
. Can you Digg it
9
Leonard Fournette TB, RB
New York Jets
10
Ben Roethlisberger Pit, QB
STATION GRITS
11
DeSean Jackson FA, WR
Fourth Reich ✠
12
Adrian Peterson Det, RB
Goodwill Hunting V2
13
Eric Ebron Pit, TE
San Giacomos Frannys Fanny
14
Broncos D/ST Den, D/ST
N.Y. Routensss
15
Cam Newton NE, QB
Team Kelly
Round 11
NO.
Player
Team
1
Ravens D/ST Bal, D/ST
Team Kelly
2
N'Keal Harry NE, WR
N.Y. Routensss
3
Allen Lazard GB, WR
San Giacomos Frannys Fanny
4
Mike Gesicki Mia, TE
Goodwill Hunting V2
5
Wil Lutz NO, K
Fourth Reich ✠
6
Parris Campbell Ind, WR
STATION GRITS
7
Justin Jackson LAC, RB
New York Jets
8
Harrison Butker KC, K
. Can you Digg it
9
Sammy Watkins KC, WR
North Korea Dingus MAGA
10
Vikings D/ST Min, D/ST
Slant Boy v2
11
Robbie Gould SF, K
Hot Rod
12
Greg Zuerlein Dal, K
Chicago We got um
13
Damien Harris NE, RB
Jungle Le Monke
14
Chase Edmonds Ari, RB
The South Will Rise
15
Jack Doyle Ind, TE
Team Serafin
Round 12
NO.
Player
Team
1
Saints D/ST NO, D/ST
Team Serafin
2
Matt Prater Det, K
The South Will Rise
3
Boston Scott Phi, RB
Jungle Le Monke
4
Randall Cobb Hou, WR
Chicago We got um
5
Jerick McKinnon SF, RB
Hot Rod
6
Mohamed Sanu Sr. Det, WR
Slant Boy v2
7
Brandon Aiyuk SF, WR
North Korea Dingus MAGA
8
Seahawks D/ST Sea, D/ST
. Can you Digg it
9
Denzel Mims NYJ, WR
New York Jets
10
Michael Pittman Jr. Ind, WR
STATION GRITS
11
Sony Michel NE, RB
Fourth Reich ✠
12
Matt Gay LAR, K
Goodwill Hunting V2
13
Zane Gonzalez FA, K
San Giacomos Frannys Fanny
14
Jalen Reagor Phi, WR
N.Y. Routensss
15
Carlos Hyde Sea, RB
Team Kelly
Round 13
NO.
Player
Team
1
Chris Boswell Pit, K
Team Kelly
2
Tee Higgins Cin, WR
N.Y. Routensss
3
Benny Snell Jr. Pit, RB
San Giacomos Frannys Fanny
4
Steven Sims Jr. Wsh, WR
Goodwill Hunting V2
5
Dede Westbrook Jax, WR
Fourth Reich ✠
6
Buccaneers D/ST TB, D/ST
STATION GRITS
7
Blake Jarwin Dal, TE
New York Jets
8
Ke'Shawn Vaughn TB, RB
. Can you Digg it
9
Dallas Goedert Phi, TE
North Korea Dingus MAGA
10
Austin Seibert Cin, K
Slant Boy v2
11
Cowboys D/ST Dal, D/ST
Hot Rod
12
AJ Dillon GB, RB
Chicago We got um
13
Darrel Williams KC, RB
Jungle Le Monke
14
Baker Mayfield Cle, QB
The South Will Rise
15
Chase McLaughlin NYJ, K
Team Serafin
Round 14
NO.
Player
Team
1
Jakeem Grant Mia, WR
Team Serafin
2
Chargers D/ST LAC, D/ST
The South Will Rise
3
Irv Smith Jr. Min, TE
Jungle Le Monke
4
Jimmy Garoppolo SF, QB
Chicago We got um
5
Ka'imi Fairbairn Hou, K
Hot Rod
6
Joe Burrow Cin, QB
Slant Boy v2
7
Kirk Cousins Min, QB
North Korea Dingus MAGA
8
Russell Gage Atl, WR
. Can you Digg it
9
Sam Darnold NYJ, QB
New York Jets
10
Jake Elliott Phi, K
STATION GRITS
11
Kyle Rudolph FA, TE
Fourth Reich ✠
12
Jamaal Williams GB, RB
Goodwill Hunting V2
13
Darrynton Evans Ten, RB
San Giacomos Frannys Fanny
14
Alshon Jeffery Phi, WR
N.Y. Routensss
15
James Washington Pit, WR
Team Kelly
Round 15
NO.
Player
Team
1
Chase Claypool Pit, WR
Team Kelly
2
Joshua Kelley LAC, RB
N.Y. Routensss
3
Anthony McFarland Jr. Pit, RB
San Giacomos Frannys Fanny
4
Danny Amendola Det, WR
Goodwill Hunting V2
5
Cole Beasley Buf, WR
Fourth Reich ✠
6
LeSean McCoy TB, RB
STATION GRITS
7
Younghoe Koo Atl, K
New York Jets
8
Jonnu Smith Ten, TE
. Can you Digg it
9
Mason Crosby GB, K
North Korea Dingus MAGA
10
Corey Davis Ten, WR
Slant Boy v2
11
Giovani Bernard Cin, RB
Hot Rod
12
Bryce Love Wsh, RB
Chicago We got um
13
Devine Ozigbo Jax, RB
Jungle Le Monke
14
Lynn Bowden Jr. Mia, RB
The South Will Rise
15
DeAndre Washington Mia, RB
Team Serafin
Round 16
NO.
Player
Team
1
Devin Duvernay Bal, WR
Team Serafin
2
Laviska Shenault Jr. Jax, WR
The South Will Rise
3
Drew Lock Den, QB
Jungle Le Monke
4
Bryan Edwards LV, WR
Chicago We got um
5
Josh Reynolds LAR, WR
Hot Rod
6
Antonio Brown TB, WR
Slant Boy v2
7
Hunter Renfrow LV, WR
North Korea Dingus MAGA
8
Trent Taylor SF, WR
. Can you Digg it
9
Bengals D/ST Cin, D/ST
New York Jets
10
KJ Hamler Den, WR
STATION GRITS
11
Scotty Miller TB, WR
Fourth Reich ✠
12
Gardner Minshew II Jax, QB
Goodwill Hunting V2
13
Chris Conley Jax, WR
San Giacomos Frannys Fanny
14
Jason Myers Sea, K
N.Y. Routensss
15
Adam Humphries FA, WR
Team Kelly
"""

raw_2021 = """
Round 1
NO.
Player
Team
1
Christian McCaffrey Car, RB
N.Y. Routensss
2
Travis Kelce KC, TE
Zay Sutherland
3
Alvin Kamara NO, RB
I shoot blanks n shit
4
Derrick Henry Ten, RB
San Giacomos Frannys Fanny
5
Ezekiel Elliott Dal, RB
AND I...AM ...IRON MAN
6
Austin Ekeler LAC, RB
Darnold Trump
7
Aaron Jones GB, RB
Nicholas Cruz's
8
Saquon Barkley NYG, RB
Kittle Me This
9
Davante Adams GB, WR
Fresh Prince Of Helaire
10
Jonathan Taylor Ind, RB
Tony Fkn Romo
11
Antonio Gibson Wsh, RB
. Hockenshit
12
Nick Chubb Cle, RB
The Minutemen ︻デ═一
13
Najee Harris Pit, RB
Mixon a Half Chûbb
14
Dalvin Cook Min, RB
Chicago We got um
Round 2
NO.
Player
Team
1
Darren Waller LV, TE
Chicago We got um
2
Stefon Diggs Buf, WR
Mixon a Half Chûbb
3
DeAndre Hopkins Ari, WR
The Minutemen ︻デ═一
4
Calvin Ridley Atl, WR
. Hockenshit
5
James Robinson Jax, RB
Tony Fkn Romo
6
Clyde Edwards-Helaire KC, RB
Fresh Prince Of Helaire
7
Keenan Allen LAC, WR
Kittle Me This
8
DK Metcalf Sea, WR
Nicholas Cruz's
9
Joe Mixon Cin, RB
Darnold Trump
10
Allen Robinson II Chi, WR
AND I...AM ...IRON MAN
11
Chris Carson Sea, RB
San Giacomos Frannys Fanny
12
David Montgomery Chi, RB
I shoot blanks n shit
13
Tyreek Hill KC, WR
Zay Sutherland
14
Miles Sanders Phi, RB
N.Y. Routensss
Round 3
NO.
Player
Team
1
A.J. Brown Ten, WR
N.Y. Routensss
2
Josh Jacobs LV, RB
Zay Sutherland
3
Justin Jefferson Min, WR
I shoot blanks n shit
4
Robert Woods LAR, WR
San Giacomos Frannys Fanny
5
CeeDee Lamb Dal, WR
AND I...AM ...IRON MAN
6
D'Andre Swift Det, RB
Darnold Trump
7
Diontae Johnson Pit, WR
Nicholas Cruz's
8
George Kittle SF, TE
Kittle Me This
9
Cooper Kupp LAR, WR
Fresh Prince Of Helaire
10
Amari Cooper Dal, WR
Tony Fkn Romo
11
Brandon Aiyuk SF, WR
. Hockenshit
12
Julio Jones Ten, WR
The Minutemen ︻デ═一
13
Mike Evans TB, WR
Mixon a Half Chûbb
14
Terry McLaurin Wsh, WR
Chicago We got um
Round 4
NO.
Player
Team
1
Damien Harris NE, RB
Chicago We got um
2
Adam Thielen Min, WR
Mixon a Half Chûbb
3
Javonte Williams Den, RB
The Minutemen ︻デ═一
4
T.J. Hockenson Det, TE
. Hockenshit
5
Chris Godwin TB, WR
Tony Fkn Romo
6
Kyler Murray Ari, QB
Fresh Prince Of Helaire
7
Tyler Lockett Sea, WR
Kittle Me This
8
Chase Edmonds Ari, RB
Nicholas Cruz's
9
DJ Moore Car, WR
Darnold Trump
10
Gus Edwards Bal, RB
AND I...AM ...IRON MAN
11
JuJu Smith-Schuster Pit, WR
San Giacomos Frannys Fanny
12
Robby Anderson Car, WR
I shoot blanks n shit
13
Myles Gaskin Mia, RB
Zay Sutherland
14
Courtland Sutton Den, WR
N.Y. Routensss
Round 5
NO.
Player
Team
1
Patrick Mahomes KC, QB
N.Y. Routensss
2
Kareem Hunt Cle, RB
Zay Sutherland
3
Josh Allen Buf, QB
I shoot blanks n shit
4
Lamar Jackson Bal, QB
San Giacomos Frannys Fanny
5
Justin Herbert LAC, QB
AND I...AM ...IRON MAN
6
Corey Davis NYJ, WR
Darnold Trump
7
Mark Andrews Bal, TE
Nicholas Cruz's
8
Dak Prescott Dal, QB
Kittle Me This
9
Kyle Pitts Atl, TE
Fresh Prince Of Helaire
10
Russell Wilson Sea, QB
Tony Fkn Romo
11
Aaron Rodgers GB, QB
. Hockenshit
12
DeVonta Smith Phi, WR
The Minutemen ︻デ═一
13
Mike Davis Atl, RB
Mixon a Half Chûbb
14
Tee Higgins Cin, WR
Chicago We got um
Round 6
NO.
Player
Team
1
Odell Beckham Jr. LAR, WR
Chicago We got um
2
Logan Thomas Wsh, TE
Mixon a Half Chûbb
3
Tom Brady TB, QB
The Minutemen ︻デ═一
4
Zack Moss Buf, RB
. Hockenshit
5
Noah Fant Den, TE
Tony Fkn Romo
6
Leonard Fournette TB, RB
Fresh Prince Of Helaire
7
Jerry Jeudy Den, WR
Kittle Me This
8
Ja'Marr Chase Cin, WR
Nicholas Cruz's
9
Ryan Tannehill Ten, QB
Darnold Trump
10
Chase Claypool Pit, WR
AND I...AM ...IRON MAN
11
Brandin Cooks Hou, WR
San Giacomos Frannys Fanny
12
Dallas Goedert Phi, TE
I shoot blanks n shit
13
Kenny Golladay NYG, WR
Zay Sutherland
14
Laviska Shenault Jr. Jax, WR
N.Y. Routensss
Round 7
NO.
Player
Team
1
Antonio Brown FA, WR
N.Y. Routensss
2
Joe Burrow Cin, QB
Zay Sutherland
3
Tyler Boyd Cin, WR
I shoot blanks n shit
4
Robert Tonyan GB, TE
San Giacomos Frannys Fanny
5
Marquez Callaway NO, WR
AND I...AM ...IRON MAN
6
Michael Thomas NO, WR
Darnold Trump
7
Matthew Stafford LAR, QB
Nicholas Cruz's
8
Darrell Henderson Jr. LAR, RB
Kittle Me This
9
William Fuller V Mia, WR
Fresh Prince Of Helaire
10
DJ Chark Jr. Jax, WR
Tony Fkn Romo
11
Trey Sermon SF, RB
. Hockenshit
12
Raheem Mostert SF, RB
The Minutemen ︻デ═一
13
Baker Mayfield Cle, QB
Mixon a Half Chûbb
14
Jalen Hurts Phi, QB
Chicago We got um
Round 8
NO.
Player
Team
1
Marvin Jones Jr. Jax, WR
Chicago We got um
2
Michael Carter NYJ, RB
Mixon a Half Chûbb
3
Tyler Higbee LAR, TE
The Minutemen ︻デ═一
4
Russell Gage Atl, WR
. Hockenshit
5
Jamaal Williams Det, RB
Tony Fkn Romo
6
Jarvis Landry Cle, WR
Fresh Prince Of Helaire
7
Sony Michel LAR, RB
Kittle Me This
8
Darnell Mooney Chi, WR
Nicholas Cruz's
9
Jonnu Smith NE, TE
Darnold Trump
10
Melvin Gordon III Den, RB
AND I...AM ...IRON MAN
11
Mecole Hardman KC, WR
San Giacomos Frannys Fanny
12
Kenyan Drake LV, RB
I shoot blanks n shit
13
Michael Pittman Jr. Ind, WR
Zay Sutherland
14
Evan Engram NYG, TE
N.Y. Routensss
Round 9
NO.
Player
Team
1
Henry Ruggs III FA, WR
N.Y. Routensss
2
Tony Pollard Dal, RB
Zay Sutherland
3
Deebo Samuel SF, WR
I shoot blanks n shit
4
James Conner Ari, RB
San Giacomos Frannys Fanny
5
Terrace Marshall Jr. Car, WR
AND I...AM ...IRON MAN
6
Elijah Moore NYJ, WR
Darnold Trump
7
Alexander Mattison Min, RB
Nicholas Cruz's
8
Jaylen Waddle Mia, WR
Kittle Me This
9
Phillip Lindsay Mia, RB
Fresh Prince Of Helaire
10
Curtis Samuel Wsh, WR
Tony Fkn Romo
11
Mike Williams LAC, WR
. Hockenshit
12
Nelson Agholor NE, WR
The Minutemen ︻デ═一
13
Hunter Renfrow LV, WR
Mixon a Half Chûbb
14
Ronald Jones II TB, RB
Chicago We got um
Round 10
NO.
Player
Team
1
Ravens D/ST Bal, D/ST
Chicago We got um
2
Anthony Miller Pit, WR
Mixon a Half Chûbb
3
AJ Dillon GB, RB
The Minutemen ︻デ═一
4
Xavier Jones LAR, RB
. Hockenshit
5
Jakobi Meyers NE, WR
Tony Fkn Romo
6
Jalen Reagor Phi, WR
Fresh Prince Of Helaire
7
J.D. McKissic Wsh, RB
Kittle Me This
8
Sterling Shepard NYG, WR
Nicholas Cruz's
9
Younghoe Koo Atl, K
Darnold Trump
10
Cole Beasley Buf, WR
AND I...AM ...IRON MAN
11
Buccaneers D/ST TB, D/ST
San Giacomos Frannys Fanny
12
Steelers D/ST Pit, D/ST
I shoot blanks n shit
13
Michael Gallup Dal, WR
Zay Sutherland
14
Commanders D/ST Wsh, D/ST
N.Y. Routensss
Round 11
NO.
Player
Team
1
Kadarius Toney NYG, WR
N.Y. Routensss
2
Amon-Ra St. Brown Det, WR
Zay Sutherland
3
Nyheim Hines Ind, RB
I shoot blanks n shit
4
Bryan Edwards LV, WR
San Giacomos Frannys Fanny
5
49ers D/ST SF, D/ST
AND I...AM ...IRON MAN
6
Adam Trautman NO, TE
Darnold Trump
7
Rams D/ST LAR, D/ST
Nicholas Cruz's
8
Browns D/ST Cle, D/ST
Kittle Me This
9
Bills D/ST Buf, D/ST
Fresh Prince Of Helaire
10
Harrison Butker KC, K
Tony Fkn Romo
11
Patriots D/ST NE, D/ST
. Hockenshit
12
Colts D/ST Ind, D/ST
The Minutemen ︻デ═一
13
Chiefs D/ST KC, D/ST
Mixon a Half Chûbb
14
A.J. Green Ari, WR
Chicago We got um
Round 12
NO.
Player
Team
1
Deshaun Watson Hou, QB
Chicago We got um
2
Samaje Perine Cin, RB
Mixon a Half Chûbb
3
Tre'Quan Smith NO, WR
The Minutemen ︻デ═一
4
Marquise Brown Bal, WR
. Hockenshit
5
Teddy Bridgewater Den, QB
Tony Fkn Romo
6
Parris Campbell Ind, WR
Fresh Prince Of Helaire
7
Devontae Booker NYG, RB
Kittle Me This
8
Jamison Crowder NYJ, WR
Nicholas Cruz's
9
Tevin Coleman NYJ, RB
Darnold Trump
10
Mike Gesicki Mia, TE
AND I...AM ...IRON MAN
11
Ryan Succop TB, K
San Giacomos Frannys Fanny
12
Rodrigo Blankenship Ind, K
I shoot blanks n shit
13
Latavius Murray Bal, RB
Zay Sutherland
14
Boston Scott Phi, RB
N.Y. Routensss
Round 13
NO.
Player
Team
1
Rashod Bateman Bal, WR
N.Y. Routensss
2
Tua Tagovailoa Mia, QB
Zay Sutherland
3
Quintez Cephus Det, WR
I shoot blanks n shit
4
Sammy Watkins Bal, WR
San Giacomos Frannys Fanny
5
Jason Sanders Mia, K
AND I...AM ...IRON MAN
6
Carson Wentz Ind, QB
Darnold Trump
7
Jason Myers Sea, K
Nicholas Cruz's
8
Tyler Bass Buf, K
Kittle Me This
9
Mason Crosby GB, K
Fresh Prince Of Helaire
10
Bears D/ST Chi, D/ST
Tony Fkn Romo
11
Randall Cobb GB, WR
. Hockenshit
12
Matt Gay LAR, K
The Minutemen ︻デ═一
13
Justin Fields Chi, QB
Mixon a Half Chûbb
14
Justin Tucker Bal, K
Chicago We got um
Round 14
NO.
Player
Team
1
DeVante Parker Mia, WR
Chicago We got um
2
Chris Boswell Pit, K
Mixon a Half Chûbb
3
Jared Cook LAC, TE
The Minutemen ︻デ═一
4
Brandon McManus Den, K
. Hockenshit
5
Malcolm Brown Mia, RB
Tony Fkn Romo
6
Trevor Lawrence Jax, QB
Fresh Prince Of Helaire
7
Jameis Winston NO, QB
Kittle Me This
8
Trey Lance SF, QB
Nicholas Cruz's
9
James White NE, RB
Darnold Trump
10
Chuba Hubbard Car, RB
AND I...AM ...IRON MAN
11
Joshua Kelley LAC, RB
San Giacomos Frannys Fanny
12
Ryan Fitzpatrick Wsh, QB
I shoot blanks n shit
13
Robbie Gould SF, K
Zay Sutherland
14
Matt Prater Ari, K
N.Y. Routensss
Round 15
NO.
Player
Team
1
Cam Newton Car, QB
N.Y. Routensss
2
Broncos D/ST Den, D/ST
Zay Sutherland
3
Zach Ertz Ari, TE
I shoot blanks n shit
4
Sam Darnold Car, QB
San Giacomos Frannys Fanny
5
Kirk Cousins Min, QB
AND I...AM ...IRON MAN
6
Vikings D/ST Min, D/ST
Darnold Trump
7
Salvon Ahmed Mia, RB
Nicholas Cruz's
8
Zach Pascal Ind, WR
Kittle Me This
9
Devin Singletary Buf, RB
Fresh Prince Of Helaire
10
Rob Gronkowski TB, TE
Tony Fkn Romo
11
Derek Carr LV, QB
. Hockenshit
12
Jared Goff Det, QB
The Minutemen ︻デ═一
13
Carlos Hyde Jax, RB
Mixon a Half Chûbb
14
Jeff Wilson Jr. SF, RB
Chicago We got um
Round 16
NO.
Player
Team
1
Mac Jones NE, QB
Chicago We got um
2
Ty Johnson NYJ, RB
Mixon a Half Chûbb
3
Dee Eskridge Sea, WR
The Minutemen ︻デ═一
4
Ty Montgomery NO, WR
. Hockenshit
5
N'Keal Harry NE, WR
Tony Fkn Romo
6
T.Y. Hilton Ind, WR
Fresh Prince Of Helaire
7
Nico Collins Hou, WR
Kittle Me This
8
Matt Ryan Atl, QB
Nicholas Cruz's
9
Zach Wilson NYJ, QB
Darnold Trump
10
Tyrell Williams FA, WR
AND I...AM ...IRON MAN
11
Marlon Mack Ind, RB
San Giacomos Frannys Fanny
12
Donovan Peoples-Jones Cle, WR
I shoot blanks n shit
13
Qadree Ollison Atl, RB
Zay Sutherland
14
Tarik Cohen Chi, RB
N.Y. Routensss
"""

raw_2022 = """
Round 1
NO.
Player
Team
1
Jonathan Taylor Ind, RB
San Giacomos Frannys Fanny
2
Derrick Henry Ten, RB
Mike White
3
Christian McCaffrey SF, RB
Broncos Country Lets Ride!
4
Cooper Kupp LAR, WR
AnaKen skyWalker
5
Austin Ekeler LAC, RB
Tiger King
6
Justin Jefferson Min, WR
Nicholas Cruz's
7
Najee Harris Pit, RB
The Minutemen ︻デ═一
8
Ja'Marr Chase Cin, WR
Rolls With butter
9
Dalvin Cook Min, RB
Tony Fkn Romo
10
Joe Mixon Cin, RB
U SHOULDVE GONE FOR THE HEAD
11
D'Andre Swift Det, RB
. Dan Washburn
12
Davante Adams LV, WR
The Less Fourtunette
13
Stefon Diggs Buf, WR
Chi Town Murder Suicide?
14
Aaron Jones GB, RB
N.Y. Routensss
Round 2
NO.
Player
Team
1
Deebo Samuel SF, WR
N.Y. Routensss
2
CeeDee Lamb Dal, WR
Chi Town Murder Suicide?
3
Leonard Fournette FA, RB
The Less Fourtunette
4
Alvin Kamara NO, RB
. Dan Washburn
5
Saquon Barkley NYG, RB
U SHOULDVE GONE FOR THE HEAD
6
Keenan Allen LAC, WR
Tony Fkn Romo
7
James Conner Ari, RB
Rolls With butter
8
Tyreek Hill Mia, WR
The Minutemen ︻デ═一
9
Javonte Williams Den, RB
Nicholas Cruz's
10
Tee Higgins Cin, WR
Tiger King
11
David Montgomery Det, RB
AnaKen skyWalker
12
Travis Kelce KC, TE
Broncos Country Lets Ride!
13
Jaylen Waddle Mia, WR
Mike White
14
Mark Andrews Bal, TE
San Giacomos Frannys Fanny
Round 3
NO.
Player
Team
1
Mike Evans TB, WR
San Giacomos Frannys Fanny
2
Breece Hall NYJ, RB
Mike White
3
Nick Chubb Cle, RB
Broncos Country Lets Ride!
4
Ezekiel Elliott FA, RB
AnaKen skyWalker
5
Michael Pittman Jr. Ind, WR
Tiger King
6
DJ Moore Chi, WR
Nicholas Cruz's
7
Cam Akers LAR, RB
The Minutemen ︻デ═一
8
A.J. Brown Phi, WR
Rolls With butter
9
Terry McLaurin Wsh, WR
Tony Fkn Romo
10
Diontae Johnson Pit, WR
U SHOULDVE GONE FOR THE HEAD
11
Mike Williams LAC, WR
. Dan Washburn
12
Chris Godwin TB, WR
The Less Fourtunette
13
J.K. Dobbins Bal, RB
Chi Town Murder Suicide?
14
Josh Jacobs LV, RB
N.Y. Routensss
Round 4
NO.
Player
Team
1
DK Metcalf Sea, WR
N.Y. Routensss
2
Antonio Gibson Wsh, RB
Chi Town Murder Suicide?
3
Josh Allen Buf, QB
The Less Fourtunette
4
Kyle Pitts Atl, TE
. Dan Washburn
5
Michael Thomas NO, WR
U SHOULDVE GONE FOR THE HEAD
6
Elijah Mitchell SF, RB
Tony Fkn Romo
7
Travis Etienne Jr. Jax, RB
Rolls With butter
8
Amon-Ra St. Brown Det, WR
The Minutemen ︻デ═一
9
Darnell Mooney Chi, WR
Nicholas Cruz's
10
Courtland Sutton Den, WR
Tiger King
11
Brandin Cooks Dal, WR
AnaKen skyWalker
12
Jerry Jeudy Den, WR
Broncos Country Lets Ride!
13
Adam Thielen FA, WR
Mike White
14
Amari Cooper Cle, WR
San Giacomos Frannys Fanny
Round 5
NO.
Player
Team
1
Cordarrelle Patterson Atl, RB
San Giacomos Frannys Fanny
2
JuJu Smith-Schuster NE, WR
Mike White
3
Allen Robinson II LAR, WR
Broncos Country Lets Ride!
4
Darren Waller NYG, TE
AnaKen skyWalker
5
Rashod Bateman Bal, WR
Tiger King
6
Marquise Brown Ari, WR
Nicholas Cruz's
7
Miles Sanders Car, RB
The Minutemen ︻デ═一
8
George Kittle SF, TE
Rolls With butter
9
Patrick Mahomes KC, QB
Tony Fkn Romo
10
Justin Herbert LAC, QB
U SHOULDVE GONE FOR THE HEAD
11
Lamar Jackson Bal, QB
. Dan Washburn
12
Kareem Hunt Cle, RB
The Less Fourtunette
13
Kyler Murray Ari, QB
Chi Town Murder Suicide?
14
Jalen Hurts Phi, QB
N.Y. Routensss
Round 6
NO.
Player
Team
1
Gabe Davis Buf, WR
N.Y. Routensss
2
Drake London Atl, WR
Chi Town Murder Suicide?
3
Dalton Schultz Hou, TE
The Less Fourtunette
4
DeVonta Smith Phi, WR
. Dan Washburn
5
DeAndre Hopkins Ari, WR
U SHOULDVE GONE FOR THE HEAD
6
Tyler Lockett Sea, WR
Tony Fkn Romo
7
Allen Lazard NYJ, WR
Rolls With butter
8
T.J. Hockenson Min, TE
The Minutemen ︻デ═一
9
Rashaad Penny Phi, RB
Nicholas Cruz's
10
AJ Dillon GB, RB
Tiger King
11
Tom Brady TB, QB
AnaKen skyWalker
12
Russell Wilson Den, QB
Broncos Country Lets Ride!
13
Elijah Moore NYJ, WR
Mike White
14
Dak Prescott Dal, QB
San Giacomos Frannys Fanny
Round 7
NO.
Player
Team
1
Chase Edmonds TB, RB
San Giacomos Frannys Fanny
2
Clyde Edwards-Helaire KC, RB
Mike White
3
Hunter Renfrow LV, WR
Broncos Country Lets Ride!
4
Tony Pollard Dal, RB
AnaKen skyWalker
5
Joe Burrow Cin, QB
Tiger King
6
Matthew Stafford LAR, QB
Nicholas Cruz's
7
Garrett Wilson NYJ, WR
The Minutemen ︻デ═一
8
Brandon Aiyuk SF, WR
Rolls With butter
9
Dallas Goedert Phi, TE
Tony Fkn Romo
10
Zach Ertz Ari, TE
U SHOULDVE GONE FOR THE HEAD
11
Chris Olave NO, WR
. Dan Washburn
12
Chase Claypool Chi, WR
The Less Fourtunette
13
Mike Gesicki NE, TE
Chi Town Murder Suicide?
14
Hunter Henry NE, TE
N.Y. Routensss
Round 8
NO.
Player
Team
1
Christian Kirk Jax, WR
N.Y. Routensss
2
Treylon Burks Ten, WR
Chi Town Murder Suicide?
3
Robert Woods FA, WR
The Less Fourtunette
4
Russell Gage TB, WR
. Dan Washburn
5
Skyy Moore KC, WR
U SHOULDVE GONE FOR THE HEAD
6
Devin Singletary Hou, RB
Tony Fkn Romo
7
Aaron Rodgers GB, QB
Rolls With butter
8
Zach Wilson NYJ, QB
The Minutemen ︻デ═一
9
Kadarius Toney KC, WR
Nicholas Cruz's
10
James Robinson NE, RB
Tiger King
11
Christian Watson GB, WR
AnaKen skyWalker
12
Jakobi Meyers LV, WR
Broncos Country Lets Ride!
13
Damien Harris Buf, RB
Mike White
14
Trey Lance SF, QB
San Giacomos Frannys Fanny
Round 9
NO.
Player
Team
1
Kenny Golladay FA, WR
San Giacomos Frannys Fanny
2
Pat Freiermuth Pit, TE
Mike White
3
James Cook Buf, RB
Broncos Country Lets Ride!
4
Kenneth Walker III Sea, RB
AnaKen skyWalker
5
Rhamondre Stevenson NE, RB
Tiger King
6
Raheem Mostert Mia, RB
Nicholas Cruz's
7
Derek Carr NO, QB
The Minutemen ︻デ═一
8
Alexander Mattison Min, RB
Rolls With butter
9
Jarvis Landry NO, WR
Tony Fkn Romo
10
Isaiah Spiller LAC, RB
U SHOULDVE GONE FOR THE HEAD
11
Jamaal Williams NO, RB
. Dan Washburn
12
Melvin Gordon III FA, RB
The Less Fourtunette
13
Michael Carter NYJ, RB
Chi Town Murder Suicide?
14
Nyheim Hines Buf, RB
N.Y. Routensss
Round 10
NO.
Player
Team
1
Tyler Boyd Cin, WR
N.Y. Routensss
2
Robbie Anderson FA, WR
Chi Town Murder Suicide?
3
Marvin Jones Jr. Jax, WR
The Less Fourtunette
4
Irv Smith Jr. Min, TE
. Dan Washburn
5
Jahan Dotson Wsh, WR
U SHOULDVE GONE FOR THE HEAD
6
Bills D/ST Buf, D/ST
Tony Fkn Romo
7
George Pickens Pit, WR
Rolls With butter
8
Marquez Valdes-Scantling KC, WR
The Minutemen ︻デ═一
9
Dawson Knox Buf, TE
Nicholas Cruz's
10
Tua Tagovailoa Mia, QB
Tiger King
11
Dameon Pierce Hou, RB
AnaKen skyWalker
12
Chuba Hubbard Car, RB
Broncos Country Lets Ride!
13
Michael Gallup Dal, WR
Mike White
14
Mecole Hardman KC, WR
San Giacomos Frannys Fanny
Round 11
NO.
Player
Team
1
Packers D/ST GB, D/ST
San Giacomos Frannys Fanny
2
Trevor Lawrence Jax, QB
Mike White
3
Jalen Tolbert Dal, WR
Broncos Country Lets Ride!
4
Tyler Allgeier Atl, RB
AnaKen skyWalker
5
Jameson Williams Det, WR
Tiger King
6
DJ Chark Det, WR
Nicholas Cruz's
7
Marlon Mack Den, RB
The Minutemen ︻デ═一
8
Julio Jones TB, WR
Rolls With butter
9
Noah Fant Sea, TE
Tony Fkn Romo
10
Rachaad White TB, RB
U SHOULDVE GONE FOR THE HEAD
11
Nico Collins Hou, WR
. Dan Washburn
12
Saints D/ST NO, D/ST
The Less Fourtunette
13
Ravens D/ST Bal, D/ST
Chi Town Murder Suicide?
14
Cole Kmet Chi, TE
N.Y. Routensss
Round 12
NO.
Player
Team
1
Buccaneers D/ST TB, D/ST
N.Y. Routensss
2
J.D. McKissic FA, RB
Chi Town Murder Suicide?
3
Justin Tucker Bal, K
The Less Fourtunette
4
49ers D/ST SF, D/ST
. Dan Washburn
5
Alec Pierce Ind, WR
U SHOULDVE GONE FOR THE HEAD
6
Harrison Butker KC, K
Tony Fkn Romo
7
Joshua Palmer LAC, WR
Rolls With butter
8
Colts D/ST Ind, D/ST
The Minutemen ︻デ═一
9
Evan McPherson Cin, K
Nicholas Cruz's
10
David Njoku Cle, TE
Tiger King
11
Matt Gay Ind, K
AnaKen skyWalker
12
Cowboys D/ST Dal, D/ST
Broncos Country Lets Ride!
13
Logan Thomas Wsh, TE
Mike White
14
Kirk Cousins Min, QB
San Giacomos Frannys Fanny
Round 13
NO.
Player
Team
1
Daniel Carlson LV, K
San Giacomos Frannys Fanny
2
Evan Engram Jax, TE
Mike White
3
Brandon McManus Den, K
Broncos Country Lets Ride!
4
Ronald Jones KC, RB
AnaKen skyWalker
5
Darrell Henderson Jr. FA, RB
Tiger King
6
Chargers D/ST LAC, D/ST
Nicholas Cruz's
7
Tyler Bass Buf, K
The Minutemen ︻デ═一
8
Commanders D/ST Wsh, D/ST
Rolls With butter
9
Tyler Higbee LAR, TE
Tony Fkn Romo
10
Odell Beckham Jr. FA, WR
U SHOULDVE GONE FOR THE HEAD
11
Matt Prater Ari, K
. Dan Washburn
12
Steelers D/ST Pit, D/ST
The Less Fourtunette
13
Nick Folk NE, K
Chi Town Murder Suicide?
14
Graham Gano NYG, K
N.Y. Routensss
Round 14
NO.
Player
Team
1
DeVante Parker NE, WR
N.Y. Routensss
2
Curtis Samuel Wsh, WR
Chi Town Murder Suicide?
3
Van Jefferson LAR, WR
The Less Fourtunette
4
Justin Fields Chi, QB
. Dan Washburn
5
Deshaun Watson Cle, QB
U SHOULDVE GONE FOR THE HEAD
6
Kenyan Drake Bal, RB
Tony Fkn Romo
7
Jerick McKinnon KC, RB
Rolls With butter
8
Kenneth Gainwell Phi, RB
The Minutemen ︻デ═一
9
Mark Ingram II NO, RB
Nicholas Cruz's
10
Greg Joseph Min, K
Tiger King
11
Ryan Tannehill Ten, QB
AnaKen skyWalker
12
Rondale Moore Ari, WR
Broncos Country Lets Ride!
13
Jameis Winston NO, QB
Mike White
14
Gus Edwards Bal, RB
San Giacomos Frannys Fanny
Round 15
NO.
Player
Team
1
Daniel Jones NYG, QB
San Giacomos Frannys Fanny
2
Younghoe Koo Atl, K
Mike White
3
Carson Wentz FA, QB
Broncos Country Lets Ride!
4
Browns D/ST Cle, D/ST
AnaKen skyWalker
5
Brian Robinson Jr. Wsh, RB
Tiger King
6
Sterling Shepard NYG, WR
Nicholas Cruz's
7
Jamison Crowder Buf, WR
The Minutemen ︻デ═一
8
Jake Elliott Phi, K
Rolls With butter
9
KJ Hamler Den, WR
Tony Fkn Romo
10
Patriots D/ST NE, D/ST
U SHOULDVE GONE FOR THE HEAD
11
Hayden Hurst Car, TE
. Dan Washburn
12
Austin Hooper Ten, TE
The Less Fourtunette
13
Nick Westbrook-Ikhine Ten, WR
Chi Town Murder Suicide?
14
Corey Davis NYJ, WR
N.Y. Routensss
Round 16
NO.
Player
Team
1
Sammy Watkins Bal, WR
N.Y. Routensss
2
Kendrick Bourne NE, WR
Chi Town Murder Suicide?
3
Sony Michel FA, RB
The Less Fourtunette
4
Cade York Cle, K
. Dan Washburn
5
Dustin Hopkins LAC, K
U SHOULDVE GONE FOR THE HEAD
6
Rex Burkhead Hou, RB
Tony Fkn Romo
7
Darrel Williams Ari, RB
Rolls With butter
8
Robert Tonyan Chi, TE
The Minutemen ︻デ═一
9
Dontrell Hilliard Ten, RB
Nicholas Cruz's
10
Dolphins D/ST Mia, D/ST
Tiger King
11
Khalil Herbert Chi, RB
AnaKen skyWalker
12
Cole Beasley Buf, WR
Broncos Country Lets Ride!
13
Titans D/ST Ten, D/ST
Mike White
14
James White NE, RB
San Giacomos Frannys Fanny
"""

raw_2023 = """
Round 1
NO.
Player
Team
1
Justin Jefferson Min, WR
The Koo Dynasty
2
Christian McCaffrey SF, RB
Oh He Likes Cooking!
3
Ja'Marr Chase Cin, WR
THERE IS NO DOOR NUMBER FOUR
4
Austin Ekeler Wsh, RB
Allgeier Season
5
Travis Kelce KC, TE
Tony Fkn Romo
6
Cooper Kupp LAR, WR
Pickett to Pickens
7
Tyreek Hill Mia, WR
San Giacomos Frannys Fanny
8
Bijan Robinson Atl, RB
Rolls With butter
9
Saquon Barkley Phi, RB
Run Gibbs Fraud Ford
10
Davante Adams LV, WR
Free Kyle Pitts
11
Derrick Henry Bal, RB
Addison Square Garden
12
Stefon Diggs Buf, WR
The Minutemen ︻デ═一
13
CeeDee Lamb Dal, WR
Thank You Max!
14
Josh Jacobs GB, RB
N.Y. Routensss
Round 2
NO.
Player
Team
1
Nick Chubb Cle, RB
N.Y. Routensss
2
Tony Pollard Ten, RB
Thank You Max!
3
Jonathan Taylor Ind, RB
The Minutemen ︻デ═一
4
Amon-Ra St. Brown Det, WR
Addison Square Garden
5
A.J. Brown Phi, WR
Free Kyle Pitts
6
Garrett Wilson NYJ, WR
Run Gibbs Fraud Ford
7
Jaylen Waddle Mia, WR
Rolls With butter
8
Joe Mixon Hou, RB
San Giacomos Frannys Fanny
9
DK Metcalf Sea, WR
Pickett to Pickens
10
Travis Etienne Jr. Jax, RB
Tony Fkn Romo
11
Jahmyr Gibbs Det, RB
Allgeier Season
12
Rhamondre Stevenson NE, RB
THERE IS NO DOOR NUMBER FOUR
13
Mark Andrews Bal, TE
Oh He Likes Cooking!
14
Breece Hall NYJ, RB
The Koo Dynasty
Round 3
NO.
Player
Team
1
Aaron Jones Min, RB
The Koo Dynasty
2
DeVonta Smith Phi, WR
Oh He Likes Cooking!
3
Najee Harris Pit, RB
THERE IS NO DOOR NUMBER FOUR
4
Dameon Pierce Hou, RB
Allgeier Season
5
Chris Olave NO, WR
Tony Fkn Romo
6
Rachaad White TB, RB
Pickett to Pickens
7
Deebo Samuel SF, WR
San Giacomos Frannys Fanny
8
Patrick Mahomes KC, QB
Rolls With butter
9
Josh Allen Buf, QB
Run Gibbs Fraud Ford
10
Miles Sanders Car, RB
Free Kyle Pitts
11
Jalen Hurts Phi, QB
Addison Square Garden
12
Tee Higgins Cin, WR
The Minutemen ︻デ═一
13
Calvin Ridley Ten, WR
Thank You Max!
14
Jerry Jeudy Cle, WR
N.Y. Routensss
Round 4
NO.
Player
Team
1
Lamar Jackson Bal, QB
N.Y. Routensss
2
T.J. Hockenson Min, TE
Thank You Max!
3
Joe Burrow Cin, QB
The Minutemen ︻デ═一
4
Keenan Allen Chi, WR
Addison Square Garden
5
Amari Cooper Cle, WR
Free Kyle Pitts
6
Darren Waller NYG, TE
Run Gibbs Fraud Ford
7
Alexander Mattison LV, RB
Rolls With butter
8
Alvin Kamara NO, RB
San Giacomos Frannys Fanny
9
Christian Watson GB, WR
Pickett to Pickens
10
Terry McLaurin Wsh, WR
Tony Fkn Romo
11
DeAndre Hopkins Ten, WR
Allgeier Season
12
Justin Fields Pit, QB
THERE IS NO DOOR NUMBER FOUR
13
Justin Herbert LAC, QB
Oh He Likes Cooking!
14
Kenneth Walker III Sea, RB
The Koo Dynasty
Round 5
NO.
Player
Team
1
Cam Akers Min, RB
The Koo Dynasty
2
Mike Evans TB, WR
Oh He Likes Cooking!
3
George Kittle SF, TE
THERE IS NO DOOR NUMBER FOUR
4
Marquise Brown KC, WR
Allgeier Season
5
Tyler Lockett Sea, WR
Tony Fkn Romo
6
James Conner Ari, RB
Pickett to Pickens
7
Diontae Johnson Car, WR
San Giacomos Frannys Fanny
8
Brandon Aiyuk SF, WR
Rolls With butter
9
DJ Moore Chi, WR
Run Gibbs Fraud Ford
10
Kyle Pitts Atl, TE
Free Kyle Pitts
11
Javonte Williams Den, RB
Addison Square Garden
12
Isiah Pacheco KC, RB
The Minutemen ︻デ═一
13
James Cook Buf, RB
Thank You Max!
14
Dallas Goedert Phi, TE
N.Y. Routensss
Round 6
NO.
Player
Team
1
Chris Godwin TB, WR
N.Y. Routensss
2
Mike Williams NYJ, WR
Thank You Max!
3
Michael Pittman Jr. Ind, WR
The Minutemen ︻デ═一
4
Evan Engram Jax, TE
Addison Square Garden
5
David Montgomery Det, RB
Free Kyle Pitts
6
D'Andre Swift Chi, RB
Run Gibbs Fraud Ford
7
Drake London Atl, WR
Rolls With butter
8
David Njoku Cle, TE
San Giacomos Frannys Fanny
9
George Pickens Pit, WR
Pickett to Pickens
10
J.K. Dobbins Bal, RB
Tony Fkn Romo
11
Trevor Lawrence Jax, QB
Allgeier Season
12
Christian Kirk Jax, WR
THERE IS NO DOOR NUMBER FOUR
13
Michael Thomas NO, WR
Oh He Likes Cooking!
14
Aaron Rodgers NYJ, QB
The Koo Dynasty
Round 7
NO.
Player
Team
1
Brandin Cooks Dal, WR
The Koo Dynasty
2
Dalvin Cook Bal, RB
Oh He Likes Cooking!
3
Jaxon Smith-Njigba Sea, WR
THERE IS NO DOOR NUMBER FOUR
4
Pat Freiermuth Pit, TE
Allgeier Season
5
Dak Prescott Dal, QB
Tony Fkn Romo
6
Deshaun Watson Cle, QB
Pickett to Pickens
7
Kirk Cousins Atl, QB
San Giacomos Frannys Fanny
8
Jahan Dotson Wsh, WR
Rolls With butter
9
Skyy Moore KC, WR
Run Gibbs Fraud Ford
10
Jamaal Williams NO, RB
Free Kyle Pitts
11
Jordan Addison Min, WR
Addison Square Garden
12
Brian Robinson Jr. Wsh, RB
The Minutemen ︻デ═一
13
Courtland Sutton Den, WR
Thank You Max!
14
Odell Beckham Jr. FA, WR
N.Y. Routensss
Round 8
NO.
Player
Team
1
Treylon Burks Ten, WR
N.Y. Routensss
2
Geno Smith Sea, QB
Thank You Max!
3
Tyler Higbee LAR, TE
The Minutemen ︻デ═一
4
JuJu Smith-Schuster NE, WR
Addison Square Garden
5
Tua Tagovailoa Mia, QB
Free Kyle Pitts
6
Khalil Herbert Chi, RB
Run Gibbs Fraud Ford
7
Dalton Schultz Hou, TE
Rolls With butter
8
AJ Dillon GB, RB
San Giacomos Frannys Fanny
9
Cole Kmet Chi, TE
Pickett to Pickens
10
Samaje Perine Den, RB
Tony Fkn Romo
11
Elijah Moore Cle, WR
Allgeier Season
12
Antonio Gibson NE, RB
THERE IS NO DOOR NUMBER FOUR
13
Zay Flowers Bal, WR
Oh He Likes Cooking!
14
Quentin Johnston LAC, WR
The Koo Dynasty
Round 9
NO.
Player
Team
1
Kyler Murray Ari, QB
The Koo Dynasty
2
Rashaad Penny Phi, RB
Oh He Likes Cooking!
3
Rondale Moore Atl, WR
THERE IS NO DOOR NUMBER FOUR
4
Chase Claypool Mia, WR
Allgeier Season
5
Jakobi Meyers LV, WR
Tony Fkn Romo
6
Jeff Wilson Jr. Mia, RB
Pickett to Pickens
7
Zay Jones Jax, WR
San Giacomos Frannys Fanny
8
DJ Chark Jr. Car, WR
Rolls With butter
9
Gabe Davis Jax, WR
Run Gibbs Fraud Ford
10
Jerick McKinnon KC, RB
Free Kyle Pitts
11
Darnell Mooney Atl, WR
Addison Square Garden
12
Adam Thielen Car, WR
The Minutemen ︻デ═一
13
Zach Charbonnet Sea, RB
Thank You Max!
14
Tyler Boyd Cin, WR
N.Y. Routensss
Round 10
NO.
Player
Team
1
Damien Harris Buf, RB
N.Y. Routensss
2
Allen Lazard NYJ, WR
Thank You Max!
3
Steelers D/ST Pit, D/ST
The Minutemen ︻デ═一
4
49ers D/ST SF, D/ST
Addison Square Garden
5
Nico Collins Hou, WR
Free Kyle Pitts
6
Rashod Bateman Bal, WR
Run Gibbs Fraud Ford
7
Anthony Richardson Ind, QB
Rolls With butter
8
Dolphins D/ST Mia, D/ST
San Giacomos Frannys Fanny
9
Bills D/ST Buf, D/ST
Pickett to Pickens
10
Greg Dulcich Den, TE
Tony Fkn Romo
11
Tyler Allgeier Atl, RB
Allgeier Season
12
Daniel Jones NYG, QB
THERE IS NO DOOR NUMBER FOUR
13
Kendre Miller NO, RB
Oh He Likes Cooking!
14
Kadarius Toney KC, WR
The Koo Dynasty
Round 11
NO.
Player
Team
1
Jonathan Mingo Car, WR
The Koo Dynasty
2
Cowboys D/ST Dal, D/ST
Oh He Likes Cooking!
3
Jameson Williams Det, WR
THERE IS NO DOOR NUMBER FOUR
4
Rashee Rice KC, WR
Allgeier Season
5
Saints D/ST NO, D/ST
Tony Fkn Romo
6
Michael Gallup Dal, WR
Pickett to Pickens
7
Justin Tucker Bal, K
San Giacomos Frannys Fanny
8
Isaiah Hodgins NYG, WR
Rolls With butter
9
Curtis Samuel Buf, WR
Run Gibbs Fraud Ford
10
Jets D/ST NYJ, D/ST
Free Kyle Pitts
11
Evan McPherson Cin, K
Addison Square Garden
12
Robert Woods Hou, WR
The Minutemen ︻デ═一
13
Browns D/ST Cle, D/ST
Thank You Max!
14
Russell Wilson Pit, QB
N.Y. Routensss
Round 12
NO.
Player
Team
1
Tank Bigsby Jax, RB
N.Y. Routensss
2
Jake Elliott Phi, K
Thank You Max!
3
Elijah Mitchell SF, RB
The Minutemen ︻デ═一
4
Matthew Stafford LAR, QB
Addison Square Garden
5
De'Von Achane Mia, RB
Free Kyle Pitts
6
Chigoziem Okonkwo Ten, TE
Run Gibbs Fraud Ford
7
Jaylen Warren Pit, RB
Rolls With butter
8
Donovan Peoples-Jones Det, WR
San Giacomos Frannys Fanny
9
Graham Gano NYG, K
Pickett to Pickens
10
Younghoe Koo Atl, K
Tony Fkn Romo
11
D'Onta Foreman Cle, RB
Allgeier Season
12
Daniel Carlson LV, K
THERE IS NO DOOR NUMBER FOUR
13
Jayden Reed GB, WR
Oh He Likes Cooking!
14
Dalton Kincaid Buf, TE
The Koo Dynasty
Round 13
NO.
Player
Team
1
Mecole Hardman KC, WR
The Koo Dynasty
2
Jerome Ford Cle, RB
Oh He Likes Cooking!
3
Parris Campbell Phi, WR
THERE IS NO DOOR NUMBER FOUR
4
Patriots D/ST NE, D/ST
Allgeier Season
5
Justyn Ross KC, WR
Tony Fkn Romo
6
Raheem Mostert Mia, RB
Pickett to Pickens
7
Devin Singletary NYG, RB
San Giacomos Frannys Fanny
8
Joshua Kelley LAC, RB
Rolls With butter
9
Allen Robinson II Pit, WR
Run Gibbs Fraud Ford
10
Marquez Valdes-Scantling KC, WR
Free Kyle Pitts
11
Tyquan Thornton NE, WR
Addison Square Garden
12
Cameron Dicker LAC, K
The Minutemen ︻デ═一
13
Gus Edwards LAC, RB
Thank You Max!
14
Packers D/ST GB, D/ST
N.Y. Routensss
Round 14
NO.
Player
Team
1
Ezekiel Elliott NE, RB
N.Y. Routensss
2
John Metchie III Hou, WR
Thank You Max!
3
Sam LaPorta Det, TE
The Minutemen ︻デ═一
4
Sterling Shepard NYG, WR
Addison Square Garden
5
Harrison Butker KC, K
Free Kyle Pitts
6
Bryce Young Car, QB
Run Gibbs Fraud Ford
7
Romeo Doubs GB, WR
Rolls With butter
8
Kyren Williams LAR, RB
San Giacomos Frannys Fanny
9
Kenny Pickett Phi, QB
Pickett to Pickens
10
Leonard Fournette Buf, RB
Tony Fkn Romo
11
Tyjae Spears Ten, RB
Allgeier Season
12
Chuba Hubbard Car, RB
THERE IS NO DOOR NUMBER FOUR
13
Josh Downs Ind, WR
Oh He Likes Cooking!
14
Zach Ertz Wsh, TE
The Koo Dynasty
Round 15
NO.
Player
Team
1
Ravens D/ST Bal, D/ST
The Koo Dynasty
2
K.J. Osborn NE, WR
Oh He Likes Cooking!
3
Gerald Everett Chi, TE
THERE IS NO DOOR NUMBER FOUR
4
Marvin Mims Jr. Den, WR
Allgeier Season
5
Michael Carter Ari, RB
Tony Fkn Romo
6
Jason Myers Sea, K
Pickett to Pickens
7
Hunter Renfrow LV, WR
San Giacomos Frannys Fanny
8
Commanders D/ST Wsh, D/ST
Rolls With butter
9
Eagles D/ST Phi, D/ST
Run Gibbs Fraud Ford
10
Alec Pierce Ind, WR
Free Kyle Pitts
11
Mack Hollins Buf, WR
Addison Square Garden
12
Van Jefferson Pit, WR
The Minutemen ︻デ═一
13
Marvin Jones Jr. FA, WR
Thank You Max!
14
Tyler Bass Buf, K
N.Y. Routensss
Round 16
NO.
Player
Team
1
Matt Gay Ind, K
N.Y. Routensss
2
Michael Wilson Ari, WR
Thank You Max!
3
Jordan Love GB, QB
The Minutemen ︻デ═一
4
Cordarrelle Patterson Atl, RB
Addison Square Garden
5
Roschon Johnson Chi, RB
Free Kyle Pitts
6
Greg Zuerlein NYJ, K
Run Gibbs Fraud Ford
7
Greg Joseph Min, K
Rolls With butter
8
Clyde Edwards-Helaire KC, RB
San Giacomos Frannys Fanny
9
Eddy Pineiro Car, K
Pickett to Pickens
10
Chase Edmonds TB, RB
Tony Fkn Romo
11
Brandon McManus Wsh, K
Allgeier Season
12
Seahawks D/ST Sea, D/ST
THERE IS NO DOOR NUMBER FOUR
13
Brett Maher LAR, K
Oh He Likes Cooking!
14
Jake Moody SF, K
The Koo Dynasty
"""

raw_2024 = """
Round 1
NO.
Player
Team
1
Christian McCaffrey SF, RB
N.Y. Routensss
2
CeeDee Lamb Dal, WR
JOSH JACOBS FAN CLUB
3
Tyreek Hill Mia, WR
LeGoon
4
Breece Hall NYJ, RB
Rolls With Butter
5
Bijan Robinson Atl, RB
Set Pitts Free
6
Amon-Ra St. Brown Det, WR
STATION GRITS
7
Ja'Marr Chase Cin, WR
Glass of Charbonnet
8
Justin Jefferson Min, WR
The Minutemen ︻デ═一
9
Garrett Wilson NYJ, WR
Kittle Me This
10
Jonathan Taylor Ind, RB
Tee Time
11
A.J. Brown Phi, WR
Oh He Likes Cooking!
12
Saquon Barkley Phi, RB
Dent.
13
Isiah Pacheco KC, RB
LaPorta Potty
14
Marvin Harrison Jr. Ari, WR
Tony Fkn Romo
Round 2
NO.
Player
Team
1
Jahmyr Gibbs Det, RB
Tony Fkn Romo
2
Travis Etienne Jr. Jax, RB
LaPorta Potty
3
Derrick Henry Bal, RB
Dent.
4
James Cook Buf, RB
Oh He Likes Cooking!
5
Kyren Williams LAR, RB
Tee Time
6
Chris Olave NO, WR
Kittle Me This
7
Rachaad White TB, RB
The Minutemen ︻デ═一
8
Michael Pittman Jr. Ind, WR
Glass of Charbonnet
9
Puka Nacua LAR, WR
STATION GRITS
10
Nico Collins Hou, WR
Set Pitts Free
11
Mike Evans TB, WR
Rolls With Butter
12
Drake London Atl, WR
LeGoon
13
Josh Jacobs GB, RB
JOSH JACOBS FAN CLUB
14
Alvin Kamara NO, RB
N.Y. Routensss
Round 3
NO.
Player
Team
1
Deebo Samuel Sr. Wsh, WR
N.Y. Routensss
2
Davante Adams LAR, WR
JOSH JACOBS FAN CLUB
3
Brandon Aiyuk SF, WR
LeGoon
4
Jaylen Waddle Mia, WR
Rolls With Butter
5
DJ Moore Chi, WR
Set Pitts Free
6
De'Von Achane Mia, RB
STATION GRITS
7
Kenneth Walker III Sea, RB
Glass of Charbonnet
8
DK Metcalf Pit, WR
The Minutemen ︻デ═一
9
DeVonta Smith Phi, WR
Kittle Me This
10
Travis Kelce KC, TE
Tee Time
11
Cooper Kupp Sea, WR
Oh He Likes Cooking!
12
Malik Nabers NYG, WR
Dent.
13
Rashee Rice KC, WR
LaPorta Potty
14
Joe Mixon Hou, RB
Tony Fkn Romo
Round 4
NO.
Player
Team
1
Stefon Diggs Hou, WR
Tony Fkn Romo
2
Sam LaPorta Det, TE
LaPorta Potty
3
Josh Allen Buf, QB
Dent.
4
Trey McBride Ari, TE
Oh He Likes Cooking!
5
Tee Higgins Cin, WR
Tee Time
6
Jalen Hurts Phi, QB
Kittle Me This
7
Lamar Jackson Bal, QB
The Minutemen ︻デ═一
8
Patrick Mahomes KC, QB
Glass of Charbonnet
9
Anthony Richardson Ind, QB
STATION GRITS
10
C.J. Stroud Hou, QB
Set Pitts Free
11
Zay Flowers Bal, WR
Rolls With Butter
12
Joe Burrow Cin, QB
LeGoon
13
George Pickens Pit, WR
JOSH JACOBS FAN CLUB
14
Kyler Murray Ari, QB
N.Y. Routensss
Round 5
NO.
Player
Team
1
Mark Andrews Bal, TE
N.Y. Routensss
2
Evan Engram Den, TE
JOSH JACOBS FAN CLUB
3
Zamir White LV, RB
LeGoon
4
James Conner Ari, RB
Rolls With Butter
5
D'Andre Swift Chi, RB
Set Pitts Free
6
Aaron Jones Min, RB
STATION GRITS
7
Rhamondre Stevenson NE, RB
Glass of Charbonnet
8
David Montgomery Det, RB
The Minutemen ︻デ═一
9
George Kittle SF, TE
Kittle Me This
10
Calvin Ridley Ten, WR
Tee Time
11
Diontae Johnson Bal, WR
Oh He Likes Cooking!
12
Dalton Kincaid Buf, TE
Dent.
13
Amari Cooper Buf, WR
LaPorta Potty
14
Dak Prescott Dal, QB
Tony Fkn Romo
Round 6
NO.
Player
Team
1
Chris Godwin TB, WR
Tony Fkn Romo
2
Terry McLaurin Wsh, WR
LaPorta Potty
3
Keenan Allen Chi, WR
Dent.
4
Tank Dell Hou, WR
Oh He Likes Cooking!
5
Christian Kirk Hou, WR
Tee Time
6
Javonte Williams Dal, RB
Kittle Me This
7
Christian Watson GB, WR
The Minutemen ︻デ═一
8
Courtland Sutton Den, WR
Glass of Charbonnet
9
Kyle Pitts Atl, TE
STATION GRITS
10
Jake Ferguson Dal, TE
Set Pitts Free
11
Jaxon Smith-Njigba Sea, WR
Rolls With Butter
12
Brian Robinson Jr. Wsh, RB
LeGoon
13
Tony Pollard Ten, RB
JOSH JACOBS FAN CLUB
14
Jayden Reed GB, WR
N.Y. Routensss
Round 7
NO.
Player
Team
1
Xavier Worthy KC, WR
N.Y. Routensss
2
Jordan Love GB, QB
JOSH JACOBS FAN CLUB
3
Jordan Addison Min, WR
LeGoon
4
Najee Harris LAC, RB
Rolls With Butter
5
Brian Thomas Jr. Jax, WR
Set Pitts Free
6
Ladd McConkey LAC, WR
STATION GRITS
7
Keon Coleman Buf, WR
Glass of Charbonnet
8
David Njoku Cle, TE
The Minutemen ︻デ═一
9
Jaylen Warren Pit, RB
Kittle Me This
10
Aaron Rodgers FA, QB
Tee Time
11
Jonathon Brooks Car, RB
Oh He Likes Cooking!
12
Raheem Mostert LV, RB
Dent.
13
Hollywood Brown KC, WR
LaPorta Potty
14
Rome Odunze Chi, WR
Tony Fkn Romo
Round 8
NO.
Player
Team
1
Dallas Goedert Phi, TE
Tony Fkn Romo
2
Brock Purdy SF, QB
LaPorta Potty
3
Jerome Ford Cle, RB
Dent.
4
Chuba Hubbard Car, RB
Oh He Likes Cooking!
5
Austin Ekeler Wsh, RB
Tee Time
6
Tyjae Spears Ten, RB
Kittle Me This
7
Mike Williams LAC, WR
The Minutemen ︻デ═一
8
Brock Bowers LV, TE
Glass of Charbonnet
9
Tyler Lockett FA, WR
STATION GRITS
10
Nick Chubb Cle, RB
Set Pitts Free
11
Dalton Schultz Hou, TE
Rolls With Butter
12
T.J. Hockenson Min, TE
LeGoon
13
Devin Singletary NYG, RB
JOSH JACOBS FAN CLUB
14
Ravens D/ST Bal, D/ST
N.Y. Routensss
Round 9
NO.
Player
Team
1
Chase Brown Cin, RB
N.Y. Routensss
2
Khalil Shakir Buf, WR
JOSH JACOBS FAN CLUB
3
Ezekiel Elliott FA, RB
LeGoon
4
Caleb Williams Chi, QB
Rolls With Butter
5
Jerry Jeudy Cle, WR
Set Pitts Free
6
Zack Moss Cin, RB
STATION GRITS
7
Zach Charbonnet Sea, RB
Glass of Charbonnet
8
J.K. Dobbins LAC, RB
The Minutemen ︻デ═一
9
DeAndre Hopkins Bal, WR
Kittle Me This
10
Jayden Daniels Wsh, QB
Tee Time
11
Trey Benson Ari, RB
Oh He Likes Cooking!
12
Jakobi Meyers LV, WR
Dent.
13
Blake Corum LAR, RB
LaPorta Potty
14
Jameson Williams Det, WR
Tony Fkn Romo
Round 10
NO.
Player
Team
1
Gus Edwards FA, RB
Tony Fkn Romo
2
Jordan Mason Min, RB
LaPorta Potty
3
DeMario Douglas NE, WR
Dent.
4
Trevor Lawrence Jax, QB
Oh He Likes Cooking!
5
Justin Herbert LAC, QB
Tee Time
6
Tyler Allgeier Atl, RB
Kittle Me This
7
Darnell Mooney Atl, WR
The Minutemen ︻デ═一
8
Ja'Lynn Polk NE, WR
Glass of Charbonnet
9
Deshaun Watson Cle, QB
STATION GRITS
10
Rico Dowdle Car, RB
Set Pitts Free
11
Jaleel McLaughlin Den, RB
Rolls With Butter
12
Gabe Davis Jax, WR
LeGoon
13
Romeo Doubs GB, WR
JOSH JACOBS FAN CLUB
14
Rashid Shaheed NO, WR
N.Y. Routensss
Round 11
NO.
Player
Team
1
Antonio Gibson NE, RB
N.Y. Routensss
2
Brandon Aubrey Dal, K
JOSH JACOBS FAN CLUB
3
Pat Freiermuth Pit, TE
LeGoon
4
Ty Chandler Min, RB
Rolls With Butter
5
Curtis Samuel Buf, WR
Set Pitts Free
6
Adam Thielen Car, WR
STATION GRITS
7
Xavier Legette Car, WR
Glass of Charbonnet
8
Browns D/ST Cle, D/ST
The Minutemen ︻デ═一
9
Tua Tagovailoa Mia, QB
Kittle Me This
10
Brandin Cooks Dal, WR
Tee Time
11
Jaylen Wright Mia, RB
Oh He Likes Cooking!
12
Adonai Mitchell Ind, WR
Dent.
13
Joshua Palmer Buf, WR
LaPorta Potty
14
Kirk Cousins Atl, QB
Tony Fkn Romo
Round 12
NO.
Player
Team
1
Cowboys D/ST Dal, D/ST
Tony Fkn Romo
2
Jared Goff Det, QB
LaPorta Potty
3
Jets D/ST NYJ, D/ST
Dent.
4
49ers D/ST SF, D/ST
Oh He Likes Cooking!
5
Bucky Irving TB, RB
Tee Time
6
Steelers D/ST Pit, D/ST
Kittle Me This
7
Michael Wilson Ari, WR
The Minutemen ︻デ═一
8
Chiefs D/ST KC, D/ST
Glass of Charbonnet
9
Khalil Herbert Ind, RB
STATION GRITS
10
Tyrone Tracy Jr. NYG, RB
Set Pitts Free
11
Dontayvion Wicks GB, WR
Rolls With Butter
12
Dolphins D/ST Mia, D/ST
LeGoon
13
Lions D/ST Det, D/ST
JOSH JACOBS FAN CLUB
14
Baker Mayfield TB, QB
N.Y. Routensss
Round 13
NO.
Player
Team
1
Ray Davis Buf, RB
N.Y. Routensss
2
Kendrick Bourne NE, WR
JOSH JACOBS FAN CLUB
3
Harrison Butker KC, K
LeGoon
4
Rashod Bateman Bal, WR
Rolls With Butter
5
Justin Tucker Bal, K
Set Pitts Free
6
Josh Downs Ind, WR
STATION GRITS
7
Evan McPherson Cin, K
Glass of Charbonnet
8
Jake Elliott Phi, K
The Minutemen ︻デ═一
9
Greg Zuerlein NYJ, K
Kittle Me This
10
Tyler Conklin NYJ, TE
Tee Time
11
Braelon Allen NYJ, RB
Oh He Likes Cooking!
12
Ka'imi Fairbairn Hou, K
Dent.
13
Cole Kmet Chi, TE
LaPorta Potty
14
MarShawn Lloyd GB, RB
Tony Fkn Romo
Round 14
NO.
Player
Team
1
Taysom Hill NO, TE
Tony Fkn Romo
2
Saints D/ST NO, D/ST
LaPorta Potty
3
Bryce Young Car, QB
Dent.
4
Matthew Stafford LAR, QB
Oh He Likes Cooking!
5
Jake Moody SF, K
Tee Time
6
Miles Sanders Dal, RB
Kittle Me This
7
Clyde Edwards-Helaire NO, RB
The Minutemen ︻デ═一
8
Tre Tucker LV, WR
Glass of Charbonnet
9
Younghoe Koo Atl, K
STATION GRITS
10
Bears D/ST Chi, D/ST
Set Pitts Free
11
Bo Nix Den, QB
Rolls With Butter
12
Demarcus Robinson SF, WR
LeGoon
13
Samaje Perine Cin, RB
JOSH JACOBS FAN CLUB
14
Jahan Dotson Phi, WR
N.Y. Routensss
Round 15
NO.
Player
Team
1
Roschon Johnson Chi, RB
N.Y. Routensss
2
Will Levis Ten, QB
JOSH JACOBS FAN CLUB
3
Jalin Hyatt NYG, WR
LeGoon
4
Seahawks D/ST Sea, D/ST
Rolls With Butter
5
Isaiah Likely Bal, TE
Set Pitts Free
6
Jaguars D/ST Jax, D/ST
STATION GRITS
7
Luke McCaffrey Wsh, WR
Glass of Charbonnet
8
Tucker Kraft GB, TE
The Minutemen ︻デ═一
9
Chig Okonkwo Ten, TE
Kittle Me This
10
Juwan Johnson NO, TE
Tee Time
11
Cairo Santos Chi, K
Oh He Likes Cooking!
12
Jalen Tolbert Dal, WR
Dent.
13
Allen Lazard NYJ, WR
LaPorta Potty
14
Wan'Dale Robinson NYG, WR
Tony Fkn Romo
Round 16
NO.
Player
Team
1
Jason Sanders Mia, K
Tony Fkn Romo
2
Jason Myers Sea, K
LaPorta Potty
3
Hunter Henry NE, TE
Dent.
4
Luke Musgrave GB, TE
Oh He Likes Cooking!
5
Bengals D/ST Cin, D/ST
Tee Time
6
Cameron Dicker LAC, K
Kittle Me This
7
DJ Chark Jr. LAC, WR
The Minutemen ︻デ═一
8
Geno Smith LV, QB
Glass of Charbonnet
9
Jake Bates Det, K
STATION GRITS
10
Tyler Boyd Ten, WR
Set Pitts Free
11
Dustin Hopkins Cle, K
Rolls With Butter
12
Daniel Jones Ind, QB
LeGoon
13
Darius Slayton NYG, WR
JOSH JACOBS FAN CLUB
14
Tyler Bass Buf, K
N.Y. Routensss
"""

raw_2025 = """
Round 1
NO.
Player
Team
1
Bijan Robinson Atl, RB
Make Fantasy Great Again
2
Ja'Marr Chase Cin, WR
N.Y. Routensss
3
Saquon Barkley Phi, RB
RPMs backup team
4
Jahmyr Gibbs Det, RB
A$AP Monke
5
Justin Jefferson Min, WR
The Minutemen
6
CeeDee Lamb Dal, WR
Oh He Likes Cooking!
7
Malik Nabers NYG, WR
Talking Tua Freshman
8
Puka Nacua LAR, WR
STATION GRITS
9
Amon-Ra St. Brown Det, WR
Rolls With Butter
10
Christian McCaffrey SF, RB
Shakir to death
11
Ashton Jeanty LV, RB
Worthy of a Warren(t)
12
Nico Collins Hou, WR
(Dan wash)Burn
13
Jonathan Taylor Ind, RB
LaPorta Potty
14
Josh Jacobs GB, RB
Theres Always This Year
Round 2
NO.
Player
Team
1
De'Von Achane Mia, RB
Theres Always This Year
2
Derrick Henry Bal, RB
LaPorta Potty
3
Brian Thomas Jr. Jax, WR
(Dan wash)Burn
4
Bucky Irving TB, RB
Worthy of a Warren(t)
5
A.J. Brown Phi, WR
Shakir to death
6
Drake London Atl, WR
Rolls With Butter
7
Brock Bowers LV, TE
STATION GRITS
8
Chase Brown Cin, RB
Talking Tua Freshman
9
Trey McBride Ari, TE
Oh He Likes Cooking!
10
Kyren Williams LAR, RB
The Minutemen
11
Ladd McConkey LAC, WR
A$AP Monke
12
Tyreek Hill FA, WR
RPMs backup team
13
James Cook III Buf, RB
N.Y. Routensss
14
Lamar Jackson Bal, QB
Make Fantasy Great Again
Round 3
NO.
Player
Team
1
Omarion Hampton LAC, RB
Make Fantasy Great Again
2
Kenneth Walker III Sea, RB
N.Y. Routensss
3
Alvin Kamara NO, RB
RPMs backup team
4
Jaxon Smith-Njigba Sea, WR
A$AP Monke
5
Jayden Daniels Wsh, QB
The Minutemen
6
Josh Allen Buf, QB
Oh He Likes Cooking!
7
Jalen Hurts Phi, QB
Talking Tua Freshman
8
Chuba Hubbard Car, RB
STATION GRITS
9
TreVeyon Henderson NE, RB
Rolls With Butter
10
Davante Adams LAR, WR
Shakir to death
11
Tee Higgins Cin, WR
Worthy of a Warren(t)
12
James Conner Ari, RB
(Dan wash)Burn
13
Terry McLaurin Wsh, WR
LaPorta Potty
14
George Kittle SF, TE
Theres Always This Year
Round 4
NO.
Player
Team
1
Marvin Harrison Jr. Ari, WR
Theres Always This Year
2
Garrett Wilson NYJ, WR
LaPorta Potty
3
Mike Evans TB, WR
(Dan wash)Burn
4
Xavier Worthy KC, WR
Worthy of a Warren(t)
5
D'Andre Swift Chi, RB
Shakir to death
6
Breece Hall NYJ, RB
Rolls With Butter
7
RJ Harvey Den, RB
STATION GRITS
8
DJ Moore Chi, WR
Talking Tua Freshman
9
Tony Pollard Ten, RB
Oh He Likes Cooking!
10
Courtland Sutton Den, WR
The Minutemen
11
Zay Flowers Bal, WR
A$AP Monke
12
Rashee Rice KC, WR
RPMs backup team
13
Joe Burrow Cin, QB
N.Y. Routensss
14
DK Metcalf Pit, WR
Make Fantasy Great Again
Round 5
NO.
Player
Team
1
DeVonta Smith Phi, WR
Make Fantasy Great Again
2
Calvin Ridley Ten, WR
N.Y. Routensss
3
Jameson Williams Det, WR
RPMs backup team
4
Isiah Pacheco KC, RB
A$AP Monke
5
David Montgomery Hou, RB
The Minutemen
6
Rome Odunze Chi, WR
Oh He Likes Cooking!
7
Jaylen Waddle Mia, WR
Talking Tua Freshman
8
Baker Mayfield TB, QB
STATION GRITS
9
Tetairoa McMillan Car, WR
Rolls With Butter
10
Patrick Mahomes KC, QB
Shakir to death
11
George Pickens Dal, WR
Worthy of a Warren(t)
12
Kaleb Johnson Pit, RB
(Dan wash)Burn
13
Sam LaPorta Det, TE
LaPorta Potty
14
Matthew Golden GB, WR
Theres Always This Year
Round 6
NO.
Player
Team
1
Jerry Jeudy Cle, WR
Theres Always This Year
2
Chris Olave NO, WR
LaPorta Potty
3
T.J. Hockenson Min, TE
(Dan wash)Burn
4
Kyler Murray Ari, QB
Worthy of a Warren(t)
5
Aaron Jones Sr. Min, RB
Shakir to death
6
Travis Hunter Jax, WR
Rolls With Butter
7
Emeka Egbuka TB, WR
STATION GRITS
8
Tyrone Tracy Jr. NYG, RB
Talking Tua Freshman
9
Ricky Pearsall SF, WR
Oh He Likes Cooking!
10
Stefon Diggs NE, WR
The Minutemen
11
David Njoku Cle, TE
A$AP Monke
12
Bo Nix Den, QB
RPMs backup team
13
Travis Kelce KC, TE
N.Y. Routensss
14
Mark Andrews Bal, TE
Make Fantasy Great Again
Round 7
NO.
Player
Team
1
Jordan Addison Min, WR
Make Fantasy Great Again
2
Cooper Kupp Sea, WR
N.Y. Routensss
3
Evan Engram Den, TE
RPMs backup team
4
Brock Purdy SF, QB
A$AP Monke
5
Jacory Croskey-Merritt Wsh, RB
The Minutemen
6
Jordan Mason Min, RB
Oh He Likes Cooking!
7
Tyler Warren Ind, TE
Talking Tua Freshman
8
Jakobi Meyers Jax, WR
STATION GRITS
9
Michael Pittman Jr. Ind, WR
Rolls With Butter
10
Khalil Shakir Buf, WR
Shakir to death
11
Jaylen Warren Pit, RB
Worthy of a Warren(t)
12
Joe Mixon Hou, RB
(Dan wash)Burn
13
J.K. Dobbins Den, RB
LaPorta Potty
14
Deebo Samuel Wsh, WR
Theres Always This Year
Round 8
NO.
Player
Team
1
Quinshon Judkins Cle, RB
Theres Always This Year
2
Justin Fields NYJ, QB
LaPorta Potty
3
Caleb Williams Chi, QB
(Dan wash)Burn
4
Chris Godwin Jr. TB, WR
Worthy of a Warren(t)
5
Tucker Kraft GB, TE
Shakir to death
6
Austin Ekeler Wsh, RB
Rolls With Butter
7
Cam Skattebo NYG, RB
STATION GRITS
8
Jauan Jennings SF, WR
Talking Tua Freshman
9
Josh Downs Ind, WR
Oh He Likes Cooking!
10
Colston Loveland Chi, TE
The Minutemen
11
Rhamondre Stevenson NE, RB
A$AP Monke
12
Javonte Williams Dal, RB
RPMs backup team
13
Keon Coleman Buf, WR
N.Y. Routensss
14
Jayden Reed GB, WR
Make Fantasy Great Again
Round 9
NO.
Player
Team
1
Travis Etienne Jr. Jax, RB
Make Fantasy Great Again
2
Justin Herbert LAC, QB
N.Y. Routensss
3
Jaydon Blue Dal, RB
RPMs backup team
4
Dak Prescott Dal, QB
A$AP Monke
5
Keenan Allen LAC, WR
The Minutemen
6
Tank Bigsby Phi, RB
Oh He Likes Cooking!
7
Rachaad White TB, RB
Talking Tua Freshman
8
Jayden Higgins Hou, WR
STATION GRITS
9
Jake Ferguson Dal, TE
Rolls With Butter
10
Zach Charbonnet Sea, RB
Shakir to death
11
Kyle Pitts Sr. Atl, TE
Worthy of a Warren(t)
12
Drake Maye NE, QB
(Dan wash)Burn
13
Rashid Shaheed Sea, WR
LaPorta Potty
14
C.J. Stroud Hou, QB
Theres Always This Year
Round 10
NO.
Player
Team
1
Nick Chubb Hou, RB
Theres Always This Year
2
Cedric Tillman Cle, WR
LaPorta Potty
3
Trey Benson Ari, RB
(Dan wash)Burn
4
Darnell Mooney Atl, WR
Worthy of a Warren(t)
5
Hollywood Brown KC, WR
Shakir to death
6
Jared Goff Det, QB
Rolls With Butter
7
Braelon Allen NYJ, RB
STATION GRITS
8
Adam Thielen Pit, WR
Talking Tua Freshman
9
Jerome Ford Cle, RB
Oh He Likes Cooking!
10
Tyjae Spears Ten, RB
The Minutemen
11
Xavier Legette Car, WR
A$AP Monke
12
Brandon Aiyuk SF, WR
RPMs backup team
13
Jordan Love GB, QB
N.Y. Routensss
14
Tyler Allgeier Atl, RB
Make Fantasy Great Again
Round 11
NO.
Player
Team
1
Bhayshul Tuten Jax, RB
Make Fantasy Great Again
2
J.J. McCarthy Min, QB
N.Y. Routensss
3
Brian Robinson Jr. SF, RB
RPMs backup team
4
Dalton Kincaid Buf, TE
A$AP Monke
5
Najee Harris LAC, RB
The Minutemen
6
Ray Davis Buf, RB
Oh He Likes Cooking!
7
Tua Tagovailoa Mia, QB
Talking Tua Freshman
8
DeMario Douglas NE, WR
STATION GRITS
9
Jaylen Wright Mia, RB
Rolls With Butter
10
Hunter Henry NE, TE
Shakir to death
11
Christian Kirk Hou, WR
Worthy of a Warren(t)
12
Wan'Dale Robinson NYG, WR
(Dan wash)Burn
13
Texans D/ST Hou, D/ST
LaPorta Potty
14
MarShawn Lloyd GB, RB
Theres Always This Year
Round 12
NO.
Player
Team
1
Kyle Williams NE, WR
Theres Always This Year
2
Will Shipley Phi, RB
LaPorta Potty
3
Broncos D/ST Den, D/ST
(Dan wash)Burn
4
Matthew Stafford LAR, QB
Worthy of a Warren(t)
5
Seahawks D/ST Sea, D/ST
Shakir to death
6
Bryce Young Car, QB
Rolls With Butter
7
Steelers D/ST Pit, D/ST
STATION GRITS
8
Ravens D/ST Bal, D/ST
Talking Tua Freshman
9
Dylan Sampson Cle, RB
Oh He Likes Cooking!
10
Vikings D/ST Min, D/ST
The Minutemen
11
Lions D/ST Det, D/ST
A$AP Monke
12
Eagles D/ST Phi, D/ST
RPMs backup team
13
Patriots D/ST NE, D/ST
N.Y. Routensss
14
Trevor Lawrence Jax, QB
Make Fantasy Great Again
Round 13
NO.
Player
Team
1
Dallas Goedert Phi, TE
Make Fantasy Great Again
2
Jake Bates Det, K
N.Y. Routensss
3
Marvin Mims Jr. Den, WR
RPMs backup team
4
Jack Bech LV, WR
A$AP Monke
5
Cameron Dicker LAC, K
The Minutemen
6
Woody Marks Hou, RB
Oh He Likes Cooking!
7
Chase McLaughlin TB, K
Talking Tua Freshman
8
Brandon Aubrey Dal, K
STATION GRITS
9
Rico Dowdle Car, RB
Rolls With Butter
10
Tyler Lockett LV, WR
Shakir to death
11
Darren Waller Mia, TE
Worthy of a Warren(t)
12
Justice Hill Bal, RB
(Dan wash)Burn
13
Zach Ertz Wsh, TE
LaPorta Potty
14
Blake Corum LAR, RB
Theres Always This Year
Round 14
NO.
Player
Team
1
Cardinals D/ST Ari, D/ST
Theres Always This Year
2
Tyler Bass Buf, K
LaPorta Potty
3
Chris Boswell Pit, K
(Dan wash)Burn
4
Luther Burden III Chi, WR
Worthy of a Warren(t)
5
Ka'imi Fairbairn Hou, K
Shakir to death
6
Jets D/ST NYJ, D/ST
Rolls With Butter
7
Cam Ward Ten, QB
STATION GRITS
8
Rashod Bateman Bal, WR
Talking Tua Freshman
9
Brenton Strange Jax, TE
Oh He Likes Cooking!
10
Sam Darnold Sea, QB
The Minutemen
11
Jake Elliott Phi, K
A$AP Monke
12
Harrison Butker KC, K
RPMs backup team
13
Tre' Harris LAC, WR
N.Y. Routensss
14
Joshua Palmer Buf, WR
Make Fantasy Great Again
Round 15
NO.
Player
Team
1
Chargers D/ST LAC, D/ST
Make Fantasy Great Again
2
Michael Wilson Ari, WR
N.Y. Routensss
3
Michael Penix Jr. Atl, QB
RPMs backup team
4
Jonnu Smith Pit, TE
A$AP Monke
5
Roschon Johnson Chi, RB
The Minutemen
6
Bills D/ST Buf, D/ST
Oh He Likes Cooking!
7
Colts D/ST Ind, D/ST
Talking Tua Freshman
8
Elijah Arroyo Sea, TE
STATION GRITS
9
Kareem Hunt KC, RB
Rolls With Butter
10
Romeo Doubs GB, WR
Shakir to death
11
Matt Gay FA, K
Worthy of a Warren(t)
12
DJ Giddens Ind, RB
(Dan wash)Burn
13
Pat Bryant Den, WR
LaPorta Potty
14
Cade Otton TB, TE
Theres Always This Year
Round 16
NO.
Player
Team
1
Tyler Loop Bal, K
Theres Always This Year
2
Dont'e Thornton Jr. LV, WR
LaPorta Potty
3
Mason Taylor NYJ, TE
(Dan wash)Burn
4
Giants D/ST NYG, D/ST
Worthy of a Warren(t)
5
Sean Tucker TB, RB
Shakir to death
6
Wil Lutz Den, K
Rolls With Butter
7
Adonai Mitchell NYJ, WR
STATION GRITS
8
Jason Sanders Mia, K
Talking Tua Freshman
9
Will Reichard Min, K
Oh He Likes Cooking!
10
Calvin Austin III Pit, WR
The Minutemen
11
Cairo Santos Chi, K
A$AP Monke
12
Isaiah Likely Bal, TE
RPMs backup team
13
Quentin Johnston LAC, WR
N.Y. Routensss
14
Cam Little Jax, K
Make Fantasy Great Again
"""

# ── Run all seasons ───────────────────────────────────────────────────────────

season_data = {
    2020: (raw_2020, 15),
    2021: (raw_2021, 14),
    2022: (raw_2022, 14),
    2023: (raw_2023, 14),
    2024: (raw_2024, 14),
    2025: (raw_2025, 14),
}

frames = []
for season, (raw, league_size) in season_data.items():
    if not raw.strip():
        print(f"Season {season}: no data, skipping")
        continue
    df = parse_draft(raw, season=season, league_size=league_size)
    frames.append(df)
    print(f"Season {season}: {len(df)} total picks parsed")

df_all = pd.concat(frames, ignore_index=True)

# ── Filter skill positions ────────────────────────────────────────────────────

df_skill = df_all[~df_all["position"].isin(["K", "D/ST"])].copy()

print(f"\nTotal picks (all positions): {len(df_all)}")
print(f"Skill position picks only:   {len(df_skill)}")

# ── Sanity checks ─────────────────────────────────────────────────────────────

print("\n--- Sanity check: 2025 Round 1 with draft slots ---")
print(
    df_skill[(df_skill["season"] == 2025) & (df_skill["round"] == 1)]
    .sort_values("overall_pick")
    [["draft_slot", "overall_pick", "player_name", "position", "manager"]]
    .to_string(index=False)
)

print("\n--- Draft slot per manager per season (spot check) ---")
slot_check = (
    df_skill[df_skill["round"] == 1]
    .groupby(["season", "manager"])["draft_slot"]
    .first()
    .unstack("season")
    .sort_index()
)
print(slot_check.to_string())

print("\n--- Unmatched fantasy team names (no manager found) ---")
unmatched = df_all[df_all["manager"] == df_all["fantasy_team"]]["fantasy_team"].unique()
if len(unmatched) == 0:
    print("None — all teams matched successfully")
else:
    for t in sorted(unmatched):
        print(f"  '{t}'")

# ── Save ──────────────────────────────────────────────────────────────────────

df_skill.to_csv("draft_history.csv", index=False)
df_all.to_csv("draft_history_all_positions.csv", index=False)

print("\n=== Done ===")
print(f"draft_history.csv               — {len(df_skill)} rows (skill positions only)")
print(f"draft_history_all_positions.csv — {len(df_all)} rows (all positions)")