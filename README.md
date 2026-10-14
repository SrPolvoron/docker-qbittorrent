# Docker qBittorrent — SrPolvoron

A standalone, private qBittorrent download service for Debian/Linux hosts using Docker Compose. It can download games, books, software, video and other files **without Jellyfin**, and optionally connect to Radarr/Sonarr in another Compose project. No migrations, database, reverse proxy or open Web UI ports are required.

[Leer en español](docs/README.es.md)

## Architecture and safe defaults

| Concern | Default | Optional |
| --- | --- | --- |
| Deployment | One Compose-managed qBittorrent instance | Connect it to other Compose projects |
| Web UI | `127.0.0.1:8081` on the **host**, accessed over SSH | Additional host WireGuard IP binding (`--vpn`) |
| BitTorrent | Outbound connections on the host's ordinary network; **no published inbound P2P port** | Explicit future change, not included |
| Application state | `/srv/qbittorrent/config` | Configurable with `CONFIG_ROOT` |
| Download data | `/srv/qbittorrent/data` | Configurable with `DATA_ROOT` |
| Optional media DNS | No cross-project network | `qbittorrent-standalone:8081` on `media-downloads` |
| Software version | Immutable digest resolved at installation | Manually refresh with `./stack lock --refresh` |

This is a **new instance**, not a migration of Jellyfin's existing qBittorrent. The default Web UI port `8081` avoids a typical collision with its `8080`. State must NEVER be shared between the two running instances. No changes are made to another repository.

**Security boundary:** SSH and host WireGuard protect access to the Web UI, not BitTorrent egress. Torrent peers see the public IP used for outbound traffic from the Docker host. A WireGuard tunnel between a home server and an OVH proxy does **not** automatically provide an external VPN egress for torrent traffic.

## Requirements

- Debian or another Linux Docker host (`amd64` or `arm64` for the upstream image).
- Docker Engine (28+ recommended), Docker Compose plugin 2.24+ and Python 3.10+.
- Working SSH access, preferably with key-based authentication; an account with Docker permissions to manage containers. Docker access is equivalent to root-equivalent host privileges.
- Free disk space and write access to chosen host storage directories; `sudo` for provisioning paths under `/srv`.
- Optional `iproute2`, `wireguard-tools` and an **already configured host WireGuard interface** for `--vpn`. Optional existing Docker bridge network for `--media`.

No Python packages are required. The `stack` script reads literal `.env` values without executing shell code.

## Quick start — SSH-only, no other services

```bash
# In this repository
./stack init
id -u
id -g
nano .env                    # Set your actual PUID/PGID and storage paths
./stack check
sudo ./stack prepare         # Creates only missing directories; never chowns old data
./stack lock                 # Resolve upstream image to an immutable digest
./stack config               # Inspect the fully rendered Compose model
./stack up
./stack status
./stack logs --tail 100     # On first start, get the TEMPORARY 'admin' password
```

`./stack init` will not overwrite an existing `.env`. `./stack lock` deliberately resolves the current stable upstream image and writes the digest to `images.lock.env`; it will not update that digest again unless you pass `--refresh`. The `.env` and lock file are private, host-specific and ignored by Git.

From your workstation, connect through your SSH alias (replace `casa` with yours):

```bash
ssh -N -o ExitOnForwardFailure=yes -L 8081:127.0.0.1:8081 casa
```

Open **http://127.0.0.1:8081** on your workstation. Log in as `admin` with the temporary password shown in container logs. **Change the username/password in Tools → Options → Web UI immediately.** Until a permanent password is set, the upstream container prints a new temporary password on subsequent restarts. Do not publish logs containing credentials.

### Initialize categories and download paths

After changing the password, from the **Docker host** run:

```bash
./stack categories              # Prompts for the Web UI password; never stores it
# Or, if you changed the admin username:
./stack categories --username myuser
```

This uses the loopback Web API and sets the default save path, incomplete path and automatic torrent management; it adds/verifies these categories:

