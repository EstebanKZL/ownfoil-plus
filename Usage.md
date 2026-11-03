# Using Ownfoil-Plus

Once Ownfoil-Plus is running, the Shop Web UI is accessible with your computer/server IP and port, by navigating to `http://<computer/server IP>:8465`, i.e. `http://localhost:8465` from the same computer or `http://192.168.1.100:8465` from a device in your network.

# First steps

1. Open the Web UI.
2. Go to `Admin` → `Settings` and __create an admin user__. Until you do, authentication is disabled and anyone who can reach the Web UI can change the configuration of your shop.
3. Upload your [console keys](#console-keys) under `Titles`, so your files can be identified whatever their name.
4. Configure the [workers](#workers) to optimize identification for large libraries.
5. Add the directories containing your games under `Library` → `Paths`. Ownfoil-Plus scans a path as soon as you add it.
6. Open the `Setup` page and configure your client on your Nintendo Switch with the values it shows you.

By default the organizer and compression features are disabled until you turn them on, so your library isn't modified unexpectedly.

# Console keys

Console keys are the keys dumped from your own Nintendo Switch. Ownfoil-Plus uses them to decrypt the metadata inside your files, which is how it identifies a game regardless of what the file is called.

Upload your `prod.keys` (or any `.keys` / `.txt` file with the same content) in the `Settings` under `Titles`, then hit `Submit`. Ownfoil-Plus checks every master key revision it contains and tells you if one is missing or wrong. A missing revision means the games released after it cannot be decrypted, so they will not be identified.

Without keys, Ownfoil-Plus falls back to reading the filename, and every file __must contain `[TITLEID][vVERSION]`__ or it won't be recognized.

Three features need valid keys and are unavailable without them:

* identification of files that aren't named `[TITLEID][vVERSION]`
* [file verification](#file-verification), which is disabled when no valid keys are loaded
* [file compression](#file-compression), which has to decrypt the content to recompress it

# The Web UI

The top bar links every page: `Library` and `Setup` for everyone with shop access, and for admins `Files`, `Tasks`, `Stats` and the `Admin` menu (dashboard, settings, services). `Files` shows how many files are not identified yet and `Tasks` how many are running. On a phone, admins get a bottom bar instead (`Library`, `Files`, `Tasks`, `Stats` and `More`, which holds the rest: setup, admin pages, theme, language and logout).

## Theme, style and search

The sun/moon icon in the navbar sets two things:

- the **mode**: **light**, **dark** (the default) or **automatic**, following the device's own setting;
- the **style**, the colors of the interface: **Joy-Con** (the default: cyan to navigate, red for actions), **Ownfoil-Plus** (cyan, the logo's color) or **Neon** (red, with cyan details).

Both are remembered per browser. The admin chooses the style everyone sees by default, also on the login page, in `Settings > Appearance`; a browser that picked its own keeps it until `Use the server's style` is chosen.

**Search** from any page with `Ctrl+K` (`Cmd+K` on a Mac), `/`, or the magnifier in the navbar: type a game's name or title ID, a file name (admins), or a page or setting ("notifications", "backup", "users"...). Arrow keys move through the results and `Enter` opens one: a game opens the library filtered to it, a file opens the Files page filtered to it. Results only include what your account can access.

## Installing as an app

The web UI can be installed as an app on a phone, tablet or computer (its own icon and window, no browser bar), using the shop's name. When the browser offers it, an `Install app` button appears in the navbar; otherwise use the browser's own menu (`Install app` / `Add to Home Screen`). Static files are cached so pages open faster, and a "can't reach the server" page is shown instead of a browser error when the server is down. Library data, downloads and uploads always come live from the server.

Browsers only allow this over **HTTPS** (see [Remote access and HTTPS](./Install.md#remote-access-and-https)) or on `localhost`: on a plain `http://192.168.x.x` address the button doesn't appear and the site works exactly as a normal web page.

## Dashboard

The landing page of `Admin`. At the top, what needs attention, each linking to where to fix it: missing console keys, an unreachable library, low disk space, corrupt or unidentified files, duplicates, failed tasks, no backups yet. Then the figures that matter (games and how many are complete and up to date, files and total size, downloads this week, running and queued tasks), a bar per library with the space used and free (amber below 15 % free, red below 5 %), the latest added files and downloads - each opens its game's page - and the state of maintenance, backups, notifications and shop access.

`Upload files`, on the dashboard next to `Storage`, adds games from the browser: pick the destination library, then drop `nsp`, `nsz`, `xci` or `xcz` files (or click to choose them). They go up in chunks, one file at a time, with progress and speed, and can be paused, resumed or cancelled. If the connection drops, the tab is closed or the server restarts, choosing the same file again continues from where it stopped; unfinished uploads are listed in the same window and removed after 7 days without activity. While uploading, the file is a hidden `.part` file in the library folder that scans ignore; once complete it's renamed into place and identified like any other new file. A file whose name is already in the library is refused.

## Library view

The landing page: your whole library as cards, icons or a list.

- **At the top**, how the library is doing: the number of games, how many have an update pending, how many are missing DLC, the total size (admins only), and a bar with the share of games up to date. Clicking *Pending updates* or *Missing DLC* shows those games.
- **The toolbar**: search (by name or title ID), sort by **name** or **release date** in either direction, the view (cards, icons, list), the **View** menu (games per page, card size) and the **Filters** menu (type, ownership, update, DLC; in the list view, the state of the files). A dot on *Filters* means some filter is on.
- **The pills** under it are one-click filters, each with how many results it gives: *All*, *Update pending*, *Missing DLC*, *Up to date* (in the list view: *Complete*, *Incomplete*, *With errors*, *Repacks*). The counts follow the search and the Filters menu.
- **Each card** shows the cover, the name, the publisher and year, and badges for its state: update available, missing DLC, or complete. Games you don't have are dimmed. The clock button lists every known version of the title with its release date and whether you own it; the cover or the name opens the game's page.

Search, sort, view, filters and page size are remembered per browser. When nothing matches, *Clear filters* resets them.

## Game page

Every game has its own page, `/game/<title ID>`, opened from its card in the Library, its name in the list view, or a search with `Ctrl+K`. A DLC opens its game's page, scrolled to that DLC.

- **At the top**, the cover over the game's own artwork, whether you have it (and whether it's up to date and complete), the publisher and year, and the actions: *Download all* (when web downloads are on in Settings, for users with shop access), *Edit metadata* (admins) and *Copy title ID*.
- **The details**: title ID, release date, region, languages, genre, players, rating, size, the version you have and the latest one. Details the catalogue doesn't have aren't shown.
- **The sections**: the description; the screenshots (click one to see it full size); the updates, with a notice when you don't have the latest; the DLC, the ones you have and the ones missing; and, for admins, every file of the game with its verification and download.

*Edit metadata* corrects the name, developer, publisher, release date or description for this shop; an empty field keeps the catalogue's value, and *Back to the catalogue data* undoes your changes. The *Library* link at the top goes back to the Library as you left it.

## Setup page

This is the page to use when configuring a client on your Nintendo Switch. It prints the configuration tables for Tinfoil, Sphaira and CyberFoil, already filled in with your own address and port, and the exact menu path to follow in each app.

It has two tabs. `Local Access` is for when your Switch and your Ownfoil-Plus server are on the same network, and uses your server's LAN IP. `Remote Access` is for reaching your shop over the internet, and uses the `Shop URL` you configured in the [Shop](#shop) settings.

## Files page

Admin only. Search and filter every file in the library and act on it (retry identification, verify, compress, decompress, delete), with one-click cleanups for duplicates and outdated updates.


## Tasks page

Everything Ownfoil-Plus does in the background is a task, and this page shows them live: what is queued, what is running with its progress, what is scheduled to run later, and what failed. Failed tasks stay until you dismiss them, so you can see what went wrong earlier.

The worker section shows what each worker process is doing right now. How many there are is configured in [Workers](#workers), you can use it to see if the backlog of tasks can be optimized.

## Stats page

Admin only. An overview of the library: games, files, total size and unidentified files; the space each format takes (a donut) and each library (bars - click one for its titles); how much of the library is verified (a ring, with a row per status that lists its files); how much you own of each kind of content (base, updates, DLC); the ten largest files, each linking to its game; the duplicates; and, under `Downloads`, the download history: how many downloads and how much data over the last 7, 30, 90 or 365 days, a per-day chart, the most downloaded titles, counts per user and per client (Tinfoil, Sphaira, CyberFoil or the web UI), and the 50 latest downloads with who took them and from which address.

A file taken again by the same address within a minute counts once, so a console resuming or probing a download isn't counted twice. The history is kept for a year, survives deleting the file it refers to, and can be cleared from the same section (the per-file download counters are kept).

## Settings page

Admin only, and a single scrolling page.

# Clients

Ownfoil-Plus supports multiple clients to install content on your Nintendo Switch. They can be enabled and disabled individually in the [Shop](#client-access) settings.

## [Tinfoil:](https://tinfoil.io/Download)
- `HTTP` / `HTTPS` protocol support
- User authentication
- Shop browsing with icons and banners
- [Content filtering](#content-filters) (games, updates, DLC, multi-content) based on URL
- New games, DLC, Updates, Recommended and XCI sections
- Compressed content (NSZ and XCZ) support
- Encrypted shop support
- Client side Host verification for secure connections
- Tinfoil shop customization

## [Sphaira:](https://github.com/ITotalJustice/sphaira)
- `HTTP` / `HTTPS` protocol support
- User authentication
- Directory-based file browsing
- [Content filtering](#content-filters) (games, updates, DLC, multi-content) based on URL
- Compressed content (NSZ and XCZ) support

Sphaira browses your shop as a folder tree rather than a shop listing, so what you see is the layout of your library on disk. Opening a file shows a preview of its content, to actually install it press `Options` → `Install`.

Sphaira identifies itself in its requests since version `1.0.6`, which Ownfoil-Plus needs to serve the shop. Be sure to use an up to date version if encountering issues.

## [CyberFoil:](https://github.com/luketanti/CyberFoil)
- `HTTP` / `HTTPS` protocol support
- User authentication
- Shop browsing with icons and Sections (Updates, DLC)
- Compressed content (NSZ and XCZ) support
- Client side Host verification for secure connections
- Custom welcome message (MOTD)

> [!TIP]
> Check the `Setup` page in the Web UI for specific instructions on configuring each app, using local or remote access.

## Content filters

Adding a path to the shop URL configured in your client filters what it serves:

| Path | What you get |
| --- | --- |
| `/` | Everything, including files Ownfoil-Plus could not identify |
| `/base` | Games only |
| `/update` | Updates only |
| `/dlc` | DLC only |
| `/multi` | Files containing more than one content, typically an `xci` bundling a game with its update and DLC |

This is how you get several shops out of one Ownfoil-Plus: add one entry per filter in your client and you can browse your updates without scrolling past every game you own.

Note that only the unfiltered shop shows unidentified files. If a file shows up in the root shop but in none of the filters, it was not identified.

# Settings reference

The sections below follow the order of the `Settings` page.

## Authentication

Ownfoil-Plus requires an `admin` user to be created to enable authentication for your Shop. Create the first one here, it will have admin rights, then you can add more users to your shop the same way.

Each user has up to three permissions:

| Permission | Grants |
| --- | --- |
| `Shop` | Access to the shop from a client, to file downloads, and to the library page. |
| `Admin` | Access to the `Settings` and `Tasks` pages and everything that changes the configuration. Admins get the other two permissions automatically. |
| `Backup` | Reserved for a future feature, it currently grants nothing. |

You can also create users from [environment variables](./Install.md#environment-variables) at startup, which is handy to avoid ever running an instance without an admin.

## Library

This section is where you tell Ownfoil-Plus what your library is, how to watch it, and how to automatically manage the files in it.

Every file goes through the same pipeline, in order: it is __identified__ (what game, which version, base/update/DLC it contains), __verified__, __organized__, then __compressed__. A step that is disabled or already done is skipped, so a settled library does nothing at all. This is why enabling compression on an existing library starts compressing everything.

### Paths

Add the directories containing your content here. The path has to already exist on the machine running Ownfoil-Plus: with Docker that means the path *inside* the container, so `/games`, not the path on your NAS.

Ownfoil-Plus scans a path as soon as you add it, looking for `nsp`, `nsz`, `xci` and `xcz` files. The arrows button on a row rescans that one path, and `Scan library` rescans all of them. If enabled, the file watcher below detects changes automatically.

### File watcher

| Setting | Default | Description |
| --- | --- | --- |
| `Enable file watcher` | enabled | Watch your library paths for changes. |
| `Polling interval` | `60` seconds | How often network paths are checked. |

Files moved, renamed, added or removed are reflected directly in your library, without a scan.

Local directories are watched through the operating system, which notifies Ownfoil-Plus the moment something changes and costs nothing while idle, the polling interval is not used for them at all. Network filesystems (NFS, SMB, a mapped Windows drive) cannot do that, so they are checked at the interval you set instead, which is why a change on a NAS takes up to one interval to show up. Lower it if you want your library to react faster, at the cost of walking the whole tree more often.

### Management

Automated library management. Everything in this section shares the `Submit` button at the bottom.

| Setting | Default | Description |
| --- | --- | --- |
| `Delete older updates` | disabled | Deletes older update files when a newer version of the same update is in your library. |

#### File compression

| Setting | Default | Description |
| --- | --- | --- |
| `Compress files` | disabled | Compress files after they are added and organized. |
| `Compression level` | `18` | zstandard level, `1` to `22`. Higher is smaller but slower. |

Compression converts `nsp` to `nsz` and `xci` to `xcz`, which saves storage space depending on the game. Both formats install fine on all supported clients.

The compressed file is written next to the original, then every piece of content inside it is decompressed again and hashed, and compared against the same content in the source file. The original is only deleted once every one of them matches. If anything fails the original is left exactly where it was and the incomplete output is removed. A file that [verification](#file-verification) found to be corrupt is not compressed.

> [!TIP]
> Compression needs valid [console keys](#console-keys).

<details>
<summary>Advanced compression options</summary>

| Setting | Default | Description |
| --- | --- | --- |
| `Long-distance mode` | disabled | Better ratio on large files, at a higher memory use. |
| `Compression mode` | `auto` | `solid` gives the best ratio, `block` allows random reads so a file can be streamed or mounted without decompressing it fully. `auto` uses solid for `nsp` and block for `xci`. |
| `Block size exponent` | `20` | Block size is `2^x`, from `14` to `32`. `20` is 1 MB. Only used in block mode. |
| `Threads per file` | `0` | Threads a single compression uses, `0` picks automatically. |

`Threads per file` multiplies with the number of tasks running at once, so a high value combined with several [I/O tasks](#workers) will oversubscribe your CPU.

</details>

#### File verification

| Setting | Default | Description |
| --- | --- | --- |
| `Verify files` | enabled | Check that your files are original and intact. |
| Depth | `Full hash` | `Signature only` or `Full hash`. |

One aspect of library curation is to know whether or not the files in your collection are valid. This means different things for different users: some want to ensure every file is original and intact, while for others a modified but working file is enough. File verification is a tedious chore, but a mandatory one to make sure your backups will install and work, or if they need to be replaced.

`Signature only` checks that the file decrypts and that every content header is signed by Nintendo. It is near instant, and it catches a file that isn't what it claims to be. `Full hash` also reads every byte and compares it against the hash the file itself declares, which is the only way to catch actual corruption.

After files have been been successfully decrypted and identified, automatic verification will run in a background task. Using `signature` and content `hash` validation, each file will be classified as either:
- `valid`: original content from Nintendo, intact.
- `repack`: content has been modified, but metadata has been updated to allow integrity verification and it matches.
- `modified`: content has been modified but integrity metadata has not been updated.
- `corrupt`: the integrity of the content cannot be verified.

A `corrupt` file should be deleted or replaced, as installation will fail, but anything else should be fine to keep.

Verification is disabled entirely, with the controls greyed out, when no valid [console keys](#console-keys) are loaded.

#### Organizer

| Setting | Default | Description |
| --- | --- | --- |
| `Enable organizer` | disabled | Move identified files into the paths built from the templates below. |
| `Remove empty folders` | disabled | Remove folders left empty after files are moved out of them. |
| `Windows compatible filenames` | disabled | Use filenames a Windows system can read. |

Once a file is identified, the organizer renders the matching template, and moves the file there if it isn't already. Paths are relative to the library path the file is in, and the extension is added automatically.

By default, file names are sanitized based on the system running Ownfoil-Plus, for compatible characters. If Ownfoil-Plus is running on a Linux server but you are accessing your library on Windows (with an SMB or NFS mount), you can force the organizer to comply with file names that will render correctly in Windows.

##### Templates

| Template | Default |
| --- | --- |
| `Base template` | `{titleName}/{titleName} [{appId}][v{appVersion}]` |
| `Update template` | `{titleName}/{titleName} [{appId}][v{appVersion}]` |
| `DLC template` | `{titleName}/{appName} [{appId}][v{appVersion}]` |
| `Multi-content template` | `{titleName}/{titleName} [{titleId}]` |

Available in every template:

| Attribute | Description |
| --- | --- |
| `{extension}` | File extension, e.g. `nsp`, `nsz` |
| `{titleId}` | Title ID of the game |
| `{titleName}` | Name of the game title |

Available in the base, update and DLC templates:

| Attribute | Description |
| --- | --- |
| `{appId}` | Application ID |
| `{appVersion}` | Application version |
| `{patchLevel}` | Patch level |
| `{appName}` | Name of the application, the title or the DLC name |

> [!CAUTION]
> Make sure the templates contain `[{appId}][v{appVersion}]` for Tinfoil to recognize the apps.

## Titles

| Setting | Default | Description |
| --- | --- | --- |
| `Library Region` | `US` | Region used to get games informations. |
| `Library Language` | `en` | Language used to get games informations. |

This is the region and language of your shop, and for now it is the same for all users. It matches the names, descriptions and artwork for identified files. Changing it re-downloads titledb and, if the organizer is on, renames your files to match the new names.

The available languages depend on the region you pick.

`Console Keys file` is where you upload your keys - see [Console keys](#console-keys). Below it, `Master key revisions` reports what Ownfoil-Plus found in the file you uploaded, and names any revision that is missing or invalid.

## Shop

| Setting | Default | Description |
| --- | --- | --- |
| `Shop URL` | empty | The hostname your shop is reachable at from the internet, e.g. `shop.domain.tld`. |
| `Public shop` | disabled | Serve the shop to clients without authentication. |
| `Message of the day` | `Welcome to your own shop!` | Message presented in clients after successfully loading your shop. |

The MOTD is shown by Tinfoil and CyberFoil. Sphaira browses files and does not display it.

Setting `Shop URL` lets Ownfoil-Plus tell the client which address the shop is supposed to be served from, and the client refuses to load it from anywhere else. That is what stops someone who got hold of your URL and credentials from rebroadcasting your shop as their own.

It only works on secure requests: if your reverse proxy still answers on plain `http`, or doesn't send `X-Forwarded-Proto`, none of this applies and your shop is unprotected. See [Remote access and HTTPS](./Install.md#remote-access-and-https).

### Client access

| Setting | Default | Description |
| --- | --- | --- |
| `Tinfoil` → `Enabled` | enabled | Allow Tinfoil to access the shop. |
| `Tinfoil` → `Encrypt shop` | enabled | Serve the shop listing encrypted. |
| `Sphaira` → `Enabled` | enabled | Allow Sphaira to access the shop. |
| `CyberFoil` → `Enabled` | enabled | Allow CyberFoil to access the shop. |

Disabling a client makes Ownfoil-Plus refuse it with a message.

`Encrypt shop` compresses and encrypts the shop listing in a way only a real Tinfoil build can read, so only a Tinfoil client will be able to inspect the shop's content. Note that if a client other than Tinfoil is enabled (and not encryption is available), the shop content will be served in clear through their headers, rendering encryption useless.

## Scheduler

| Setting | Default | Description |
| --- | --- | --- |
| `TitleDB update interval` | `12h` | How often to refresh titledb and re-process your library. |

The interval is a number followed by a unit: `s`, `m`, `h` or `d`, so `30m`, `2h` and `1d` are all valid. Set it to `0` to disable the periodic run entirely.

TitleDB is updated upstream once per day, this scheduled task will sync your local reference and add the new titles, updates and DLCs. Libraries will be re-processed after the update, for example to identify files to titles that were not available before.

## Maintenance & backups

A daily window, off by default, that runs at the chosen time (the server's local time):

| Setting | Default | Description |
| --- | --- | --- |
| `Time` | `04:00` | When the window runs each day. |
| `Back up ...` | on | Saves the database, settings and console keys as a zip in `config/backups/`. |
| `Backups to keep` | `7` | Older backups beyond this count are deleted. |
| `Scan the libraries` | on | Finds new or missing files and processes what's pending. |
| `Delete superseded updates` | off | Removes update files older than one you also have. |
| `Re-verify every file` | `Never` | `Sundays only` or `Every day`: re-checks every file in full, to catch damage after it was added. Slow on big libraries. |

`Back up now` makes a backup on demand, and the list below it downloads or deletes any of them.

To restore a backup: stop Ownfoil-Plus, extract the zip into your `config/` folder (it replaces `ownfoil.db`, `settings.yaml` and `keys.txt`), then start it again. TitleDB and artwork aren't in the backup; they're downloaded again automatically.

## Notifications

Get a message when something happens in the library. Off by default: turn on `Enable notifications`, at least one channel, and use `Send test` to check it.

| Event | Sent when |
| --- | --- |
| Added to the library | A game, update or DLC file is identified for the first time. |
| New updates/DLC available | A TitleDB refresh finds a new update or DLC for a game whose base is in your library. |
| Corrupt files found | Verification marks a file as corrupt (not repacks or modified files). |
| Failed tasks | A background task fails. |

Events are grouped: everything that happens within 20 seconds of the first event goes out as one message per event type, listing up to 15 items. Messages are written in the `Message language` chosen in this section.

| Channel | What you need |
| --- | --- |
| Discord | A channel webhook URL: channel settings → Integrations → Webhooks. |
| Telegram | A bot token from [@BotFather](https://t.me/BotFather) and your chat ID (send the bot a message first). |
| ntfy | A server (`https://ntfy.sh` by default, or your own) and a topic; an access token for protected topics. On the public server anyone who knows the topic can read it, so pick a hard-to-guess name. |
| Webhook | Any URL; it receives a `POST` with `{"shop", "event", "title", "items": [...]}` as JSON. |

## Appearance

| Setting | Default | Description |
| --- | --- | --- |
| `Default style` | `Joy-Con` | The color style of the web UI for everyone: `Joy-Con`, `Ownfoil-Plus` or `Neon` (`appearance.default_style`: `joycon`, `ownfoil`, `neon`). Each person can still pick another one for their own browser from the theme menu. |

## Workers

| Setting | Default | Description |
| --- | --- | --- |
| `Worker count` | `2` | Number of worker processes. |
| `Max concurrent I/O tasks` | `1` | How many disk-heavy tasks run at once. |

Workers are the processes that run everything in the background. More of them means more tasks in parallel like identifying, scanning, compressing.

The second setting ensures CPU/disk heavy tasks do not loose the benefit of parallelism. Compression, decompression and verification read and write multi-GB files, and running several of them at once can be detrimental. If the files are on the same hard drive, parallel tasks will make the heads seek back and forth and will make processing time significantly longer.  So this limit caps them independently of the worker count, while light tasks keep flowing. Pick it based on where your library lives:

* __Network share or a single hard drive: `1`__ - avoids seek thrashing, the safe default.
* __SATA SSD: `2` to `3`__ - no seek penalty, so you are limited by CPU.
* __NVMe with spare CPU cores: raise it towards your core count__ - each compression uses about 3 to 4 threads, so the CPU, not the disk, is the ceiling.
