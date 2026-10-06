"""One publisher per page (docs/PUBLISH_PLAN.md section 9).

Each module defines a publisher with `name`, `outputs(ctx)` (the page model
file and, during Stage A, the legacy view of today's file) and `verify(ctx)`
(the Stage A checks: the legacy view, fed legacy-mode analysis, against the
golden, plus INFO lines on what the live page changes to at M1).
"""

from engine.publish.pages.champions import ChampionsPublisher
from engine.publish.pages.draft_analysis import DraftAnalysisPublisher
from engine.publish.pages.draft_history import DraftHistoryPublisher
from engine.publish.pages.extra_analytics import ExtraAnalyticsPublisher
from engine.publish.pages.fingerprints import FingerprintsPublisher
from engine.publish.pages.games import GamesPublisher
from engine.publish.pages.headshots import HeadshotsPublisher
from engine.publish.pages.impact import ImpactPublisher
from engine.publish.pages.lineup_efficiency import LineupEfficiencyPublisher
from engine.publish.pages.managers import ManagersPublisher
from engine.publish.pages.odds import OddsPublisher
from engine.publish.pages.rankings import RankingsPublisher
from engine.publish.pages.schedule import SchedulePublisher
from engine.publish.pages.surplus import SurplusPublisher
from engine.publish.pages.trades import TradesPublisher
from engine.publish.pages.waivers import WaiversPublisher

PUBLISHERS: list = [GamesPublisher(), ManagersPublisher(), TradesPublisher(), ImpactPublisher(),
                     OddsPublisher(), DraftHistoryPublisher(), FingerprintsPublisher(), SurplusPublisher(),
                     DraftAnalysisPublisher(), WaiversPublisher(), LineupEfficiencyPublisher(),
                     ExtraAnalyticsPublisher(), ChampionsPublisher(), SchedulePublisher(), RankingsPublisher(),
                     HeadshotsPublisher()]
