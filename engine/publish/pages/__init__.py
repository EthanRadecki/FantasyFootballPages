"""One publisher per page (docs/PUBLISH_PLAN.md section 9).

Each module defines a publisher with `name`, `outputs(ctx)` (the page model
file and, during Stage A, the legacy view of today's file) and `verify(ctx)`
(the Stage A checks: the legacy view, fed legacy-mode analysis, against the
golden, plus INFO lines on what the live page changes to at M1).
"""

from engine.publish.pages.games import GamesPublisher
from engine.publish.pages.impact import ImpactPublisher
from engine.publish.pages.managers import ManagersPublisher
from engine.publish.pages.odds import OddsPublisher
from engine.publish.pages.trades import TradesPublisher

PUBLISHERS: list = [GamesPublisher(), ManagersPublisher(), TradesPublisher(), ImpactPublisher(),
                     OddsPublisher()]
