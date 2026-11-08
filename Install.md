# Installing Ownfoil-Plus

Ownfoil-Plus is a web server listening on port `8465`, so anything that can run a Docker container or a Python environment will do - a NAS, a Raspberry Pi, an old laptop or your own desktop.

- [Using Docker](#using-docker)
- [Using the Helm chart](#using-the-helm-chart)
- [Available versions](#available-versions)

> [!CAUTION]
> There is __no website associated with this project__, only this GitHub repo.  
> Ownfoil-Plus is __not released as an application or an executable file__ - DO NOT download or execute anything related to Ownfoil-Plus outside of this repository and its instructions.

# Using Docker
Ownfoil-Plus is shipped as a docker container for easy deployment, data persistency and updates. If you are unfamiliar with Docker, check [the installation documentation here](https://docs.docker.com/engine/install/).  
## Docker run

<details>

Running this command will start the shop on local port `8465` with the library in `/your/game/directory`, and persist the `data` and `config` directories:
```
docker run -d -p 8465:8465 \
   -v /your/game/directory:/games \
   -v ./config:/app/config \
   -v ./data:/app/data \
   --name ownfoil-plus \
   estebankzl/ownfoil-plus
```
To see the logs of the container:  

      docker logs -f ownfoil-plus

</details>

## Docker compose
<details>

Create a file named `docker-compose.yml` with the following content:
```
---
services:
  ownfoil-plus:
    container_name: ownfoil-plus
    image: estebankzl/ownfoil-plus
   # environment:
   #   # For write permission in config directory
   #   - PUID=1000
   #   - PGID=1000
   #   # to create/update an admin user at startup
   #   - USER_ADMIN_NAME=admin
   #   - USER_ADMIN_PASSWORD=asdvnf!546
   #   # to create/update a regular user at startup
   #   - USER_GUEST_NAME=guest
   #   - USER_GUEST_PASSWORD=oerze!@8981
    volumes:
      - /your/game/directory:/games
      - ./data:/app/data
      - ./config:/app/config
    ports:
      - "8465:8465"
```

You can then create and start the container with the command (executed in the same directory as the docker-compose file):

    docker-compose up -d

This is usefull if you don't want to remember the `docker run` command and have a persistent and reproductible container configuration.
</details>

## Volumes

| Container path | What to mount there |
| --- | --- |
| `/games` | Your library. You can mount several of them, and add each one in the `Settings`. |
| `/app/config` | The config directory. Back this one up. |
| `/app/data` | The titledb cache. |

### Behind a reverse proxy: the save vault

JKSV uploads save backups to `/dav/` (see Usage > Save vault). If a reverse proxy sits in front, let it pass the WebDAV methods (`PROPFIND`, `MKCOL`, `MOVE`, `PUT`, `DELETE`) and large request bodies to that path - for nginx, `client_max_body_size 4g;` - and keep it on your LAN or behind a VPN.

## Environment variables

| Variable | Description |
| --- | --- |
| `PUID` / `PGID` | UID and GID of the user running the app in the container, `1000:1000` by default. |
| `USER_ADMIN_NAME` / `USER_ADMIN_PASSWORD` | Creates (or updates) an admin user at every startup. |
| `USER_GUEST_NAME` / `USER_GUEST_PASSWORD` | Creates (or updates) a regular user with shop access at every startup. |
| `OWNFOIL_SECRET_KEY` (or `SECRET_KEY`) | Optional. The key that signs login cookies and the links in account emails. When unset, a random one is generated on first start and kept in `config/.secret_key` - keep that file private. `OWNFOIL_SECRET_KEY` wins when both are set. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Optional. The mail server for account emails (verifying a registration, resetting a password). `SMTP_SECURITY` is `TLS` (STARTTLS, port 587 by default), `SSL` (port 465) or `NONE`. Needed for public registration with the form and for password resets. Step by step, with Gmail and Outlook: [Public registration](#public-registration-email-smtp-and-google-sign-in). |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Optional. "Sign in with Google". Create an OAuth client (web application) in the Google Cloud console and add `GOOGLE_REDIRECT_URI` - your server's public address followed by `/login/google/callback` - as an authorized redirect URI. Step by step: [Sign in with Google](#3-sign-in-with-google). |
| `OWNFOIL_METRICS_TOKEN` | Optional. A token Prometheus can send as `Authorization: Bearer <token>` to read `/metrics`, instead of an admin username and password. See [Monitoring with Prometheus](#monitoring-with-prometheus). |

> [!TIP]
> You can control the `UID` and `GID` of the user running the app in the container with the `PUID` and `PGID` environment variables. By default the user is created with `1000:1000`. If you want to have the same ownership for mounted directories, you need to set those variables with the UID and GID returned by the `id` command.

# Public registration: email (SMTP) and Google sign-in

People can make their own accounts with the form on the sign-in page (needs email) or with
"Sign in with Google" (needs a Google OAuth client). Both are set with environment
variables - their secrets never go in `settings.yaml` or the web UI - and turned on in
`Settings > Registration`.

## 1. The server's public address

Links in account emails (verify a registration, reset a password) and Google's redirect
need the address people reach the server at, such as `https://shop.example.com`. Set it in
`Settings > Registration > Server's public address`. It must be the real public address
behind your reverse proxy (see [Remote access and HTTPS](#remote-access-and-https)): it is
never taken from the request, which anyone can forge.

## 2. Email (SMTP)

| Variable | Example | Notes |
| --- | --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` | Required. |
| `SMTP_FROM` | `Ownfoil-Plus <shop@example.com>` | Required. The sender; many providers only accept your own address. |
| `SMTP_SECURITY` | `TLS` | `TLS` (STARTTLS), `SSL` or `NONE`. Default `TLS`. |
| `SMTP_PORT` | `587` | Default 587 for `TLS`, 465 for `SSL`. |
| `SMTP_USER` | `shop@example.com` | Leave empty for a relay that needs no login. |
| `SMTP_PASSWORD` | an app password | |

Common providers:

| Provider | `SMTP_HOST` | `SMTP_SECURITY` / `SMTP_PORT` | Password |
| --- | --- | --- | --- |
| Gmail / Google Workspace | `smtp.gmail.com` | `TLS` / `587` | An [app password](https://myaccount.google.com/apppasswords) (needs 2-step verification), not your Google password. |
| Outlook.com / Microsoft 365 | `smtp.office365.com` | `TLS` / `587` | Your account password, or an app password with 2-step verification. |
| Brevo, Mailgun, SendGrid, Amazon SES... | the provider's SMTP host | `TLS` / `587` | The SMTP key the provider gives you. |
| Your own mail server or relay | its host name | as it is set up | - |

Docker Compose:

```yaml
    environment:
      - SMTP_HOST=smtp.gmail.com
      - SMTP_PORT=587
      - SMTP_SECURITY=TLS
      - SMTP_USER=shop@example.com
      - SMTP_PASSWORD=abcd efgh ijkl mnop      # a Gmail app password
      - SMTP_FROM=Ownfoil-Plus <shop@example.com>
```

`docker run`: add `-e SMTP_HOST=smtp.gmail.com -e SMTP_USER=... -e SMTP_PASSWORD=... -e SMTP_FROM=...`.
Recreate the container after changing them (`docker compose up -d`).

Check it: `Settings > Registration` shows `Email (SMTP): Set up`, and `Send a test email
to` sends one to the address you type. If it fails, the message says why (wrong password,
port blocked by the host, sender refused).

## 3. Sign in with Google

1. Open the [Google Cloud console](https://console.cloud.google.com/), create a project
   (or pick one) and go to `APIs & Services`.
2. `OAuth consent screen`: choose `External`, fill in the app name and your email. The
   scopes it needs are the basic ones: `openid`, `email` and `profile`. While the app is
   in `Testing`, only the test users you add can sign in; `Publish app` opens it to
   everyone (no Google review is needed for these scopes).
3. `Credentials > Create credentials > OAuth client ID`, type `Web application`:
   - **Authorized redirect URIs**: your public address followed by
     `/login/google/callback`, exactly, e.g. `https://shop.example.com/login/google/callback`.
   - Create it and copy the **Client ID** and **Client secret**.
4. Give them to the container:

```yaml
    environment:
      - GOOGLE_CLIENT_ID=1234567890-abc123.apps.googleusercontent.com
      - GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxx
      - GOOGLE_REDIRECT_URI=https://shop.example.com/login/google/callback
```

`GOOGLE_REDIRECT_URI` must match the one in the Google console character for character
(`https`, no trailing slash). Google only accepts `https` redirects, except for
`http://localhost`, so a server reached by its LAN address (`http://192.168.1.100:8465`)
needs a domain with HTTPS behind a reverse proxy for this.

Check it: `Settings > Registration` shows `Google sign-in: Set up`, and the sign-in page
shows `Sign in with Google`.

## 4. Turn it on

`Settings > Registration > Allow public registration` (or its switch in `Services`). New
accounts get shop access only - never the administration or the saves. What each way of
signing up does, step by step: [User registration](./Usage.md#user-registration).

# Using the Helm chart

The chart lives in [`chart/`](./chart) of this repository - there is no chart repository to add, so clone this repo first, then from the `chart` directory:

```
helm upgrade --install ownfoil-plus ./ -n namespace -f values.yaml
```

# Remote access and HTTPS

Exposing your shop to the internet is done with a reverse proxy in front of Ownfoil-Plus, and there are a few things it must get right.

* Send the `X-Forwarded-Proto` header, and make sure it does __not__ serve the shop over plain `http` (or redirect it to `https`). Ownfoil-Plus only enforces host verification on secure requests, so a proxy that leaves `http` open means anyone who learns your URL can use your shop.
* Don't set a small request body limit, clients download multi-GB files through it. Web uploads send 8 MiB chunks, grow them up to 64 MiB while the network keeps up, and shrink them down to 512 KiB if the proxy refuses them (nginx's default `client_max_body_size` is `1m`); `client_max_body_size 64m;` (or more) keeps uploads fast. On your own LAN, uploading through the server's local address (`http://192.168.x.x:8465`) skips the proxy and its TLS, and is usually much faster than through the public domain.

Once that is done, set the `Shop URL` in the `Settings` to the same hostname - see [Shop](./Usage.md#shop) for what it does and how to configure it.

# Monitoring with Prometheus

`/metrics` serves library-level metrics in Prometheus' text format: files and total size, unidentified files, owned / complete / up-to-date games, files per verification status, tasks per status (including failed), downloads, free and total disk space and reachability per library, backup count and age, users, and whether the shop is public. `/api/health` is the separate, unauthenticated liveness check.

It needs an admin account (Basic Auth) or, if you'd rather not put a password in the scrape config, the `OWNFOIL_METRICS_TOKEN` environment variable:

```yaml
scrape_configs:
  - job_name: ownfoil-plus
    static_configs:
      - targets: ['ownfoil-plus:8465']
    # either an admin account...
    basic_auth:
      username: admin
      password: your-admin-password
    # ...or, with OWNFOIL_METRICS_TOKEN set on the container:
    # authorization:
    #   credentials: your-metrics-token
```

Useful alerts: `ownfoil_library_online == 0`, `ownfoil_tasks{status="failed"} > 0`, `time() - ownfoil_backup_last_timestamp_seconds > 2 * 86400`, and free space from `ownfoil_library_disk_free_bytes / ownfoil_library_disk_total_bytes`.

# LAN discovery

The `Services` admin page has a toggle (also in `Settings > Server network`, with these notes) to let Sphaira and other compatible clients find this shop on the local network automatically, with no address to type in on the console. It listens on UDP port `8465`, which needs to actually be reachable on the LAN:

* Docker: the container must use the host's network - add `network_mode: host` to `docker-compose.yml` (commented out there by default) instead of the `ports` mapping, or pass `--network host` to `docker run`.
* Windows: the firewall must allow this app on private networks, or the broadcast never reaches it.

# First run

On the first start Ownfoil-Plus creates the `config` and `data` directories, downloads titledb, and starts serving the Web UI on port `8465`. Open it with your computer/server IP and port, i.e. `http://localhost:8465` from the same computer or `http://192.168.1.100:8465` from a device in your network.

> [!CAUTION]
> Until an admin account is created, __authentication is disabled and anyone who can reach the Web UI can change the configuration of your shop__. Creating that account is the first thing to do.

Head over to [First steps](./Usage.md#using-ownfoil-plus) to configure your shop.

# Updating

Updating is just replacing the version you run.

* Docker: `docker pull estebankzl/ownfoil-plus` then recreate the container
* Docker compose: `docker compose pull && docker compose up -d`
* Helm: bump `image.tag` and run the `helm upgrade` command again

# Available versions

Whichever way you install it, you run one of these:

| Version | What you get |
| --- | --- |
| `latest` | The most recent release, default when you don't select a version in particular. |
| A version number | That exact release, and the way to stay on a known version. |

Versions are `major.minor.patch`, and each part can be used on its own to pin a specific "release channel" when upgrading:

* [![major version](https://img.shields.io/badge/dynamic/regex?url=https%3A%2F%2Fapi.github.com%2Frepos%2FEstebanKZL%2Fownfoil-plus%2Freleases%2Flatest&search=%22tag_name%22%3A%5Cs%2A%22%28%5B0-9%5D%2B%29&replace=%241&label=)](https://github.com/EstebanKZL/ownfoil-plus/releases/latest) is the `major` version, unlikely to change. Using it means the latest release of that major version.
* [![minor version](https://img.shields.io/badge/dynamic/regex?url=https%3A%2F%2Fapi.github.com%2Frepos%2FEstebanKZL%2Fownfoil-plus%2Freleases%2Flatest&search=%22tag_name%22%3A%5Cs%2A%22%28%5B0-9%5D%2B%5C.%5B0-9%5D%2B%29&replace=%241&label=)](https://github.com/EstebanKZL/ownfoil-plus/releases/latest) is the `minor` version, bumped when new features are introduced. Using it means the latest patch of that minor version, so including bug fixes but no new features.
* [![patch version](https://img.shields.io/badge/dynamic/regex?url=https%3A%2F%2Fapi.github.com%2Frepos%2FEstebanKZL%2Fownfoil-plus%2Freleases%2Flatest&search=%22tag_name%22%3A%5Cs%2A%22%28%5B0-9%5D%2B%5C.%5B0-9%5D%2B%5C.%5B0-9%5D%2B%29&replace=%241&label=)](https://github.com/EstebanKZL/ownfoil-plus/releases/latest) is the `patch` version, increased for a release that only fixes bugs in the latest minor version.

Releases and what changed in them are on the [releases page](https://github.com/EstebanKZL/ownfoil-plus/releases).

## Docker

The version is the image tag, `latest` when you don't set one:

    docker run ... estebankzl/ownfoil-plus:6.2.4.16

In the compose file it is the `image` line:

    image: estebankzl/ownfoil-plus:latest
