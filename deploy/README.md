# Deploying XXVI

Two honestly-different paths, depending on what else is running on the box.

## Simple case: this is the only thing on the box

If nothing else needs port 80 or 443, you don't need anything in this
directory. Use the plain `docker-compose.yml` and `Caddyfile` at the repo
root — that Caddy binds 80/443 itself and gets its own Let's Encrypt
certificate automatically from `SITE_DOMAIN` in `.env`. See
`docs/runbook.md` for the full sequence. In short:

```bash
docker compose up -d --build
```

DNS for `SITE_DOMAIN` needs to already point at this host's public IP
**before** you bring the stack up — see the DNS note below, which applies
here too.

## Shared case: something else already owns 80/443

This is what `deploy/` is for. The box already runs a front proxy (its own
Caddy, nginx, Traefik, whatever) fronting other people's sites, so XXVI's
`web` container publishes no ports at all and instead joins that proxy's
docker network, reachable only from inside it. `docker-compose.prod.yml`
and `Caddyfile.prod` carry the reasoning for that arrangement inline — read
the comments at the top of each before changing them.

Steps:

1. **Create the DNS record first.** Point your real domain at this host's
   public IP *before* touching the site block below. This is the single
   most expensive mistake from the original deployment: adding the site
   block before DNS existed made the front proxy's ACME client fail with
   `no valid A records found` — and once it fails, it can get stuck
   retrying the same broken attempt rather than cleanly trying again once
   DNS is actually live. If that happens, restart the front proxy's own
   container after DNS resolves, rather than waiting for it to notice on
   its own.

2. **Find or create the front proxy's docker network**, and export its
   name so compose can join it:

   ```bash
   docker network ls   # look for the network the front proxy is on
   export FRONT_PROXY_NETWORK=that_network_name
   ```

   If the front proxy isn't on any dedicated network yet, create one and
   connect the front proxy's container to it:

   ```bash
   docker network create front_proxy
   docker network connect front_proxy <front-proxy-container-name>
   export FRONT_PROXY_NETWORK=front_proxy
   ```

3. **Add a site block** to the front proxy's own config, pointing at this
   stack's `web` container by its compose service name (`web`) on port 80
   — not at a host port, since none is published. For a Caddy front proxy
   that's a stanza like:

   ```
   your.real.domain {
       reverse_proxy web:80
   }
   ```

   (Substitute the equivalent for nginx/Traefik/whatever actually owns the
   box.)

4. **Bring the stack up:**

   ```bash
   docker compose -f deploy/docker-compose.prod.yml up -d --build
   ```

5. **Run migrations once**, against the real database, before relying on
   the API:

   ```bash
   docker compose -f deploy/docker-compose.prod.yml run --rm api alembic upgrade head
   ```

## `.env` changes and `--force-recreate`

A plain `docker compose up -d --build` will **not** pick up a changed
`.env` value if the underlying image is unchanged — compose sees the image
hasn't changed and leaves the running container alone, `.env` mount and
all, stale. `.env` is bind-mounted read-only rather than loaded via
`env_file` (see the comment on the `api` service), so a compose-level "env
changed, recreate" check never fires for it either way. If you've only
edited `.env` — a rotated secret, a new reward code, a checkpoint hash —
force it:

```bash
docker compose -f deploy/docker-compose.prod.yml up -d --force-recreate
```

`--build` is harmless to add back in but won't be what makes the new
`.env` take effect; `--force-recreate` is.
