/* Draft Fingerprints template metadata: trait labels, the Metric Explorer's groups and each metric's
   label, format and description. Moved from the Stage A page's inline DATA (its template keys);
   no league data: numbers the descriptions quote are {placeholders} the page fills from the
   model (draft-fingerprints.js, metaText). Labels are keyed by metric, so a league whose profile lacks a metric simply
   does not show it. */

export var RADAR_LABELS = {
  "early_rb_pct": "Early RB%",
  "early_wr_pct": "Early WR%",
  "rb_wr_balance": "RB/WR Balance",
  "positional_diversity": "Positional Diversity",
  "same_position_run_rate": "Run Rate",
  "draft_conviction": "Draft Conviction",
  "qb_patience": "QB Patience",
  "te_patience": "TE Patience",
  "k_patience": "K Patience",
  "dst_patience": "DST Patience"
};

export var POSDEV_LABELS = {
  "rb_adp_deviation": "RB",
  "wr_adp_deviation": "WR",
  "qb_adp_deviation": "QB",
  "te_adp_deviation": "TE",
  "k_adp_deviation": "K",
  "dst_adp_deviation": "DST"
};

export var EXPLORER_GROUPS = [
  {
    "id": "shape",
    "label": "Draft Shape",
    "cols": [
      "early_rb_pct",
      "early_wr_pct",
      "rb_wr_balance",
      "positional_diversity",
      "same_position_run_rate"
    ]
  },
  {
    "id": "patience",
    "label": "Patience",
    "cols": [
      "qb_patience",
      "te_patience",
      "k_patience",
      "dst_patience"
    ]
  },
  {
    "id": "conviction",
    "label": "Conviction & ADP",
    "cols": [
      "avg_adp_deviation",
      "reach_tendency",
      "value_hunting",
      "draft_conviction",
      "adp_independence"
    ]
  },
  {
    "id": "posdev",
    "label": "ADP Deviation by Position",
    "cols": [
      "rb_adp_deviation",
      "wr_adp_deviation",
      "qb_adp_deviation",
      "te_adp_deviation",
      "k_adp_deviation",
      "dst_adp_deviation"
    ]
  },
  {
    "id": "outcomes",
    "label": "Outcomes",
    "cols": [
      "Win_Pct",
      "PPG",
      "avg_surplus_per_pick"
    ]
  }
];

export var CAREER_EXTRAS_GROUP = {
  "id": "career_extras",
  "label": "Career Extras",
  "cols": [
    "positional_concentration",
    "draft_adaptability",
    "first_qb_round",
    "first_te_round",
    "first_k_round",
    "first_dst_round"
  ]
};

