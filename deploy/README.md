# Publish the city explorer

Nginx serves the static bundle through `/var/www/city-releases/current/` at
`https://simm.is/city/`. The main website has its own release directory.

1. From the reviewed checkout run `npm ci` and `npm run release`. Obtain the
   runtime data directory from a retained shared release or the publishing workspace.
   `python3 -m scripts.preview_bundle --pinned-data --data /path/to/bundle/data` assembles the
   browser and city data and checks each data file against the reviewed inventory in
   `deploy/weekday-data.sha256.gz`. A mirror containing additional runs also works. The release identifier
   is the SHA-256 of the resulting inventory, `SHA256SUMS`.
2. Serve `dist/city-previews/current` with `npm run preview -- --directory dist/city-previews/current`.
   Check both city selectors, clock playback, the Milaneo and East Hastings
   scenarios, source pages and an older bookmarked URL.
3. `deploy/deploy.sh --dry-run` checks the bundle inventory, stages gzip twins and
   prints the staging size. Check available space on the host against this size.
4. `deploy/deploy.sh` uploads the bundle to a new directory on `simmis@simm.is`.
   Pass the reviewed immutable bundle path as the positional argument when
   deploying after review. The host verifies checksums before switching the current symlink.
   `deploy/deploy.sh --rollback` restores the release active immediately before
   the switch. Activation and rollback share a lock.

The host needs Bash, rsync, GNU coreutils, flock and a deploy-user-owned
`/var/www/city-releases`. For initial setup include `nginx-city.conf` in the
HTTPS server block, validate the configuration and reload Nginx. The location
sends `X-Robots-Tag: noindex`.

To restore data on a second machine, copy the `data/` directory from the
publishing workspace's immutable `dist/city-previews/<bundle-id>/` directory
or a retained server release. Pass the copied directory to `--pinned-data`.
The PR carries the SHA-256 inventory. Access to a release mirror is required
to reproduce the explorer before its first public deployment.

To update the inventory after an intentional data change, build with
`npm run preview:bundle`, review the changes, then run:

```sh
awk 'substr($0, 67, 5) == "data/"' dist/city-previews/current/SHA256SUMS |
  gzip -n > deploy/weekday-data.sha256.gz
```

The runtime inventory contains the run manifests, prepared schedules, scenes,
street traces, scenario results, Stuttgart static export and the data linked
from the scientific pages. Recomputing these products uses the producer datasets
described in DATA.md and the source register. The original Vancouver workbench
and its inputs can be inspected using Git revision `ebaecc1` and its retained
`c05e52956d9ee807c7c61141328e9f7f134526427a4e7399831ceea930865b7d` bundle.
