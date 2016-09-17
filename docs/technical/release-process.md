# Release Process for PyLink

This document documents the steps that I (James) use to release updates to PyLink.

1) Draft the next release & changelog at https://github.com/GLolol/PyLink/releases

2) Copy/export the changelog draft to [RELNOTES.md](../../RELNOTES.md), using a new section.

- [`export_github_relnotes.py`](https://github.com/GLolol/codescraps/blob/master/utils/export_github_relnotes.py) allows automating this process, using the GitHub API and an optional login to read unpublished drafts.

3) Bump the version in the [`VERSION`](VERSION) file.

4) Commit the changes to `VERSION` and `RELNOTES.md`, and tag+sign this commit as the new release. Do not prefix version numbers with "v".

5) Publish the release via the GitHub release page.

6) For stable releases, also upload to PyPI: `python3 setup.py sdist upload`
