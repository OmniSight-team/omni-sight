from dataclasses import dataclass

from omnisight_common.roles import Role


@dataclass(frozen=True)
class NavRoute:
    path: str
    label: str
    roles: tuple[Role, ...]


# The nine in-app screens, from the product document. Sign In is the tenth
# screen but sits outside the shell, so it isn't listed here. Single source
# of truth for both the frontend sidebar and, from slice 16 on, server-side
# route enforcement — two copies of this map would drift.
NAV_ROUTES: tuple[NavRoute, ...] = (
    NavRoute("/", "Operations Dashboard", (Role.OPERATOR, Role.ANALYST, Role.ADMIN)),
    NavRoute("/live", "Live Monitoring", (Role.OPERATOR, Role.ADMIN)),
    NavRoute("/search", "Search", (Role.OPERATOR, Role.ANALYST, Role.ADMIN)),
    NavRoute("/alerts", "Alerts", (Role.OPERATOR, Role.ANALYST, Role.ADMIN)),
    NavRoute("/reports", "Incident Reports", (Role.ANALYST, Role.ADMIN)),
    NavRoute("/videos", "Video Archive", (Role.OPERATOR, Role.ANALYST, Role.ADMIN)),
    NavRoute("/cameras", "Cameras", (Role.OPERATOR, Role.ADMIN)),
    NavRoute("/integrations", "Integrations", (Role.ADMIN,)),
    NavRoute("/admin", "Administration", (Role.ADMIN,)),
)
