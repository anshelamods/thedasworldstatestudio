Thedas World State Studio is a program designed to mimic (in appearance) the Dragon Age Keep tapestry, for the purpose of creating Default World States with custom histories for import into Dragon Age Inquisition.

AI Usage:
The code for the program was done by AI. The art is all the original art from the Keep. The original documentation and development were done by me. I understand people may wish to avoid AI content, so my original Custom World States is being left as is; no AI touched that. It was all investigated, documented, and edited by me personally.

## Web app

This repository builds the editor as a static web app served from GitHub Pages.
Nothing needs to be installed: open the site, build a World State and export it as an FBMOD.

The browser version runs the original Python application unchanged, using
[Pyodide](https://pyodide.org) (Python compiled to WebAssembly) in a Web Worker.
It uses the same catalog, story rules, save importers and FBMOD writer as the
Windows release, and exports are byte-for-byte identical.

Differences from the Windows application:

- **Storage.** World States, their saved revisions and FBMOD settings are kept in
  the browser's storage (IndexedDB) for this site. They are not shared with other
  browsers or devices. Clearing site data deletes them, so use
  *Manage World States → Export World State JSON* for backups, and *Import a World
  State* to restore them or move them to another browser.
- **Exports.** *Export as FBMod* downloads the `.fbmod` file through the browser.
  The export report is offered as a separate download. There is no export-folder
  setting, *Open export folder* or *Open World State folder*.
- **Game saves.** *Import Save* reads the chosen `.das` file in the browser. The
  file is never uploaded anywhere.
- **First load** downloads about 15 MB of runtime, which the browser then caches.

Several tabs can stay open at once. Saves from one tab are visible in the others,
and a tab editing an older revision is asked to reopen it, as in the desktop app.

## Repository layout

- `prototype/`, `assets/`, `assessment/`: the upstream 1.0.4 source distribution from
  [anshelamods/thedasworldstatestudio](https://github.com/anshelamods/thedasworldstatestudio/releases)
  (see `prototype/SOURCE-README.md`). The web build changes only the front end in
  `prototype/gui/` (request routing, downloads, relative asset paths) and its UI tests.
- `web/web_backend.py`: routes editor requests to the upstream `EditorApp` in place of
  the local HTTP server in `prototype/gui.py`.
- `web/worker.js`, `web/backend.js`: load Pyodide, persist storage and connect the page
  to the Python backend.
- `tools/build_web.py`: assembles the static site in `_site/`.
- `.github/workflows/pages.yml`: tests, builds and deploys the site.

## Building and testing locally

Requires Python 3.12+ and Node.js 22.

```sh
npm ci            # installs the pinned Pyodide runtime
npm run build     # writes the site to _site/
npm run serve     # serves it at http://localhost:8000/
npm test          # upstream tests, a fresh build and the Pyodide backend test
```

## Deploying

In the repository's *Settings → Pages*, set *Source* to **GitHub Actions**. Each push
to `main` then tests, builds and publishes the site. Pull requests run the same tests
and build without deploying.

## Attribution

See `SOURCE-NOTICES.txt`. Unofficial fan project, not affiliated with or endorsed by
EA or BioWare. Dragon Age artwork, interface assets and fonts belong to their
respective owners.
