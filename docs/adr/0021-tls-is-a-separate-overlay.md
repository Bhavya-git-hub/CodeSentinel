# 0021. TLS terminates in a separate overlay, and the proxy does not hold the API key

**Status:** accepted — 2026-09-11

## Context

`docs/DEPLOYMENT.md` said "No TLS. Terminate it at a reverse proxy in front of the API and
frontend. Nothing here does." Two things had to be decided to stop saying that.

**Where it lives.** The natural place is `docker-compose.prod.yml`, so that deploying
production means deploying TLS. But a certificate requires a hostname that resolves to
the machine, and that is true of a deployment and false of every CI runner and every
laptop. Putting it in the production overlay would make the file that CI validates — the
file the deployment guide tells people to use — unvalidatable, and would turn "we
terminate TLS at our existing ingress" from a supported topology into a file to edit.

**Whether the proxy supplies the API key.** The deployment guide already recommends this:
"put a gateway in front of the API that adds `X-API-Key` server-side, leave both unset,
and the browser never holds a credential at all. That is the only topology where the key
stays a secret." Having written a reverse proxy config, the obvious move is to do exactly
that — it is three lines, and it retires the whole awkward business of a key in
`localStorage`.

It is also the change that quietly converts an authenticated API into an open one.

## Decision

**A third overlay**, `docker-compose.tls.yml`, applied on top of the production one. It
adds Caddy, which obtains and renews certificates over ACME, and it uses `!override` to
unpublish the API's and the frontend's own ports so the only way in is through the proxy.
That unpublishing is the part that matters: without it a firewall gap leaves the
plaintext API listening beside the encrypted one, and nothing in the application can tell
that a caller took the unencrypted route. CI asserts the override actually removes those
ports rather than appending to them, the same check the production overlay gets for
PostgreSQL.

**The proxy does not add `X-API-Key`.** The directive is in the Caddyfile, commented,
immediately beneath the reason: injecting the key makes *reaching the proxy* the entirety
of authentication, and this file has no opinion about who may reach it. It is the right
topology only once something else decides that — a VPN, mTLS, or an SSO `forward_auth` in
front of the block. Shipping it on by default would mean every deployment that took the
TLS overlay silently lost its authentication, and the diff that did it would look like a
simplification.

**One origin.** `/api/*` and `/health*` proxy to the API; everything else is the SPA. Same
origin means no preflight and no cross-origin credential, which removes the failure mode
ADR 0016 ends on — a wildcard CORS origin plus a browser-held key being a credential any
site can borrow. The overlay sets `CODESENTINEL_CORS_ORIGINS` to the exact scheme and host
anyway, because the value still has to be right for anything reaching the API directly.

**`/metrics` is not proxied**, and the Caddyfile says so at the point where someone would
add it. It is unauthenticated when enabled (ADR 0018), so publishing it here would put
this instance's scan volumes on the open internet.

The frontend's own nginx grew a matching `/api/` proxy, so the non-TLS stack is
same-origin too. Before that, a relative `/api/v1/...` request in the compose stack landed
on the SPA fallback and came back as `index.html` with a 200 — surfacing as a JSON parse
error rather than as "the API is not reachable", which is the least informative possible
symptom of an ordinary misconfiguration. The upstream is held in a variable so nginx
resolves it per request: with a literal `proxy_pass http://api:8000`, nginx refuses to
start when that name does not resolve, so running the image alone would fail as a
container that will not boot rather than as a 502 on one request.

## Consequences

- Three files on the deploy command line. The guide gives the full invocation; anyone
  terminating TLS elsewhere omits the third and is in a supported configuration rather
  than a patched one.
- HSTS is set to two years. It is remembered by browsers and is awkward to take back, so
  the Caddyfile says to remove the line while testing.
- The CSP is tight because this app loads no third-party script and makes no cross-origin
  request. Adding a web font or an analytics script will break it, which is the intended
  behaviour — widen it deliberately.
- Certificates live in a named volume. Losing it is survivable, since Caddy re-issues, but
  it is how a restart loop reaches Let's Encrypt's rate limit.
- **This still has not been run.** CI validates and builds; no `docker compose up` has
  executed anywhere in this project, and ACME issuance in particular cannot be exercised
  without a real hostname. See ADR 0005.
