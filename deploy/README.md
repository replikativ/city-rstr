# Deploying the explorer

The explorer is published as static files under `https://simm.is/city/`,
released separately from the website.

1. Export: `(city.demo.stuttgart/export-static! :dir "dist/lab")` in a process
   that has run the pipeline (`clojure -M:demo export` does both).
2. Check locally: `deploy/deploy.sh --dry-run`, then serve the staged folder.
3. Deploy: `deploy/deploy.sh`. It uploads a new release, verifies every file
   by SHA-256 on the host and only then switches `current`.
4. Roll back: `deploy/deploy.sh --rollback`.

One-time server setup: create `/var/www/city-releases` owned by the deploy
user, add `nginx-city.conf` to the HTTPS `simm.is` server block, keep the
previous configuration, run `sudo nginx -t` and reload.

The page and the `X-Robots-Tag` header say `noindex` until the project is
announced; remove both then.
