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

## Environment variables

| Variable | Description |
| --- | --- |
| `PUID` / `PGID` | UID and GID of the user running the app in the container, `1000:1000` by default. |
| `USER_ADMIN_NAME` / `USER_ADMIN_PASSWORD` | Creates (or updates) an admin user at every startup. |
| `USER_GUEST_NAME` / `USER_GUEST_PASSWORD` | Creates (or updates) a regular user with shop access at every startup. |

> [!TIP]
> You can control the `UID` and `GID` of the user running the app in the container with the `PUID` and `PGID` environment variables. By default the user is created with `1000:1000`. If you want to have the same ownership for mounted directories, you need to set those variables with the UID and GID returned by the `id` command.

# Using the Helm chart

The chart lives in [`chart/`](./chart) of this repository - there is no chart repository to add, so clone this repo first, then from the `chart` directory:

```
helm upgrade --install ownfoil-plus ./ -n namespace -f values.yaml
```

# Remote access and HTTPS

Exposing your shop to the internet is done with a reverse proxy in front of Ownfoil-Plus, and there are a few things it must get right.

* Send the `X-Forwarded-Proto` header, and make sure it does __not__ serve the shop over plain `http` (or redirect it to `https`). Ownfoil-Plus only enforces host verification on secure requests, so a proxy that leaves `http` open means anyone who learns your URL can use your shop.
* Don't set a small request body limit, clients download multi-GB files through it.

Once that is done, set the `Shop URL` in the `Settings` to the same hostname - see [Shop](./Usage.md#shop) for what it does and how to configure it.

# First run

On the first start Ownfoil-Plus creates the `config` and `data` directories, downloads titledb, and starts serving the Web UI on port `8465`. Open it with your computer/server IP and port, i.e. `http://localhost:8465` from the same computer or `http://192.168.1.100:8465` from a device in your network.

> [!CAUTION]
> Until an admin account is created, __authentication is disabled and anyone who can reach the Web UI can change the configuration of your shop__. Creating that account is the first thing to do.

Head over to [First steps](./Usage.md#using-ownfoil) to configure your shop.

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

    docker run ... estebankzl/ownfoil-plus:6.2.4.2

In the compose file it is the `image` line:

    image: estebankzl/ownfoil-plus:latest
