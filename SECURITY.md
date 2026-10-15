# Security policy

## Important scope

SELF is an experimental, local-first agent runtime. It intentionally runs as
root inside its Docker container and can execute generated shell/Python code
inside that container. Docker is the documented security boundary; this
project is not a hardened sandbox and should not be given host mounts,
production credentials, or network access that you are unwilling to expose to
code running in the container.

The harness logs and redacts known credentials, but arbitrary shell commands
and generated code can make network requests outside the harness HTTP logger.
Treat the runtime as untrusted when evaluating a deployment.

## Reporting a vulnerability

Please do not disclose vulnerabilities in a public issue. Report them through
GitHub's private security reporting features for this repository, if enabled.
If private reporting is unavailable, contact the maintainer through the
[GitHub profile](https://github.com/FatinShadab) and include `SELF security`
in the subject.

Please include:

- a short description and security impact;
- affected commit, release, or configuration;
- reproducible steps or a minimal proof of concept; and
- any suggested mitigation, if known.

Avoid including real secrets or personal data. We will acknowledge reports as
soon as practical, investigate, and coordinate disclosure of a fix when
appropriate. Please allow maintainers reasonable time to respond before public
disclosure.

## Supported versions

Only the latest `main` branch is currently supported. There are no published
release versions yet.
