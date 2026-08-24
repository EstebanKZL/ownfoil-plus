# Changelog

All notable changes to Ownfoil-Plus are documented here, version by version. This
only covers this fork's own changes on top of [Ownfoil](https://github.com/a1ex4/ownfoil) -
see the upstream project for its own history.

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
