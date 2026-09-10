# Deployment

The dashboard is served by **Cloudflare Pages** from the committed `_site/` directory.

## Why the build is committed

`_site/` is a build artefact, and normally that would be git-ignored. It is committed
here on purpose, for two reasons.

Cloudflare Pages then needs **no build step and no secrets**: it serves the directory
as it finds it. And the scheduled collector and prediction jobs already commit new data
to this repository, so rebuilding `_site/` in the same commit means the deployed site
follows the data automatically, with no second pipeline to keep in sync.

## Cloudflare Pages settings

| Setting | Value |
|---|---|
| Framework preset | None |
| Build command | *(leave empty)* |
| Build output directory | `_site` |
| Production branch | `main` |

`wrangler.toml` records the output directory so a Wrangler-driven deploy agrees with
the dashboard setting.

## Caching

`app/_headers` ships with the site. Live data is served with a 60-second
`must-revalidate` window so a visitor never sees a stale estimate cached for hours,
while the SVG assets are allowed a day.

## Rebuilding locally

```bash
python app/build_site.py _site
```

That copies the app and the current data into `_site/`. The collector and prediction
workflows run the same command before committing, so what is deployed is always what
the pipeline produced.

## What is not used

GitHub Pages was removed. There is no `pages.yml` workflow, and nothing in the
repository depends on `github.io`.