| Category | Container save directory | Use |
| --- | --- | --- |
| `movies` | `/data/torrents/standalone/movies` | Radarr |
| `tv` | `/data/torrents/standalone/tv` | Sonarr |
| `books` | `/data/torrents/standalone/books` | Manual |
| `games` | `/data/torrents/standalone/games` | Manual |
| `software` | `/data/torrents/standalone/software` | Manual |
| `other` | `/data/torrents/standalone/other` | Default/manual |
| *incomplete* | `/data/torrents/standalone/incomplete` | Temporary files (not a category) |

The script verifies the saved paths and refuses to overwrite an existing category with a different path. It does not import media into Jellyfin or manage trackers. To download from your workstation, add magnet links or `.torrent` files in the Web UI. For filesystem access use your existing SSH/SFTP account with appropriate directory permissions. For example:

```bash
sftp casa
# Inside sftp, enter: cd /srv/qbittorrent/data/torrents/standalone/books
# Then: ls / get filename.ext
```

The host path changes if you customized `DATA_ROOT`. Treat downloaded archives and executables as untrusted; inspect or scan them before opening.

### Existing downloads, deletion and seeding

This fresh instance doesn't automatically inspect or migrate old downloads. Removing an item from Seerr, Radarr or Jellyfin does **not** automatically remove it here. Likewise, the torrent client does not delete library files by itself. Set seeding ratio/time rules in qBittorrent if desired, respecting your trackers' rules; avoid enabling automatic data deletion without planning the impact on media hardlinks.

## Optional WireGuard Web UI access

SSH access remains available. To additionally publish the Web UI **only on a WireGuard IPv4 address assigned to the Docker host**, edit `.env`:

```dotenv
WG_INTERFACE=wg0
WG_BIND_IP=10.77.0.2
```

The address is illustrative; use the **actual host interface address**, not your workstation's IP or the public OVH address. Then:

```bash
./stack check --vpn
./stack config --vpn
./stack up --vpn
```

`./stack up --vpn` checks that the address belongs to a running WireGuard interface. Docker publishes to that address alongside `127.0.0.1`; it does not create peers, routes or firewall rules. The accessing device must have a valid route to that private address; a home↔OVH tunnel alone is not enough for arbitrary remote clients. Review firewall policies because Docker-published ports can bypass some host firewall frontends. Do not set `WG_BIND_IP` to `0.0.0.0`, disable CSRF or host-header protection, or expose the Web UI through Traefik.

**Mode persistence:** Use `./stack up --vpn` on subsequent recreations if you want the VPN binding retained. Omitting `--vpn` intentionally returns to SSH-only exposure. Combine with `--media` if required.

## Optional Radarr/Sonarr / Jellyfin integration

First, decide on **storage before starting downloads**. If your other project mounts the host's `/srv/media` as `/data` inside Radarr/Sonarr, the simplest hardlink-capable option is:

```dotenv
DATA_ROOT=/srv/media
```

Keep `CONFIG_ROOT=/srv/qbittorrent/config` separate. New files will be in `/srv/media/torrents/standalone/...`, **not** in the existing qBittorrent's category directories. Radarr/Sonarr can read them as `/data/torrents/standalone/...`; this prevents Remote Path Mapping and lets hardlinks work if source/destination are on the same filesystem. Being under `/srv/media` does not make `books`, `games` or `other` part of Jellyfin's scanned library: only include the appropriate `/data/media` directories in Jellyfin libraries.

If you keep the default independent `/srv/qbittorrent/data`, you must also mount that host path into Radarr/Sonarr and configure matching container paths or Remote Path Mapping. Hardlinks only work on the same filesystem. **Do not change `DATA_ROOT` after downloads exist without an explicit data relocation and path review.**

Create the shared network and opt into it:

```bash
./stack network-create
./stack up --media
# Or: ./stack up --media --vpn
```

In the other project's Compose file, connect **Radarr and Sonarr** to `media-downloads` while retaining all of their original networks. Example *fragment* (merge with existing service definitions; don't replace their whole Compose):

