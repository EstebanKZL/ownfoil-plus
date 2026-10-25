# Ownfoil-Plus

[![GitHub repo](https://img.shields.io/badge/github-repo-24292e?logo=github)](https://github.com/EstebanKZL/ownfoil-plus)
[![Latest Release](https://img.shields.io/docker/v/estebankzl/ownfoil-plus?sort=semver&color=0969da)](https://github.com/EstebanKZL/ownfoil-plus/releases/latest)
[![Docker Image Size](https://img.shields.io/docker/image-size/estebankzl/ownfoil-plus?sort=date&arch=amd64&color=fb8500)](https://hub.docker.com/r/estebankzl/ownfoil-plus/tags)
[![Docker Pulls](https://img.shields.io/docker/pulls/estebankzl/ownfoil-plus?color=06b6d4)](https://hub.docker.com/r/estebankzl/ownfoil-plus)
![Platforms](https://img.shields.io/badge/platforms-amd64%20%7C%20arm64%2Fv8%20%7C%20arm%2Fv7%20%7C%20arm%2Fv6-8A2BE2)
![Web UI language](https://img.shields.io/badge/Web%20UI-%F0%9F%87%AC%F0%9F%87%A7%20English%20%7C%20%F0%9F%87%AA%F0%9F%87%B8%20Espa%C3%B1ol-ffc107)

Ownfoil-Plus turns a folder of game files into a fully organized, self-verified, self-hosted Nintendo Switch shop: it figures out what you have, flags what's missing or broken, keeps your files tidy, and serves everything to your console in your language - all from one web interface, no manual bookkeeping required.

It's a fork of [Ownfoil](https://github.com/a1ex4/ownfoil) by [@a1ex4](https://github.com/a1ex4), built for people who want the convenience of a managed shop without babysitting it: a bilingual interface instead of an English-only one, an admin toolkit deep enough to actually fix problems when they come up instead of just reporting them, and a Docker image that keeps itself patched instead of quietly accumulating known vulnerabilities between releases.

## Why this image

- **Rebuilt on a schedule, not just on release.** Every image is rebuilt weekly, pulling fresh base-image and OS security patches even on weeks with no code changes - a known CVE in the base layer doesn't just sit there published until someone happens to push a new feature.
- **Built, not just copied.** Fixes here are verified against the real upstream source and real client behavior (Sphaira's actual GraphQL queries, actual access logs) before they ship, with an automated test suite guarding every change - see [CHANGELOG.md](https://github.com/EstebanKZL/ownfoil-plus/blob/main/CHANGELOG.md) for the specifics of every version.
- **Multi-arch from day one**: `amd64`, `arm64/v8`, `arm/v7`, and `arm/v6` - runs the same on a NAS, a Raspberry Pi, or a full server.

## What it does

- **Organizes** your library automatically into consistent folders and filenames, using templates you control.
- **Verifies** file integrity (signature and hash) and flags anything corrupt or repacked.
- **Detects missing content**: which updates or DLC exist for a title you already own but haven't downloaded yet.
- **Resolves duplicate files** safely - it never deletes anything blindly. It only acts automatically when verification gives a clear, unambiguous answer, or when you pick which copy to keep yourself.
- **Serves your library** as a real shop to Sphaira, Tinfoil, and CyberFoil, with LAN discovery so a console can find it with no IP address to type in.
- **Full bilingual web interface** (English/Spanish), with live task monitoring, a dedicated Files admin page, and settings backup/restore.

## What this fork adds on top of upstream Ownfoil

- 🇬🇧🇪🇸 A full Spanish/English web interface, switch anytime from the navbar
- A List view showing every game with its updates and DLC in one place, including what's still missing from your library
- A filter to quickly find titles that are complete, incomplete, or have a corrupt or repack file anywhere in them
- A richer game info panel - genre, players, rating, languages, file size, screenshots - opens from any view by clicking the cover
- Editable game info: fix or fill in a title's name, developer, description, and more by hand, and it stays that way even after the catalogue updates
- Local caching of game artwork, so covers and banners keep working even if the remote image host is unreachable
- A dedicated Files admin page: search, filter, and per-file retry/verify/compress/decompress/delete actions, plus one-click cleanup for duplicates and outdated updates
- Duplicate file detection and resolution, automatic (your choice of preferring the larger file, the compressed one, or a multi-content bundle) and manual, one at a time or in bulk
- A live view of what's actually happening in the background - task progress and what each worker is doing, in real time
- A direct "Verify library now" action, and other library management improvements
- Settings export/import from the web UI

## Quick start

```bash
docker run -d -p 8465:8465 \
   -v /path/to/your/library:/games \
   -v ./config:/app/config \
   -v ./data:/app/data \
   --name ownfoil-plus \
   estebankzl/ownfoil-plus
```

Or with Docker Compose:

```yaml
services:
  ownfoil-plus:
    container_name: ownfoil-plus
    image: estebankzl/ownfoil-plus:latest
    environment:
      # - TZ=America/Argentina/Buenos_Aires
      # For write permission in the config directory
      - PUID=1000
      - PGID=1000
      # To create/update an admin user at startup
      # - USER_ADMIN_NAME=admin
      # - USER_ADMIN_PASSWORD=asdvnf!546
      # To create/update a regular user at startup
      # - USER_GUEST_NAME=guest
      # - USER_GUEST_PASSWORD=oerze!@8981
      # - ROOT_DIR=/games
      # - SAVE_ENABLED=true
    volumes:
      - /path/to/your/library:/games
      - ./config:/app/config
      - ./data:/app/data
    ports:
      - "8465:8465"
```

Once it's running, open `http://<your-server-ip>:8465` in your browser to set up your library.

Full installation and configuration guide: https://github.com/EstebanKZL/ownfoil-plus

## About this project

Ownfoil-Plus is a modified version of Ownfoil, an open-source project created by [@a1ex4](https://github.com/a1ex4), distributed under the GNU AGPLv3 license. As required by the AGPLv3, the complete source code of this modified version - including these changes - is publicly available at https://github.com/EstebanKZL/ownfoil-plus.
