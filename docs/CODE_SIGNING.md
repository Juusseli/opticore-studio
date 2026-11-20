# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by
[SignPath Foundation](https://signpath.org/).

## What is signed

The Windows program (`OptiCore Studio.exe`) and its installer
(`OptiCore-Studio-<version>-Setup.exe`), built from this repository by the
`release` workflow (`.github/workflows/release.yml`) on GitHub-hosted runners.
Nothing built elsewhere is signed. The libraries bundled with the program (the
Python runtime, NumPy, SciPy, Open CASCADE and others, listed in the package's
`licenses` folder) are their authors' files and are not signed by this project.

Each release's files and their SHA-256 sums are published on the
[releases page](https://github.com/Juusseli/opticore-studio/releases).

## Team roles

| Role | Members |
|---|---|
| Authors (commit to the repository) | [Juuso Heiskanen](https://github.com/Juusseli) |
| Reviewers (review contributions before they are merged) | [Juuso Heiskanen](https://github.com/Juusseli) |
| Approvers (approve each signing request) | [Juuso Heiskanen](https://github.com/Juusseli) |

Contributions from outside the team, including automated dependency updates, are
merged only through pull requests that a reviewer has checked. Every signing
request is approved by an approver. The team's GitHub and SignPath accounts use
multi-factor authentication.

## Licence

OptiCore Studio is licensed under AGPL-3.0-or-later only, an OSI-approved open
source licence, and is not offered under any other licence. Contributions are
accepted under the same licence ([CONTRIBUTING.md](../CONTRIBUTING.md)).

## Privacy policy

This program will not transfer any information to other networked systems
unless specifically requested by the user or the person installing or operating
it.

The program runs its engine on the local computer and shows its user interface
in a local browser window. Projects are stored in that browser on the same
computer. The only network access is the optional installation of a glass
catalogue, which the user starts. It downloads public data from the
refractiveindex.info database on GitHub and sends no project data.
