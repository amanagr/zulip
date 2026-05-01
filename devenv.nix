{ pkgs, lib, config, ... }:

let
  cfg = config.zulip;
in

{
  # Per-worktree port offset.  All service ports and the run-dev base
  # port are shifted by this value, so multiple worktrees can run
  # `devenv up` and `tools/run-dev` simultaneously without colliding.
  # The main checkout uses the default 0; tools/devenv-worktree
  # auto-fills a non-zero offset into devenv.local.nix in each new
  # worktree.
  options.zulip.portOffset = lib.mkOption {
    type = lib.types.int;
    default = 0;
    description = "Per-worktree shift added to all service ports.";
  };

  config = {
    packages = with pkgs; [
      pkg-config
      gcc
      gnumake
      gettext
      git
      curl
      moreutils
      crudini
      # Headers for compiled Python extensions in Zulip's deps.
      libffi
      openssl
      zlib
      openldap          # python-ldap
      cyrus_sasl        # python-ldap (SASL)
      libxml2           # lxml
      libxslt           # lxml
      libjpeg           # Pillow
      libpng            # Pillow
      libtiff           # Pillow
      libwebp           # Pillow
      freetype          # Pillow
      pcre2             # uwsgi
      libxcrypt         # uwsgi (crypt.h)
      xmlsec            # python-xmlsec / python3-saml (xmlsec1 binary + headers)
      libtool           # python-xmlsec links -lltdl from libtool
      libpq             # psycopg2 needs libpq.so.5 at runtime
      icu77             # PyICU was built against ICU 77; pin the matching ABI
      vips              # pyvips dlopens libvips.so.42 at runtime
      file              # python-magic needs libmagic at runtime
    ];

    languages.python = {
      enable = true;
      package = pkgs.python312;
      uv.enable = true;
    };

    languages.javascript = {
      enable = true;
      package = pkgs.nodejs_22;
      pnpm.enable = true;
    };

    services.postgres = {
      enable = true;
      package = pkgs.postgresql_17;
      port = 5433 + cfg.portOffset;
      extensions = exts: [ exts.pgroonga ];
      initialDatabases = [ { name = "zulip"; } ];
      # initialScript runs against the `postgres` database after
      # initialDatabases are created.  Switch to the `zulip` DB with
      # \c so that CREATE EXTENSION lands there: Zulip's pgroonga
      # migration assumes the access method exists at migrate time
      # and would otherwise fail with "access method pgroonga does
      # not exist".
      initialScript = ''
        CREATE USER zulip WITH SUPERUSER CREATEDB;
        ALTER DATABASE zulip OWNER TO zulip;
        \c zulip
        CREATE EXTENSION IF NOT EXISTS pgroonga;
      '';
    };

    services.rabbitmq = {
      enable = true;
      port = 5673 + cfg.portOffset;
    };

    services.memcached = {
      enable = true;
      bind = "127.0.0.1";
      port = 11212 + cfg.portOffset;
    };

    services.redis = {
      enable = true;
      port = 6380 + cfg.portOffset;
    };

    # Export host/port env vars in shapes that Zulip's dev_settings.py
    # consumes; PGHOST/PGPORT are already exported by the postgres
    # service module, and UV_PROJECT_ENVIRONMENT (pointing at
    # .devenv/state/venv) by the python module.  BASE_PORT is read by
    # tools/run-dev (and the test runner) to shift the proxy/Django/
    # Tornado/webpack/help-center/tusd ports.
    env = {
      BASE_PORT = toString (9991 + cfg.portOffset);
      RABBITMQ_PORT = toString config.services.rabbitmq.port;
      # devenv's rabbitmq module dynamically allocates the EPMD port
      # starting at 4369; both the rabbitmq server and rabbitmqctl
      # read ERL_EPMD_PORT at runtime, so an mkForce here flows
      # through to both consistently.  Pin it explicitly instead of
      # trusting the dynamic allocation, which would otherwise vary
      # depending on whether 4369 was already taken when rabbitmq
      # came up.
      ERL_EPMD_PORT = lib.mkForce (toString (4371 + cfg.portOffset));
      REDIS_HOST = "127.0.0.1";
      REDIS_PORT = toString config.services.redis.port;
      MEMCACHED_LOCATION = "127.0.0.1:${toString config.services.memcached.port}";
    };

    enterShell = ''
      echo
      echo "Zulip dev environment (devenv) — toolchain + services"
      echo "  Python:    $(python --version 2>&1)"
      echo "  Node:      $(node --version)"
      echo "  pnpm:      $(pnpm --version)"
      echo "  Postgres:  $(postgres --version)"
      echo "  Port offset: ${toString cfg.portOffset}  (base 9991, postgres ${toString config.services.postgres.port})"
      echo
      echo "tools/run-dev starts/stops postgres/rabbitmq/memcached/redis"
      echo "for you; run 'devenv up' yourself only if you want them to outlive"
      echo "a single dev-server invocation."
      echo
      if [ ! -d .devenv/state/venv ]; then
        echo "First run: 'uv sync' to populate the venv, 'pnpm install' for node_modules."
      fi
    '';
  };
}
