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

* Check the **Actions** tab: the `tests` workflow (`ci.yml`) runs on every push.
  Its first run on Linux may need fixes, because development so far has been on
  Windows. The README's test badge shows its state.

## 5. Releases and code signing

A release is a version tag. The `release` workflow (`release.yml`) builds the
Windows installer and the Linux AppImage, tests both, and creates a *draft*
release with the files and their SHA-256 sums.

1. Set the version in `backend/opticore/__init__.py`, `frontend/package.json`,
   `CITATION.cff` and `CHANGELOG.md` (the workflow refuses a tag that does not
   match the engine version).
2. Tag and push:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

3. When the workflow is done, open the draft on the *Releases* page, check it and
   publish it.

**Code signing (SignPath Foundation, free for open source).** Until it is set up,
the Windows files are built unsigned, and Windows shows "Unknown publisher" (the
user chooses *More info → Run anyway*).

1. Apply at <https://signpath.org/apply> once the repository is public. The
   policy page they ask for is `docs/CODE_SIGNING.md`. Their conditions include
   multi-factor authentication on the team's GitHub and SignPath accounts, and an
   open-source licence without commercial dual licensing (ADR-059).
2. After approval, set up in SignPath:
   * a project with the slug `opticore-studio`, with GitHub as its trusted build
     system;
   * a signing policy `release-signing` with manual approval;
   * two artifact configurations (check the syntax against SignPath's
     documentation):

     `program`: the program folder as uploaded by the workflow

     ```xml
     <artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
       <zip-file>
         <pe-file path="OptiCore Studio.exe"><authenticode-sign /></pe-file>
       </zip-file>
     </artifact-configuration>
     ```

     `installer`: the installer

     ```xml
     <artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
       <zip-file>
         <pe-file path="OptiCore-Studio-*-Setup.exe"><authenticode-sign /></pe-file>
       </zip-file>
     </artifact-configuration>
     ```

3. In GitHub (*Settings → Secrets and variables → Actions*), add the variable
   `SIGNPATH_ORGANIZATION_ID` and the secret `SIGNPATH_API_TOKEN` (the API token of
   a SignPath CI user that may submit to the project).
4. The next tag builds signed files. Approve each signing request in SignPath
   while the workflow waits.

## Updating the screenshots

The README images in `docs/img` are screenshots of the running app:

* the hero and the start screen at 1920×1080;
* the laptop view at 1366×800;
* the gallery images cropped to the analysis panes.

Retake them when the interface changes noticeably, in English, from fresh
browser storage, on test servers, never on a working instance.
