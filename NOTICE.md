# Notice

Ownfoil-Plus is distributed under the GNU Affero General Public License 3.0 (AGPL-3.0),
see [LICENSE.md](LICENSE.md). It builds on, and credits, the following projects:

| Project | What Ownfoil-Plus takes from it | License |
|---|---|---|
| [a1ex4/ownfoil](https://github.com/a1ex4/ownfoil), by [@a1ex4](https://github.com/a1ex4) and its contributors | The upstream project this fork is based on: the shop, the library manager and most of the code | AGPL-3.0 |
| [DeLFuS77/switch-library-manager-web](https://github.com/DeLFuS77/switch-library-manager-web), by [@DeLFuS77](https://github.com/DeLFuS77) | Design inspiration for the web UI's redesign: the design language (layered surfaces, rounded components, one meaning per color, page headers with soft glows, stat tiles, filter pills, a flat navigation with counters and a phone bottom bar) and adapted fragments of its styles. The ideas behind Upcoming releases, Sagas (its Wikidata queries) and the save vault for JKSV (what JKSV needs from WebDAV and the limits it keeps), a game's DLC grouped by title ID from the whole catalogue, and update versions merged from more sources (its `merge_versions.py`: the sources and the checks), reading NUP files and taking a game's NFO, SFV and proof files along when organizing, reimplemented here in Python. Its code, name, logo and texts are not used. | AGPL-3.0 |
| [DeLFuS77/NXPress](https://github.com/DeLFuS77/NXPress), by [@DeLFuS77](https://github.com/DeLFuS77) | Reference for compressing and decompressing NSP, XCI and SuperNSP files to NSZ and XCZ (Files > Compress / Decompress), which upcoming versions refine from it. | AGPL-3.0 |
| [a55uka/nup](https://github.com/a55uka/nup), by [@a55uka](https://github.com/a55uka) | The NUP container format (version 1), a clean-room container for unencrypted Switch 1/2 dumps, read by `app/containers/nup.py`. | MIT |
| [Wikidata](https://www.wikidata.org) | The series each Switch game belongs to (Sagas), asked by each server for itself. | CC0 |

Vendored front-end libraries (Bootstrap, Bootstrap Icons, jQuery, the Inter font) keep
their own licenses, listed in [app/static/vendor/README.md](app/static/vendor/README.md).
