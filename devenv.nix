{ pkgs, lib, config, ... }:

{
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
    port = 5433;
    extensions = exts: [ exts.pgroonga ];
    initialDatabases = [ { name = "zulip"; } ];
    initialScript = ''
      CREATE USER zulip WITH SUPERUSER CREATEDB;
      ALTER DATABASE zulip OWNER TO zulip;
    '';
  };

  services.rabbitmq = {
    enable = true;
    port = 5673;
  };

  services.memcached = {
    enable = true;
    bind = "127.0.0.1";
    port = 11212;
  };

  services.redis = {
    enable = true;
    port = 6380;
  };

  # Export host/port env vars in shapes that Zulip's dev_settings.py
  # consumes; PGHOST/PGPORT are already exported by the postgres
  # service module, and UV_PROJECT_ENVIRONMENT (pointing at
  # .devenv/state/venv) by the python module.
  env = {
    RABBITMQ_PORT = toString config.services.rabbitmq.port;
    # devenv runs the per-checkout rabbitmq on EPMD 4371 (its module
    # pins this internally even though it exports 4369 to the shell).
    # Override with mkForce so rabbitmqctl finds the right instance
    # instead of any system rabbitmq running on the default 4369.
    ERL_EPMD_PORT = lib.mkForce "4371";
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
    echo
    echo "State dir:  $DEVENV_STATE"
    echo "Run 'devenv up' (in another terminal) to start postgres/rabbitmq/memcached/redis."
    echo
    if [ ! -d .venv ]; then
      echo "First run: 'uv sync' to populate .venv, 'pnpm install' for node_modules."
    fi
  '';
}
