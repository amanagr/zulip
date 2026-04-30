# Experimental: development setup with Nix and devenv

This is an experimental alternative to `tools/provision` for setting up a
Zulip development environment. It uses [Nix][] and [devenv][] to provide
a reproducible toolchain (Python, Node.js, PostgreSQL, RabbitMQ, Memcached,
Redis) without relying on the host distribution's package manager, and
without using a virtual machine or container.

[Nix]: https://nixos.org/
[devenv]: https://devenv.sh/

This setup is currently a prototype. It is not a replacement for
`tools/provision`; if your distribution is supported by `tools/provision`,
that path is more battle-tested.

## Status

- Linux only. macOS may work but has not been tested.
- The Python venv is still managed by `uv` inside the devenv shell, not
  by Nix. Node modules are still managed by `pnpm`.
- Auxiliary services (thumbor, smokescreen, camo, nginx) are not yet
  wired up. The dev server's basic flow works.

## Prerequisites

Install Nix. On Fedora 44+, the distribution package works:

```bash
sudo dnf install nix nix-daemon
sudo systemctl enable --now nix-daemon.service
```

Enable flakes (devenv requires them):

```bash
sudo install -d /etc/nix
echo 'experimental-features = nix-command flakes' | sudo tee -a /etc/nix/nix.conf
echo 'trusted-users = root @wheel' | sudo tee -a /etc/nix/nix.conf
sudo systemctl restart nix-daemon.service
```

If you're on a confined-SELinux distribution like Fedora and the daemon
fails to start with a permission error on `/nix/var/nix/daemon-socket`,
relabel `/nix` so confined contexts can read it:

```bash
sudo semanage fcontext -a -t usr_t '/nix(/.*)?'
sudo restorecon -RvF /nix
```

Install the devenv CLI into your Nix profile:

```bash
nix profile add nixpkgs#devenv
```

## First-run setup

From the Zulip checkout, enter the devenv shell. The first invocation
downloads/builds the toolchain and can take a while:

```bash
devenv shell
```

Inside the shell, populate the language-level dependencies:

```bash
uv sync         # populates .devenv/state/venv with Python deps
pnpm install    # populates node_modules
```

In a second terminal (also inside `devenv shell`), start the services:

```bash
devenv up
```

This brings up PostgreSQL, RabbitMQ, Memcached, and Redis as plain user
processes. Their state lives under `.devenv/state/` in this checkout, so
each clone of the repo gets its own services on its own ports, and they
coexist with any system-installed copies that may be running on the
default ports. `Ctrl-C` in that terminal stops them.

Initialize the database. The devenv PostgreSQL is in the read-only Nix
store, so the regular `tools/setup/postgresql-init-dev-db` flow that
installs hunspell dictionaries into `share/tsearch_data/` doesn't apply;
the in-tree settings detect devenv and fall back to plain English
stemming for full-text search. Run migrations and populate:

```bash
./manage.py migrate
./tools/setup/generate-fixtures --force
./manage.py populate_db --threads=1
```

Then start the dev server as usual:

```bash
./tools/run-dev
```

## Limitations

- Auxiliary services (thumbor, smokescreen, camo, nginx) are not wired
  up.
- Full-text search uses plain English stemming rather than the hunspell
  dictionary set; this is sufficient for development but won't catch
  tsearch dictionary regressions.
- This is meant for personal experimentation. Don't rely on it for
  reproducing CI failures; CI uses `tools/provision` on Ubuntu.
