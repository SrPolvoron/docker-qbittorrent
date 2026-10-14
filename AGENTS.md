# AGENTS.md — Docker qBittorrent (SrPolvoron)

## Purpose and boundaries

Maintain a small, secure, reproducible **new** LinuxServer.io qBittorrent deployment. It is not a migration or replacement of any existing Jellyfin qBittorrent container. Do not edit another repository, add an indexer, reverse proxy, user-facing torrent catalog, VPN egress gateway or email service without explicit approval.

## Architecture invariants

- Default host Web UI publication is **127.0.0.1 only**. Optional `compose.wireguard.yaml` adds a host binding to an IP actively assigned to a verified host WireGuard interface. Never bind to `0.0.0.0` by default.
- Web UI port matches the container's `WEBUI_PORT` (LinuxServer upstream requirement). Default 8081 avoids an existing 8080 instance. No inbound BitTorrent port is published by default; SSH/WireGuard access applies to the UI, not torrent egress.
- One independently persisted instance; `CONFIG_ROOT` is never shared with another running qBittorrent. Data is under `DATA_ROOT/torrents/standalone`, mapped to `/data/torrents/standalone`, with categories movies/tv/books/games/software/other and incomplete.
- Optional shared network exists outside this Compose project's lifecycle, and the unambiguous alias is `qbittorrent-standalone`. Existing Radarr/Sonarr systems must opt in and keep their original networks and clients.
- Prefer same-host-path `/data` mounts for hardlink-capable Radarr/Sonarr import; don't silently introduce Remote Path Mappings or move data.
- `./stack` parses literal .env without shell execution, refuses unsafe/symlink paths and changes only directories this new application owns. Never recursively chown existing datasets.
- Image is resolved to an immutable digest with `./stack lock`. No auto-updaters, no auto-deletion, no public trackers/credentials in Git.
- Application credentials are configured through qBittorrent's own Web UI. `./stack categories` prompts via getpass and uses only the loopback Web API; never print/store its password.
- Configuration backup omits torrent payloads. Appdata upgrades are not assumed reversible; advise backup/restore for rollback.

## Key files and commands

- `compose.yaml`: base service and localhost UI.
- `compose.media.yaml`: external Docker network only.
- `compose.wireguard.yaml`: optional WireGuard host UI binding.
- `.env.example`: complete literal configuration contract, no secrets.
- `stack`: standard-library-only operator CLI (Python 3.10+).
- `tests/`: standard-library unittest suite, no network/daemon needed.
- `README.md`, `docs/README.es.md`: documentation pair; keep commands, configuration, security and troubleshooting synchronized.

Run `python3 -m unittest discover -s tests -v`, `python3 -m py_compile stack`, and `./stack check` after editing. If Docker Compose is available, run `./stack config` for each overlay combination (base, `--media`, `--vpn`, both) on a suitable test host with a valid WireGuard interface. Report what could not be tested.

## Workflow and release discipline

- Favor small backward-compatible changes; explicitly document changes to host mounts, categories, ports, aliases and persistent configuration.
- Never commit `.env`, `images.lock.env`, credentials, logins, payloads, or backups. Do not add auto-updating digests.
- `README.md` remains English with near-top `[Leer en español](docs/README.es.md)`. `docs/README.es.md` remains fully translated with near-top `[Read in English](../README.md)`. Maintain reciprocal links and technical parity in the same change. `AGENTS.md` is English.
- No automatic version bumps, release tags, publishing or CI workflow changes unless requested.
- Separate local static-validation success from actual Docker host deployment/testing.
