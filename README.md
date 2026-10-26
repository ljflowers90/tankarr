<p align="center">
  <img src="docs/assets/logo.svg" width="112" alt="Tankarr logo: three manga volumes on a shelf">
</p>

<h1 align="center">Tankarr</h1>

<p align="center">
  <strong>Self-hosted manga, manhwa and comics manager for the *arr stack: Sonarr for manga.</strong>
</p>

<p align="center">
  <a href="https://github.com/Renzodef/tankarr/actions/workflows/ci.yml"><img src="https://github.com/Renzodef/tankarr/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
  <a href="https://github.com/Renzodef/tankarr/releases"><img src="https://img.shields.io/github/v/release/Renzodef/tankarr?sort=semver&include_prereleases" alt="Latest release"></a>
  <a href="https://github.com/Renzodef/tankarr/pkgs/container/tankarr"><img src="https://img.shields.io/badge/image-ghcr.io%2Frenzodef%2Ftankarr-2496ED?logo=docker&logoColor=white" alt="Docker image on GitHub Container Registry"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Renzodef/tankarr" alt="License: GPL-3.0"></a>
  <a href="https://scorecard.dev/viewer/?uri=github.com/Renzodef/tankarr"><img src="https://api.scorecard.dev/projects/github.com/Renzodef/tankarr/badge" alt="OpenSSF Scorecard"></a>
  <a href="https://renzodef.github.io/tankarr/"><img src="https://img.shields.io/badge/docs-renzodef.github.io%2Ftankarr-informational" alt="Documentation"></a>
  <a href="https://renzodef.github.io/tankarr/demo/"><img src="https://img.shields.io/badge/demo-try%20it%20online-b6451b" alt="Online demo"></a>
</p>

