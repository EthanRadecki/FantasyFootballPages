"""One publisher per page (docs/PUBLISH_PLAN.md section 9).

Each module defines a publisher with `name`, `outputs(ctx)` (the page model
file and, during Stage A, the legacy view of today's file) and `verify(ctx)`
(the Stage A checks: the legacy view, fed legacy-mode analysis, against the
golden). Pages are added from PR A2 on.
"""

PUBLISHERS: list = []
