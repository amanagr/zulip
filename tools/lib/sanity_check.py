import os
import pwd
import sys

from scripts.lib.zulip_tools import is_zulip_production_install


def check_venv(filename: str) -> None:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # When this checkout is devenv-configured but we aren't in devenv
    # shell, re-exec into devenv shell BEFORE the venv check below.
    # Otherwise a foreign VIRTUAL_ENV leaking in from another shell
    # (e.g. the main checkout's venv inheriting into a worktree's
    # terminal) would let the venv check pass via UV_PROJECT_ENVIRONMENT
    # / VIRTUAL_ENV and leave the entry point silently outside the
    # per-checkout services.  devenv_supervisor is stdlib-only, so
    # importing it before the venv is active is safe.
    if os.path.exists(os.path.join(BASE_DIR, "devenv.local.nix")) and not os.environ.get(
        "DEVENV_ROOT"
    ):
        cwd = os.getcwd()
        try:
            os.chdir(BASE_DIR)
            from tools.lib import devenv_supervisor

            devenv_supervisor.reexec_under_devenv_shell_if_needed()
        finally:
            # The reexec replaces the process when it fires; we only
            # reach this restore on a no-op path (e.g. devenv binary
            # missing, which the supervisor surfaces and exits on).
            os.chdir(cwd)

    # Mirror scripts/lib/setup_path.py: honor venv-override env vars; skip on production.
    if is_zulip_production_install():
        venv_override = None
    else:
        venv_override = os.environ.get("UV_PROJECT_ENVIRONMENT") or os.environ.get("VIRTUAL_ENV")
    venv = os.path.realpath(os.path.join(BASE_DIR, venv_override or ".venv"))
    if sys.prefix == venv:
        return
    # Activate the resolved venv in-process (mirrors setup_path.py).
    activate_this = os.path.join(venv, "bin", "activate_this.py")
    if os.path.exists(activate_this):
        with open(activate_this) as f:
            exec(f.read(), {"__file__": activate_this})  # noqa: S102
        return

    print(f"You need to run {filename} inside a Zulip dev environment.")
    user_id = os.getuid()
    user_name = pwd.getpwuid(user_id).pw_name

    print(f"You can `source {venv}/bin/activate` to enter the development environment.")

    if user_name not in ("vagrant", "zulipdev"):
        print()
        print("If you are using Vagrant, first run `vagrant ssh` to enter the Vagrant guest.")
    sys.exit(1)
