# Publishing on GitHub

A checklist for creating the public repository and the settings that the files in
this repository cannot set themselves.

## 1. Create the repository and push

Publish the `main` branch: it holds the released state as a single commit. Push
no other branch.

With the [GitHub CLI](https://cli.github.com/) signed in (`gh auth login`), on
`main`:

```bash
gh repo create opticore-studio --public --source . --remote origin --description "Optical design and simulation in the browser: lens design, analysis, optimisation, tolerancing, thin films, illumination and wave optics on a validated Python engine"
git push -u origin main
```

## 2. Repository settings (github.com → Settings)

* **General → Social preview:** upload `docs/img/social-preview.png` (1280×640).
* **General → Features:** turn on *Discussions* for questions and ideas, and keep
  *Issues* on.
* **Security → Private vulnerability reporting:** enable it. `SECURITY.md`
  refers to it.
* **Branches:** protect `main` and require the `tests` workflow to pass before
  merging.

## 3. About box (the gear icon next to *About* on the front page)

* **Topics:** `optics`, `optical-design`, `lens-design`, `ray-tracing`,
  `optical-simulation`, `thin-films`, `photonics`, `physics-simulation`, `react`,
  `fastapi`, `python`, `typescript`.
* Untick *Releases* and *Packages* unless they are used.

## 4. After the first push

* Check the **Actions** tab. The first run of `.github/workflows/ci.yml` on Linux
  may need fixes, because development so far has been on Windows.
* Add the CI badge at the top of `README.md`, next to the other badges:

  ```html
  <a href="https://github.com/OWNER/opticore-studio/actions/workflows/ci.yml"><img src="https://github.com/OWNER/opticore-studio/actions/workflows/ci.yml/badge.svg" alt="tests"></a>
  ```

* Add `repository-code: https://github.com/OWNER/opticore-studio` to
  `CITATION.cff`.
* Create the first release, for example `v0.1.0`, from the *Releases* page, with
  notes from `CHANGELOG.md`.

## Updating the screenshots

The README images in `docs/img` are screenshots of the running app:

* the hero and the start screen at 1920×1080;
* the laptop view at 1366×800;
* the gallery images cropped to the analysis panes.

Retake them when the interface changes noticeably, in English, from fresh
browser storage, on test servers, never on a working instance.
