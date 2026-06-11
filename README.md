# FIA WEC 2026 - Auto-Updating Apple Calendar Feed

Daily sync from fiawec.com's official calendar endpoints with their two
feed bugs repaired (Paris double-converted end times, Le Mans Z-mislabeled
local times). Self-healing: if FIA fixes their feed, corrections disable
themselves automatically.

## Subscribe (Apple Calendar)

**iPhone:** Settings > Apps > Calendar > Calendar Accounts > Add Account >
Other > Add Subscribed Calendar:

    https://raw.githubusercontent.com/Creative-fw/wec-2026-calendar/main/FIA_WEC_2026.ics

**Mac:** Calendar > File > New Calendar Subscription > same URL.
Set Auto-refresh: Every day. Choose location iCloud so it syncs to all
devices and refreshes server-side.

## How updates flow

FIA changes a session time -> GitHub Action picks it up daily at 03:00 UTC
(07:00 Dubai) -> commits new ICS -> Apple Calendar pulls on next refresh.

During a live race week, trigger the Action manually (Actions tab >
Run workflow) for an instant sync.