```yaml
services:
  radarr:
    networks:
      default: {}
      media_downloads: {}
  sonarr:
    networks:
      default: {}
      media_downloads: {}
networks:
  media_downloads:
    external: true
    name: media-downloads
```

`default` above is illustrative: retain whatever original network names your Jellyfin Compose actually uses. Recreate those services using their **own** deployment process. Do not remove the existing qBittorrent unless that is an independently chosen future task.

Add a new download client in Radarr/Sonarr with these settings:

| Setting | Radarr | Sonarr |
| --- | --- | --- |
| Host | `qbittorrent-standalone` | `qbittorrent-standalone` |
| Port | `8081` | `8081` |
| SSL | Off (Docker-local network) | Off |
| Username/password | New standalone qBittorrent Web UI credentials | Same |
| Category | `movies` | `tv` |
| Download path | Already accessible via `/data` when using shared storage | Same |

This **adds** a second client; existing Radarr/Sonarr rules keep using their previous client unless you reconfigure selection/priorities. Use *Test* in each application's download-client settings, then test a legal sample torrent and successful import. If Web UI host-header validation rejects its Docker hostname, add only `qbittorrent-standalone` to the allowed domain names in qBittorrent Web UI security settings; do not disable host-header or CSRF checking.

> Shared Docker networks let connected containers communicate even though the host Web UI port binds only to loopback. Strong Web UI authentication remains necessary. Do not attach unrelated/untrusted containers to the shared network.

## Lifecycle, upgrades, backups and recovery

```bash
./stack check                      # Static checks; no Docker required
./stack config                     # Inspect Compose configuration
./stack status
./stack logs --tail 100
./stack down                       # Containers only; preserves data/config
./stack up                         # Restore default SSH-only mode
./stack lock --refresh             # Intentionally update immutable image digest
./stack up                         # Recreate container using new digest
```

If the deployment uses optional networking, replace the final `./stack up` with `./stack up --media`, `./stack up --vpn` or `./stack up --media --vpn` as appropriate. A plain `up` intentionally removes optional exposure and the shared-network attachment on recreation.

Before updating, create a backup with the application stopped briefly for consistency:

```bash
sudo mkdir -p /srv/backups/qbittorrent
sudo chown "$(id -u):$(id -g)" /srv/backups/qbittorrent
./stack backup --output "/srv/backups/qbittorrent/settings-$(date +%Y%m%d-%H%M%S).tar.gz"
```

Backup archives contain **`config/`, `.env`, `images.lock.env` only** — no torrent payload or library. The script refuses to overwrite backups and restarts the container if it was running. Store backups encrypted and off-host; they contain session/application credentials. Back up the configured `DATA_ROOT` separately if you need to restore completed/incomplete downloads. Review tar contents before any manual restore, perform restores only with the container stopped, and preserve PUID/PGID ownership. Restoring appdata from an earlier version may be necessary to roll back an incompatible upstream change; merely switching image digests does not undo data migrations.

For a failed boot, inspect `./stack logs`, verify disk space (`df -h`), `findmnt -T <DATA_ROOT>` if using a separate mounted disk, and ownership (`stat -c '%u:%g %n' ...`). Bind mounts forbid silent creation of missing host paths, but cannot detect a missing filesystem when a regular directory remains at the mount point. Directory preparation never recursively `chown`s data. Do not use `docker compose down -v` or delete host download paths unless data loss is intended.

### Validation

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile stack
./stack check
./stack config                   # Requires Docker Compose and an image lock
```

These local tests validate configuration rules, image-lock behavior, safety guards and Compose declarations. Actual production readiness additionally requires Docker pull/start on your Linux server, temporary-password login, category API setup, a legal test torrent, and optional integration/VPN connectivity tests.

## Repository policy

- Root `README.md` is English; `docs/README.es.md` is a complete Spanish counterpart. Update both together.
- No real `.env`, image lock, saved credentials, downloaded content, trackers or cookies in Git.
- No automated updates or background deletion logic.
- MIT applies to **this deployment configuration and scripts only**; upstream qBittorrent/LinuxServer.io projects retain their own licenses.
