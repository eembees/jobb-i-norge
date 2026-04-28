# norjobs

Static explorer for Norwegian occupations, built from SSB data and published as a single-page site.

## Local

```bash
python fetch.py
python process.py
python build_site_data.py
cd site && python3 -m http.server 4173
```

Open `http://localhost:4173`.

## GitHub Pages

This repo includes a workflow at [.github/workflows/deploy-pages.yml](.github/workflows/deploy-pages.yml).

On every push to `main`, GitHub Actions will:

1. Fetch fresh SSB raw data
2. Rebuild `data/occupations.csv`
3. Rebuild `site/data.json`
4. Publish the `site/` directory to GitHub Pages

Default Pages URL:

`https://eembees.github.io/norjobs/`

## mags.nu/norjobs

This site is safe to host behind a subpath because it uses relative asset and data URLs.

Now that the repository name is `norjobs`, the standard project-site path becomes:

`https://eembees.github.io/norjobs/`

If `mags.nu` is already configured as the custom domain for the `eembees.github.io` Pages site, this project will resolve naturally at:

`https://mags.nu/norjobs/`
