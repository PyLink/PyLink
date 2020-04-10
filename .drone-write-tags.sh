#!/bin/bash
# Write Docker tags for Drone CI: version-YYMMDD, version, major version, latest

VERSION="$1"

if test -z "$VERSION"; then
    echo "Usage: $0 <version>"
    exit 1
fi

if [[ "$VERSION" == *"alpha"* || "$VERSION" == *"dev"* ]]; then
    # This should never trigger if reference based tagging is enabled
    echo "ERROR: Pushing alpha / dev tags is not supported"
    exit 1
fi

major_version="$(printf '%s' "$VERSION" | cut -d . -f 1)"

# Date based tag
printf '%s' "$VERSION-$(date +%Y%m%d),"
# Program version
printf '%s' "$VERSION,"

if [[ "$VERSION" == *"beta"* ]]; then
    printf '%s' "$major_version-beta,"
    printf '%s' "latest-beta"
else  # Stable or rc build
    printf '%s' "$major_version,"
    printf '%s' "latest"
fi
