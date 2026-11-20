# Security policy

## Supported versions

Security fixes go into the latest version on the default branch.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately
through GitHub: open the repository's **Security** tab and choose **Report a
vulnerability**. Include the steps to reproduce it, the affected version or commit,
and its impact. You will get an answer as soon as possible, and the fix will be
credited to you unless you prefer otherwise.

## Deployment model

OptiCore Studio is designed to run on your own computer:

* The engine listens on `127.0.0.1` and has no authentication or rate limiting.
* Some analyses and optimisations use every processor core for minutes.
* Projects are stored in your browser and are never sent to a server other than
  your local engine.

Do not expose the engine to a network you do not trust. If you host it for other
people, put it behind authentication and limits on request time and concurrency.
Remember that the AGPL requires you to offer the source of a modified version that
you run as a network service.