Tankarr follows the manga, manhwa, webtoons and comics you read. It downloads
new chapters and volumes automatically in the language you choose, and files
them into a clean, reader-ready CBZ library for [Komga](https://komga.org),
[Kavita](https://www.kavitareader.com), [Stump](https://www.stumpapp.dev) or
its own built-in reader. If you know Sonarr or Radarr, you already know how it
works: add a series once, pick a monitoring profile, and Tankarr keeps the
series complete.

> ## About this fork
>
> This fork ([ljflowers90/tankarr](https://github.com/ljflowers90/tankarr))
> adds Western-comic support in the style of
> [Mylar3](https://github.com/MylarComics/mylar3), alongside the existing
> manga features. It is a work in progress, developed in milestones on
> feature branches; the upstream project is
> [Renzodef/tankarr](https://github.com/Renzodef/tankarr).
>
> **Done: milestone 1, comic catalogues** (branch `feat/comics-catalogue`)
>
> - **[ComicVine](https://comicvine.gamespot.com) and
>   [Metron](https://metron.cloud) catalogues.** Search a comic series and add
>   it to track its issues. Both are off by default and need your own
>   credentials (`TANKARR_COMICVINE_*`, `TANKARR_METRON_*`; see the
>   [configuration reference](docs/configuration.md)).
> - **Settings page.** ComicVine and Metron credentials are entered in
>   **Settings > Metadata**, each with its own **Test connection** button. Use
>   either or both: a catalogue without credentials is skipped, and the search
>   offers **All available** to query every ready catalogue at once.
> - **Storage.** New `comic_series` and `comic_issue` tables, separate from the
>   manga tables. New issues start as *wanted*. Comics are written under
>   `TANKARR_COMICS_LIBRARY_DIR` (default: a `Comics` folder in the library).
> - **Web interface.** The manga section is now labelled **Manga**, and the
>   new **Comics** section sits below it with its own **Add New** and
>   **Library Import** sub-items. Its tabs are **Library** (tracked series),
>   **Add New** (search ComicVine or Metron, then add), **Library Import**
>   (scan the import folder, or upload CBZ/CBR/PDF files, match them to tracked
>   series and issues by name and year, then copy or move them into the comics
>   library) and **Wanted** (monitored issues not yet downloaded), plus a
>   series page listing issues with monitor and remove actions. A catalogue
>   that is disabled, has no credentials or is paused is explained on the
>   search tab instead of being queried.
> - **API.** `GET /api/comics/providers`, `GET /api/comics/search`,
>   `POST /api/comics/series`, `GET /api/comics/series[/{id}]`,
>   `PUT /api/comics/series/{id}/monitored`, `DELETE /api/comics/series/{id}`,
>   `GET /api/comics/import/scan` and `POST /api/comics/import`
>   and `GET /api/comics/wanted`.
> - **Safe with rate-limited catalogues.** ComicVine requests are paced and its
>   key never appears in errors. Metron requests are sent one at a time, five
>   seconds apart (its limit is 15 a minute), are never retried, and stop
>   completely after a 401/403 (until you fix the credentials and restart) or a
>   429 (for an hour). Metron's `X-RateLimit-*` headers are honoured.
>
> **Not built yet:** issue release parsing and the Wanted search, indexer
> search and sending to download clients (qBittorrent, SABnzbd, NZBGet),
> post-processing and `ComicInfo.xml` for issues, importing an existing
> CBZ/CBR library, and story arcs and the pull list.
>
> Everything else in this README describes upstream Tankarr and applies
> unchanged.

**[Try it online](https://renzodef.github.io/tankarr/demo/)**: the real
interface on a library of well-known manga, manhwa and manhua, every page and
the built-in reader, nothing to install.

<p align="center">
  <a href="https://renzodef.github.io/tankarr/screenshots/"><img src="docs/assets/screenshots/library.webp" width="880" alt="The Tankarr Library: a grid of series covers with chapter counts, language and status badges"></a>
</p>
<p align="center">
  <a href="https://renzodef.github.io/tankarr/screenshots/"><img src="docs/assets/screenshots/series.webp" width="49%" alt="A series page with the publisher's release rhythm and the chapter list"></a>
  <a href="https://renzodef.github.io/tankarr/screenshots/"><img src="docs/assets/screenshots/calendar.webp" width="49%" alt="The Calendar week view with released, available and expected chapters"></a>
</p>
<p align="center"><sub>A fictional library, generated for the documentation. <a href="https://renzodef.github.io/tankarr/screenshots/">More screenshots</a>.</sub></p>

- **Add a work, not a website.** Series are identified through the
  [MangaBaka](https://mangabaka.org) catalogue (with MangaUpdates, AniList,
  Kitsu and MyAnimeList IDs). Download sources are mapped afterwards, so a
  badly named mirror never decides what a series is.
- **Every kind of source.** A managed [Suwayomi](https://github.com/Suwayomi/Suwayomi-Server)
  engine with Mihon/Tachiyomi-compatible extensions, [Prowlarr](https://prowlarr.com)
  indexers with qBittorrent (torrents) and SABnzbd (Usenet), the Internet
  Archive, and a local import folder for the files you already own.
- **The language belongs to the release.** A Japanese manga can be followed in
  English, Italian or any language a translation exists in. Downloads from
  indexers are checked with OCR before they enter the library.
- **Chapters or volumes.** Tankarr reads what a series actually offers, follows
  chapters while a work is running and volumes once it is collected, and can
  assemble chapters into books.
- **A library that stays clean.** Consistent naming, `ComicInfo.xml` metadata,
  covers, hash-checked atomic imports, a recycle bin, and page-quality checks
  that replace unreadable downloads.
- **The *arr experience.** Library, Calendar, Activity queue, Wanted, History,
  interactive release search, monitoring profiles, and a System page with
  health checks, scheduled tasks, logs and one-click backups.
- **In your language.** The interface is available in English and Italian,
  chosen per browser; another language is one JSON file away.
- **Built to be operated.** Notifications to ntfy, Discord, Telegram, Apprise
  or any webhook; an API key and Prometheus metrics; forms, basic or
  reverse-proxy (`Remote-User`) authentication; `PUID`/`PGID`; verified
  automatic backups and safe restores.
- **Runs anywhere Docker runs.** Multi-architecture images for `linux/amd64`
  and `linux/arm64` (Raspberry Pi 4 and 5 included), a Compose file, an
  Unraid template and a Helm chart.

If Tankarr is useful to you, a star on GitHub helps other readers find it.

## Quick start

Tankarr is distributed as a Docker image on the GitHub Container Registry.
Create a `docker-compose.yml`:

```yaml
services:
  tankarr:
    image: ghcr.io/renzodef/tankarr:latest
    container_name: tankarr
    environment:
      PUID: 1000                    # the user and group that own your folders
      PGID: 1000
      TZ: Etc/UTC
    volumes:
      - ./config:/config            # database, settings, cache, backups
      - /path/to/comics:/library    # your manga and comics library
      - /path/to/import:/import:ro  # optional: files to add to the library
    ports:
      - "8787:8787"
    restart: unless-stopped
```

Start it, read the login Tankarr creates on its first start, and open
<http://localhost:8787>:

```sh
docker compose up -d
docker compose logs tankarr | grep "created one"
```

Tankarr never runs without a login: you can also choose your own with
`TANKARR_AUTH_USERNAME` and `TANKARR_AUTH_PASSWORD`, and change it any time
under **Settings → Security**. The setup page then walks you through the
library, the reader, the download sources and the optional indexers. The
[installation guide](https://renzodef.github.io/tankarr/installation/) covers
`docker run`, permissions, reverse proxies, Raspberry Pi and running from
source.

## Documentation

The full documentation lives at **<https://renzodef.github.io/tankarr/>**
(sources in [`docs/`](docs/)):

| Guide | What it covers |
| --- | --- |
| [Installation](docs/installation.md) | Docker Compose, `docker run`, Unraid, Kubernetes (Helm), folders and permissions, reverse proxy, building from source |
| [Getting started](docs/getting-started.md) | First login, setup checklist, adding series, monitoring profiles, your first download |
| [Configuration](docs/configuration.md) | Every `TANKARR_*` environment variable and its default |
| [Integrations](docs/integrations.md) | Suwayomi, Prowlarr, qBittorrent, SABnzbd, Internet Archive, Komga, Kavita, Stump, notifications (ntfy, Discord, Telegram, Apprise, webhooks), Prometheus |
| [How Tankarr works](docs/how-it-works.md) | Identity, numbering, official editions, Wanted recovery, page quality |
| [Compared with other tools](docs/comparison.md) | Where Tankarr sits next to Mylar3, Kapowarr, Suwayomi and readers like Komga |
| [Screenshots](docs/screenshots.md) | Every page of the interface |
| [Upgrading](docs/upgrading.md) | Release channels, image tags, backups and rollback |
| [FAQ and troubleshooting](docs/faq.md) | Common questions and problems |

## Release channels

Tankarr is published the way the other *arr applications are, as Docker images
on a registry with a stable channel and immutable builds:

| Image tag | Built from | Use it for |
| --- | --- | --- |
| `latest`, `X.Y.Z`, `X.Y` | a release tag on `main` | Stable releases. Recommended. |
| `branch-<name>` | a branch with an open pull request | Trying a change before it is merged. |
| `sha-<commit>` | any published build | Pinning or rolling back to one exact build. |

Release notes are on the [releases page](https://github.com/Renzodef/tankarr/releases).

## FAQ

**Is Tankarr a "Sonarr for manga"?**
Yes. It brings the Sonarr and Radarr workflow (monitored series, a Wanted list,
a download queue, release profiles and a calendar) to manga, manhwa, manhua,
webtoons and comics, and it integrates with the same tools: Prowlarr,
qBittorrent and SABnzbd.

**How is it different from Mylar3, Kapowarr or Suwayomi?**
Mylar3 and Kapowarr are built around ComicVine and Western comic books;
Suwayomi and Mihon are readers with source extensions. Tankarr identifies works
through manga catalogues, follows chapters across editions and languages, uses
Suwayomi as one of several download channels, and writes a library for your
reader. The [comparison](docs/comparison.md) goes through it tool by tool.

**Does Tankarr host or distribute manga?**
No. Tankarr contains no content and no sources of its own. It automates the
tools and sources that you configure. You are responsible for complying with
the laws of your country and the terms of the services you use. Please support
the creators and official publishers of the works you enjoy.

**Which readers does it work with?**
Any reader that can open a folder of CBZ files. Tankarr has a built-in web
reader and can drive Komga and Stump directly (library scans, metadata and
covers). Kavita and other readers work by pointing them at the same library
folder.

**Does it run on a Raspberry Pi?**
Yes. The image is built for `arm64` and Tankarr is developed on a Raspberry Pi 5.
Allow about 1.5 GB of memory for the container when the managed Suwayomi
engine is enabled.

## Contributing

Bug reports, ideas and pull requests are welcome. Read the
[contributing guide](CONTRIBUTING.md): changes go through pull requests
against `main`, and nothing is pushed to it directly. For questions and
ideas, open a [discussion](https://github.com/Renzodef/tankarr/discussions).

Please report security vulnerabilities privately, as described in the
[security policy](SECURITY.md).

## License

Tankarr is free software released under the
[GNU General Public License v3.0](LICENSE).
