# Changelog

All notable changes to Ownfoil-Plus are documented here, version by version. This
only covers this fork's own changes on top of [Ownfoil](https://github.com/a1ex4/ownfoil) -
see the upstream project for its own history.

## [6.2.4.5]

- Clicking a row in the Stats page's "Libraries" table now opens a detail view of
  every title in that library - Base/Updates/DLC laid out the same way the Library
  page's List view does, Updates and DLC grouped into collapsible sections.
- A search box on all three of the Stats page's drill-down views (Libraries,
  Verification Status, App Types), to find a specific title or file in a long list
  without scrolling.
- Two new admin actions on each title in that new library detail view: clean a
  title's tracked database record without touching its file (for recovering a
  stuck or inconsistent entry), or delete the file from disk and its record
  together, for real. Both work on a single update/DLC on its own, or on a base
  game with the choice to sweep every update and DLC under it at the same time.
  Neither needs a settings toggle turned on first anymore - just admin access.
- Fixed the "App Types" drill-down (added in 6.2.4.4) opening to a broken, stuck
  modal that couldn't be closed without reloading the page.

## [6.2.4.4]

- Clicking a row in the Stats page's "App Types" table (Base/DLC/Update) now shows
  exactly which titles account for the gap between "Registered" and "Owned" - e.g.
  a title an update or DLC was scanned for, but the base game's own file never was.
- "Verify library now" is "Verify pending files" again - a quick, light action that
  only checks new or never-verified files, the same thing the automatic pipeline
  already does on its own.
- The "Danger zone" section is now "Clean Library", with a clearer explanation:
  it resets tracked file data so the library can be rediscovered from scratch, and
  never deletes anything from disk.

## [6.2.4.3]

- Card and Icon views now use the same local artwork cache the List view already
  did, instead of fetching covers straight from the remote catalogue.
- Clicking a game's cover in Card or Icon view now opens the same detailed info
  panel the List view's info button does.
- Release dates and file sizes in that info panel are now formatted properly
  (`24/06/2022`, `12.9 GiB`) instead of showing the catalogue's raw values.
- A short activity history on the Tasks page, showing the most recent completed
  operations (a scan, a verify pass, a titledb update, ...) - previously nothing
  was kept once a task finished.
- A pagination bar at the top of the Library page too, not just the bottom.
- The List view's per-game banner now shows behind the whole card, the way it did
  originally, instead of a shorter strip up top.
- "Verify library now" is now an explicit, confirmed action that re-checks every
  file, including already-verified ones - the automatic pipeline already picks up
  new or never-verified files on its own, so the button now does the one thing it
  couldn't before.
- Fixed a real data-loss risk: an unstable or not-yet-reconnected network share
  (or a drive still mounting at startup) could get files' tracked verification
  state wiped and treated as brand new once it came back, instead of being left
  alone until the drive was reliably back.

## [6.2.4.2]

- Users with shop access (not just admins) can now use the List view's download
  button, as long as an admin has turned it on in Settings.
- Card and Icon views now go through the same local artwork cache the List view
  already used, instead of fetching covers straight from the remote catalogue -
  faster repeat loads, and covers keep working even if that remote host is slow or
  unreachable.
- Clicking a game's cover in Card or Icon view opens the same rich info panel the
  List view's info button does - genre, players, rating, languages, file size, and
  screenshots.
- Release dates and file sizes in that info panel are now formatted properly
  (`24/06/2022`, `12.9 GiB`) instead of showing the catalogue's raw values.
- The "Updates" version-history popover in Card view now shows one entry per line
  instead of running them all together.
- A duplicate-file tie between a compressed and an uncompressed copy can now be
  resolved by that alone, separately from the existing "prefer the larger file"
  setting - useful since a compressed file is always going to be the smaller one.
- The same compressed/uncompressed preference is also available for the manual
  "resolve all by size" bulk action.
- The Duplicate Files section on the Stats page is now always visible, not just
  when there happens to be a duplicate to resolve.
- Fixed a real bug where dismissing a failed task that had its own failed children
  (e.g. after an unclean restart) silently failed instead of clearing the list.
- Fixed task progress and the Worker cards not updating during a very large backlog -
  the currently-running task could fall outside what the page was shown, so it
  looked stuck at 0% or idle even while actively working.

## [6.2.4.1]

- Editable game info: fix or fill in a title's name, developer, description, and
  other details by hand from the List view's info panel, when the catalogue is
  missing or wrong about them - it stays that way even after the catalogue updates,
  changing only the specific fields you set.
- A filter in the List view to quickly find titles that are complete, incomplete, or
  have a corrupt or repack file anywhere in them (base, update, or DLC).
- Colored badges in the README so each one is visually distinct at a glance.

## [6.2.4.0]

Initial release of this fork, bringing together everything built on top of
upstream Ownfoil:

- Full Spanish/English web interface, switchable anytime from the navbar.
- A List view showing every game with its updates and DLC in one place, including
  what's still missing from the library.
- Local caching of game artwork, so covers and banners keep working even if the
  remote image host is unreachable.
- Duplicate file detection and resolution - automatic when verification gives a
  clear, unambiguous answer (with a choice of preferring the larger file), and
  manual otherwise, one at a time or in bulk.
- A safety fix to the file organizer: a same-size collision at the target filename
  no longer gets silently deleted, in case it turns out to be a different (better
  or worse) file that merely happens to weigh the same.
- A direct "Verify library now" action on the Stats page.
- Settings export/import from the web UI.
- A dedicated Docker image, `estebankzl/ownfoil-plus`, published for
  `linux/amd64`, `linux/arm64`, `linux/arm/v7`, and `linux/arm/v6`.
