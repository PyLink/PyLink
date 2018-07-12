# Release Process for PyLink

This document documents the steps that I (James) use to release updates to PyLink.

1) Draft the next release's changelog in `RELNOTES.md`

2) Bump the version in the [`VERSION`](VERSION) file.

3) Commit the changes to `VERSION` and `RELNOTES.md`, and tag+sign this commit as the new release. Do not prefix version numbers with "v".

4) Publish the release via the GitHub release page, using the same changelog content as `RELNOTES.md`.

5) For stable releases, ~~also upload to PyPI: `python3 setup.py sdist upload`~~ PyPI uploads are handled automatically via Travis-CI.
