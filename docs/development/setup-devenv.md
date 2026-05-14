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

Enable flakes (devenv requires them). The `grep -qxF` guards keep the
lines from being duplicated if you re-run these commands later:

```bash
sudo install -d /etc/nix
grep -qxF 'experimental-features = nix-command flakes' /etc/nix/nix.conf 2>/dev/null \
    || echo 'experimental-features = nix-command flakes' | sudo tee -a /etc/nix/nix.conf
grep -qxF 'trusted-users = root @wheel' /etc/nix/nix.conf 2>/dev/null \
    || echo 'trusted-users = root @wheel' | sudo tee -a /etc/nix/nix.conf
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

PostgreSQL, RabbitMQ, Memcached, and Redis run as plain user processes
managed by devenv. Their state lives under `.devenv/state/` in this
checkout, so each clone of the repo gets its own services on its own
ports, and they coexist with any system-installed copies that may be
running on the default ports.

`tools/run-dev` starts these services automatically when you launch it
inside `devenv shell` (and stops them on exit), so you don't need a
second terminal running `devenv up`. If you'd rather manage them
yourself — for example, to keep them up between dev-server restarts —
run `devenv up` in a second terminal; `tools/run-dev` will detect that
they're already up and leave them alone.

Initialize the database. The devenv PostgreSQL is in the read-only Nix
store, so the regular `tools/setup/postgresql-init-dev-db` flow that
installs hunspell dictionaries into `share/tsearch_data/` doesn't apply;
the in-tree settings detect devenv and fall back to plain English
stemming for full-text search. With services up (either via `tools/run-dev`
having been started once, or `devenv up` in another terminal), run:

```bash
scripts/setup/configure-rabbitmq    # set up the RabbitMQ user/vhost
./manage.py migrate
./manage.py createcachetable third_party_api_results
./manage.py populate_db --threads=1
```

Then start the dev server as usual:

```bash
./tools/run-dev
```

If something crashes hard (SIGKILL, machine power-off) the service
processes can survive — `tools/run-dev`'s atexit cleanup only fires on
clean exit. To find and stop leaked services:

```bash
pgrep -fa 'process-compose'  # show any orphaned supervisors
devenv processes down        # stop services for this checkout
```

## Working in multiple worktrees

The devenv setup lives entirely on a long-lived local `devenv` branch
in your checkout. It is meant to stay local — nothing here is intended
to land upstream. To do feature work without polluting your PRs with
the devenv commits:

1. Create each feature worktree based off `devenv`:

   ```bash
   tools/devenv-worktree fix-foo
   ```

   That puts a worktree at `$HOME/zulip-fix-foo` on a new branch
   `fix-foo`, branched off `devenv`. The script also runs the
   one-time provisioning inside the worktree's devenv shell (uv
   sync, pnpm install, devenv up, configure-rabbitmq, migrate,
   createcachetable, populate_db) so `./tools/run-dev` works
   immediately on first invocation. Expect ~3-5 minutes for the
   first worktree; subsequent ones are similar (each worktree
   keeps its own `.devenv/state/venv` and `node_modules`, so the
   Python and Node-side installs run per-worktree by design).

   Pass `--no-provision` to skip the auto-provision step (e.g.,
   when scripting many worktrees or restoring from a backup); the
   script will print the manual commands instead.

   The script writes a `devenv.local.nix` in the new worktree with a
   per-worktree port offset — the lowest free 100-port slot — so
   several worktrees can run `devenv up` and `tools/run-dev` in
   parallel without colliding on PostgreSQL, RabbitMQ, memcached,
   Redis, or run-dev's proxy/Django/Tornado/webpack/help-center/tusd
   ports. The main checkout always uses offset 0.

   To put your worktrees somewhere other than `$HOME`, set
   `ZULIP_WORKTREE_DIR` in your shell profile (e.g.
   `export ZULIP_WORKTREE_DIR=$HOME/src`). Both
   `tools/devenv-worktree` and `tools/devenv-worktree-remove`
   honor it.

2. Develop and commit normally.

3. When ready to push, run `tools/devenv-publish` from the worktree:

   ```bash
   tools/devenv-publish        # pushes to origin
   ```

   It rebases the branch off the devenv commits onto
   `upstream/main`, force-with-lease pushes the clean public view,
   and then re-applies `devenv` as the local base so the worktree
   keeps working for the next round of edits. Origin only ever sees
   the rebased clean view; your local branch always has the devenv
   files.

4. When you're done with a worktree, remove it:

   ```bash
   tools/devenv-worktree-remove fix-foo        # remove the directory
   tools/devenv-worktree-remove -b fix-foo     # also delete the branch
   tools/devenv-worktree-remove -f fix-foo     # discard uncommitted changes
   ```

To pick up upstream changes into the devenv branch itself:

```bash
# From the main checkout (~/zulip):
git fetch upstream
git checkout devenv
git rebase upstream/main
```

Worktrees keep their old devenv base until you rebase them
explicitly (`git rebase devenv` from inside the worktree).

## Limitations

- Auxiliary services (thumbor, smokescreen, camo, nginx) are not wired
  up.
- Full-text search uses plain English stemming rather than the hunspell
  dictionary set; this is sufficient for development but won't catch
  tsearch dictionary regressions.
- This is meant for personal experimentation. Don't rely on it for
  reproducing CI failures; CI uses `tools/provision` on Ubuntu.