export var METRIC_META = {
  "early_rb_pct": {
    "label": "Early RB%",
    "short": "Early RB%",
    "fmt": "pct1",
    "desc": "Share of rounds 1–3 picks spent on RB."
  },
  "early_wr_pct": {
    "label": "Early WR%",
    "short": "Early WR%",
    "fmt": "pct1",
    "desc": "Share of rounds 1–3 picks spent on WR."
  },
  "rb_wr_balance": {
    "label": "RB/WR Balance",
    "short": "Balance",
    "fmt": "num1",
    "desc": "Evenness of RB vs WR investment early, independent of which position dominates. Higher = more balanced."
  },
  "positional_diversity": {
    "label": "Positional Diversity",
    "short": "Diversity",
    "fmt": "num1",
    "desc": "How evenly picks are spread across positions (HHI-based). Higher = more balanced spread."
  },
  "positional_concentration": {
    "label": "Positional Concentration",
    "short": "Concentration",
    "fmt": "num1",
    "desc": "Mirror image of Positional Diversity (r={r:positional_diversity:positional_concentration}). Shown for reference only; not used in clustering."
  },
  "same_position_run_rate": {
    "label": "Same-Position Run Rate",
    "short": "Run Rate",
    "fmt": "num1",
    "desc": "Tendency to draft the same position in bursts / consecutive picks. Higher = more likely to run a position."
  },
  "qb_patience": {
    "label": "QB Patience",
    "short": "QB Patience",
    "fmt": "num1",
    "desc": "Composite score for how late a manager waits to draft their first QB. Higher = more patient."
  },
  "te_patience": {
    "label": "TE Patience",
    "short": "TE Patience",
    "fmt": "num1",
    "desc": "Composite score for how late a manager waits to draft their first TE. Higher = more patient."
  },
  "k_patience": {
    "label": "K Patience",
    "short": "K Patience",
    "fmt": "num1",
    "desc": "Composite score for how late a manager waits to draft their first K. Higher = more patient."
  },
  "dst_patience": {
    "label": "DST Patience",
    "short": "DST Patience",
    "fmt": "num1",
    "desc": "Composite score for how late a manager waits to draft their first DST. Higher = more patient."
  },
  "avg_adp_deviation": {
    "label": "Avg ADP Deviation",
    "short": "Avg Dev.",
    "fmt": "signed1",
    "desc": "Average deviation from consensus ADP across all picks. Positive = reached (drafted ahead of ADP); negative = the player fell to them (drafted later than ADP)."
  },
  "reach_tendency": {
    "label": "Reach Tendency",
    "short": "Reach",
    "fmt": "num1",
    "desc": "Composite score for how often/far a manager reaches ahead of ADP. Correlated with Value Hunting, Draft Conviction, and ADP Independence (r={r_conviction}); these four likely share one underlying signal.",
    "caution": true
  },
  "value_hunting": {
    "label": "Value Hunting",
    "short": "Value",
    "fmt": "num1",
    "desc": "Composite score related to finding value picks relative to ADP. Part of the same correlated composite cluster as Reach Tendency.",
    "caution": true
  },
  "draft_conviction": {
    "label": "Draft Conviction",
    "short": "Conviction",
    "fmt": "num1",
    "desc": "Composite score for how strongly a manager deviates from consensus based on their own board. Used on the radar as the single representative of a correlated 4-metric cluster.",
    "caution": true
  },
  "adp_independence": {
    "label": "ADP Independence",
    "short": "Independence",
    "fmt": "num1",
    "desc": "Composite score for independence from ADP-driven drafting. Part of the same correlated composite cluster as Reach Tendency.",
    "caution": true
  },
  "rb_adp_deviation": {
    "label": "RB ADP Deviation",
    "short": "RB",
    "fmt": "signed1",
    "desc": "Average ADP deviation specifically on RB picks. Positive = reached; negative = fell to them."
  },
  "wr_adp_deviation": {
    "label": "WR ADP Deviation",
    "short": "WR",
    "fmt": "signed1",
    "desc": "Average ADP deviation specifically on WR picks. Positive = reached; negative = fell to them."
  },
  "qb_adp_deviation": {
    "label": "QB ADP Deviation",
    "short": "QB",
    "fmt": "signed1",
    "desc": "Average ADP deviation specifically on QB picks. Positive = reached; negative = fell to them."
  },
  "te_adp_deviation": {
    "label": "TE ADP Deviation",
    "short": "TE",
    "fmt": "signed1",
    "desc": "Average ADP deviation specifically on TE picks. Positive = reached; negative = fell to them."
  },
  "k_adp_deviation": {
    "label": "K ADP Deviation",
    "short": "K",
    "fmt": "signed1",
    "desc": "Average ADP deviation specifically on K picks. Positive = reached; negative = fell to them.{fill:K}",
    "caution": true
  },
  "dst_adp_deviation": {
    "label": "DST ADP Deviation",
    "short": "DST",
    "fmt": "signed1",
    "desc": "Average ADP deviation specifically on DST picks. Positive = reached; negative = fell to them.{fill:D/ST}",
    "caution": true
  },
  "Win_Pct": {
    "label": "Win %",
    "short": "Win%",
    "fmt": "pct1raw",
    "desc": "Regular-season win percentage. Not significantly associated with draft archetype (Kruskal-Wallis p={p_win})."
  },
  "PPG": {
    "label": "Points Per Game",
    "short": "PPG",
    "fmt": "num1",
    "desc": "Regular-season points per game. Not significantly associated with draft archetype (Kruskal-Wallis p={p_ppg})."
  },
  "avg_surplus_per_pick": {
    "label": "Avg Surplus / Pick",
    "short": "Surplus",
    "fmt": "signed3",
    "desc": "Mean round-weighted, position-relative surplus value per pick that season. Visually shows no separation by archetype.",
    "missing_note": "{surplus_missing}"
  },
  "draft_adaptability": {
    "label": "Draft Adaptability",
    "short": "Adaptability",
    "fmt": "num1",
    "desc": "Career-only metric: variability in a manager's draft approach from season to season. Higher = more year-to-year variation in style."
  },
  "first_qb_round": {
    "label": "First QB Round",
    "short": "1st QB Rd",
    "fmt": "num1",
    "desc": "Average round of a manager's first QB pick, career-wide."
  },
  "first_te_round": {
    "label": "First TE Round",
    "short": "1st TE Rd",
    "fmt": "num1",
    "desc": "Average round of a manager's first TE pick, career-wide."
  },
  "first_k_round": {
    "label": "First K Round",
    "short": "1st K Rd",
    "fmt": "num1",
    "desc": "Average round of a manager's first K pick, career-wide."
  },
  "first_dst_round": {
    "label": "First DST Round",
    "short": "1st DST Rd",
    "fmt": "num1",
    "desc": "Average round of a manager's first DST pick, career-wide."
  }
};

