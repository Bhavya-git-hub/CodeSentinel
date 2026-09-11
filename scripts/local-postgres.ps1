# Start, stop or inspect a local PostgreSQL for the requires_db tests.
#
# Why this exists: the tests marked `requires_db` skip when no PostgreSQL is reachable,
# and a skipped test is an unverified one. On a machine with no Docker there was no
# documented way to get one, so 48 tests -- including every foreign-key cascade the
# retention pruner depends on -- could only ever be verified in CI.
#
# This is a DEVELOPMENT convenience and nothing else. It is not how the database is run
# anywhere real: production uses the postgres:15 service in docker-compose.yml. The
# version here matches that deliberately, because a cascade or an index behaving
# differently between the two would defeat the point of running the tests at all.
#
# The cluster is a plain user-owned directory under %LOCALAPPDATA%\CodeSentinel. There is
# no Windows service and no admin right involved, which also means it does not restart by
# itself after a reboot -- run `-Action start` again.
#
#   powershell -File scripts/local-postgres.ps1 -Action start
#   powershell -File scripts/local-postgres.ps1 -Action status
#   powershell -File scripts/local-postgres.ps1 -Action stop
#
# To remove it entirely, stop it and delete %LOCALAPPDATA%\CodeSentinel.

param(
    [ValidateSet("start", "stop", "status", "psql")]
    [string]$Action = "status",
    [int]$Port = 5432
)

$ErrorActionPreference = "Stop"

$root = Join-Path $env:LOCALAPPDATA "CodeSentinel"
$bin = Join-Path $root "pgsql\bin"
$data = Join-Path $root "pgdata"
$log = Join-Path $root "postgres.log"

if (-not (Test-Path $bin)) {
    Write-Error @"
No local PostgreSQL found at $root.

Install it without admin rights by extracting the official binaries:

  curl.exe -L -o "$root\pgsql-15.zip" ``
    https://get.enterprisedb.com/postgresql/postgresql-15.13-1-windows-x64-binaries.zip
  Expand-Archive "$root\pgsql-15.zip" -DestinationPath "$root"
  & "$bin\initdb.exe" -D "$data" -U postgres --pwfile=<file> -A scram-sha-256 -E UTF8 --locale=C

Then create the role and databases that .env.example assumes:
  codesentinel / codesentinel, owning `codesentinel` and `codesentinel_test`.
"@
}

switch ($Action) {
    "start" {
        # listen_addresses is pinned to loopback. This cluster has a password published in
        # the repository, so it must not be reachable from the network.
        & "$bin\pg_ctl.exe" -D $data -l $log -o "-p $Port -c listen_addresses=127.0.0.1" start
        & "$bin\pg_isready.exe" -h 127.0.0.1 -p $Port
    }
    "stop" {
        & "$bin\pg_ctl.exe" -D $data -m fast stop
    }
    "status" {
        & "$bin\pg_ctl.exe" -D $data status
        & "$bin\pg_isready.exe" -h 127.0.0.1 -p $Port
    }
    "psql" {
        $env:PGPASSWORD = "codesentinel"
        & "$bin\psql.exe" -U codesentinel -h 127.0.0.1 -p $Port -d codesentinel
    }
}
