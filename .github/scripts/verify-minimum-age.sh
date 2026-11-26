#!/usr/bin/env bash
# Verify that every dependency version this pull request introduces was
# published at least MIN_AGE_DAYS ago. Posts a "Verify Minimum Age" commit
# status on the target commit, and when everything clears the cooldown, adds a
# ready-to-merge label and notifies the team.
#
# Renovate's minimumReleaseAge ages only the dependency it updates. This covers
# what it cannot see: SHA-pinned GitHub Actions against moving tags (Renovate
# discussion #39781), and every version a resolver writes into a lockfile
# beyond the declared one — the transitive dependencies.
#
#   GitHub Actions  SHA pins under .github/workflows and .github/actions
#   RubyGems        Gemfile.lock, GEM section only (PATH and GIT have no release)
#   npm             yarn.lock, Yarn Classic and Berry, registry entries only
#   pub.dev         pubspec.lock, hosted packages only
#   PyPI            requirements*.txt, exact == pins
#   NuGet           *.csproj and Directory.Packages.props, exact versions
#
# A workflow, manifest or lockfile is compared between the merge base and the
# head, so only the pins and versions this pull request adds are aged — a
# dependency that has sat at its version for a year is not re-verified on every
# unrelated PR.
# A younger gem version passes only when ruby-advisory-db shows it patches an
# advisory affecting the version it replaces.
#
# State semantics (consistent with Renovate stability-days):
#   pending — at least one version under MIN_AGE_DAYS; merge blocked
#   success — every version at or above MIN_AGE_DAYS; merge unblocked
#   error   — could not read a file or resolve a release date
#
# Required env: GH_TOKEN, GITHUB_REPOSITORY, COMMIT_SHA, PR_NUMBER, NOTIFY_HANDLE,
#               MIN_AGE_DAYS
# Optional env: READY_LABEL (default ready-to-merge)
#
# MIN_AGE_DAYS has no default on purpose: a default here is a second place the
# organization-wide policy is written down, and it keeps its own number in
# silence when the organization variable moves.
#
# NOTIFY_HANDLE is the user or team to @-mention when the cooldown clears.
# Team format: <org>/<team-slug>, e.g. 4shark/app-back-end-development.

set -euo pipefail

export LC_ALL=C

READY_LABEL="${READY_LABEL:-ready-to-merge}"
STATUS_CONTEXT="Verify Minimum Age"
DEPENDENCY_FILE_PATTERN='^(\.github/(workflows|actions)/|(.*/)?(Gemfile\.lock|yarn\.lock|pubspec\.lock|requirements[^/]*\.txt|[^/]+\.csproj|Directory\.Packages\.props)$)'

: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${COMMIT_SHA:?COMMIT_SHA is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"
: "${NOTIFY_HANDLE:?NOTIFY_HANDLE is required}"
: "${MIN_AGE_DAYS:?DEPENDENCY_MINIMUM_RELEASE_AGE_DAYS is required}"

# Prints one "name<TAB>version" line per registry release or action pin the file holds.
list_versions() {
  local ecosystem="$1"
  local file="$2"

  case "$ecosystem" in
    action)
      sed -nE 's/^[[:space:]]*-?[[:space:]]*uses:[[:space:]]+([^.\/][^@[:space:]]+)@([0-9a-f]{40}).*$/\1\t\2/p' "$file"
      ;;
    rubygems)
      awk '
        /^[A-Z]/ { in_gem_section = ($0 == "GEM") }
        in_gem_section && /^    [a-zA-Z0-9._-]+ \([0-9][^)]*\)$/ { version = $2; gsub(/[()]/, "", version); print $1 "\t" version }
      ' "$file"
      ;;
    npm)
      sed -nE \
        -e 's/^  resolution: "(.+)@npm:([^"]+)"$/\1\t\2/p' \
        -e 's%^  resolved "https://registry\.(yarnpkg\.com|npmjs\.org)/((@[^/]+/)?([^/]+))/-/\4-([^"#]+)\.tgz(#[^"]*)?"$%\2\t\5%p' \
        "$file"
      ;;
    pub)
      awk '
        /^  [^ ]/ { package_name = ""; package_source = "" }
        /^      name: / { package_name = $2 }
        /^    source: / { package_source = $2 }
        /^    version: / && package_source == "hosted" { version = $2; gsub(/"/, "", version); print package_name "\t" version }
      ' "$file"
      ;;
    pypi)
      sed -nE 's/^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^]]*\])?[[:space:]]*==[[:space:]]*([^[:space:];#]+).*$/\1\t\3/p' "$file"
      ;;
    nuget)
      sed -nE \
        -e 's/.*<Package(Reference|Version)[[:space:]]+Include="([^"]+)"[[:space:]]+Version="([0-9][^"*,()$]*)".*/\2\t\3/p' \
        -e 's/.*<Package(Reference|Version)[[:space:]]+Version="([0-9][^"*,()$]*)"[[:space:]]+Include="([^"]+)".*/\3\t\2/p' \
        "$file"
      ;;
  esac
}

# Succeeds when an advisory in ruby-advisory-db affects the replaced version
# and not the added one. Requirements are read the way bundler-audit reads them.
patches_rubygems_advisory() {
  local package="$1"
  local replaced_version="${2%%-*}"
  local added_version="${3%%-*}"
  local advisory_urls

  advisory_urls=$(gh api "repos/rubysec/ruby-advisory-db/contents/gems/${package}" --jq '.[].download_url' 2>/dev/null) || return 1

  while IFS= read -r advisory_url; do
    [[ -n "$advisory_url" ]] || continue

    if curl -sf --max-time 30 --retry 3 --retry-all-errors --retry-max-time 90 "$advisory_url" | ruby -ryaml -rdate -e '
      advisory = YAML.safe_load($stdin.read, permitted_classes: [Date])
      requirements = lambda { |key| Array(advisory[key]).map { |requirement| Gem::Requirement.new(*requirement.split(", ")) } }
      safe_requirements = requirements.call("patched_versions") + requirements.call("unaffected_versions")
      vulnerable = lambda { |version| safe_requirements.none? { |requirement| requirement.satisfied_by?(Gem::Version.new(version)) } }
      exit(vulnerable.call(ARGV[0]) && !vulnerable.call(ARGV[1]))
    ' "$replaced_version" "$added_version"; then
      return 0
    fi
  done <<< "$advisory_urls"

  return 1
}

# --paginate prints the pages it fetched before failing on a later one, so only the
# exit status tells a truncated list from a complete one.
if ! PR_FILES=$(gh api "repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}/files" --paginate \
                  --jq '.[] | "\(.status)\t\(.filename)\t\(.previous_filename // .filename)"' 2>/dev/null); then
  PR_FILES=""
fi

# A pull request always changes at least one file, so an empty list means the read failed.
if [[ -z "$PR_FILES" ]]; then
  gh api -X POST "repos/${GITHUB_REPOSITORY}/statuses/${COMMIT_SHA}" \
    -f state="error" \
    -f context="$STATUS_CONTEXT" \
    -f description="Could not read the pull request file list" >/dev/null
  echo "::error::could not read the file list of PR #${PR_NUMBER}"
  exit 0
fi

# Skip verification when the PR diff moves no dependency this script can age.
# Without such a change there is nothing to verify and the "cooldown complete"
# notification has no semantic meaning. Post a green status so branch
# protection stays satisfied, then bail.
PR_PATHS=$(printf '%s\n' "$PR_FILES" | cut -f2)
if ! grep -qE "$DEPENDENCY_FILE_PATTERN" <<< "$PR_PATHS"; then
  gh api -X POST "repos/${GITHUB_REPOSITORY}/statuses/${COMMIT_SHA}" \
    -f state="success" \
    -f context="$STATUS_CONTEXT" \
    -f description="No dependency pin, manifest or lockfile changes in this PR" >/dev/null
  echo "PR #${PR_NUMBER} touched no workflow, action, manifest or lockfile; skipping verification."
  exit 0
fi

NOW=$(date -u +%s)
THRESHOLD_SECONDS=$((MIN_AGE_DAYS * 86400))

TOTAL=0
NEW_VERSIONS=0
VIOLATIONS=0
SECURITY_EXEMPTIONS=0
ERRORS=0
MIN_AGE_FOUND=999999
DEPENDENCIES=""

# gh api writes the error body to stdout, so a failed call has to leave the value empty rather than keep that body.
BASE_REF=$(gh api "repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}" --jq '.base.ref' 2>/dev/null) || BASE_REF=""
MERGE_BASE_SHA=$(gh api "repos/${GITHUB_REPOSITORY}/compare/${BASE_REF}...${COMMIT_SHA}" --jq '.merge_base_commit.sha // empty' 2>/dev/null) || MERGE_BASE_SHA=""

# An empty ref makes the contents API answer from the default branch instead of failing.
if [[ -z "$MERGE_BASE_SHA" ]]; then
  echo "::error::could not resolve the merge base of ${COMMIT_SHA}"
  ERRORS=$((ERRORS + 1))
fi

HEAD_CONTENT_FILE=$(mktemp)
BASE_CONTENT_FILE=$(mktemp)
trap 'rm -f "$HEAD_CONTENT_FILE" "$BASE_CONTENT_FILE"' EXIT

while IFS=$'\t' read -r FILE_STATUS FILE_PATH PREVIOUS_PATH; do
  [[ -z "$FILE_PATH" || "$FILE_STATUS" == "removed" ]] && continue

  case "$FILE_PATH" in
    .github/workflows/* | .github/actions/*) ECOSYSTEM="action" ;;
    Gemfile.lock | */Gemfile.lock) ECOSYSTEM="rubygems" ;;
    yarn.lock | */yarn.lock) ECOSYSTEM="npm" ;;
    pubspec.lock | */pubspec.lock) ECOSYSTEM="pub" ;;
    requirements*.txt | */requirements*.txt) ECOSYSTEM="pypi" ;;
    *.csproj | Directory.Packages.props | */Directory.Packages.props) ECOSYSTEM="nuget" ;;
    *) continue ;;
  esac

  if ! gh api -H "Accept: application/vnd.github.raw" "repos/${GITHUB_REPOSITORY}/contents/${FILE_PATH}?ref=${COMMIT_SHA}" > "$HEAD_CONTENT_FILE" 2>/dev/null; then
    echo "::error::${FILE_PATH} — could not read the file at ${COMMIT_SHA}"
    ERRORS=$((ERRORS + 1))
    continue
  fi

  : > "$BASE_CONTENT_FILE"

  if [[ "$FILE_STATUS" != "added" && -z "$MERGE_BASE_SHA" ]]; then
    continue
  fi

  if [[ "$FILE_STATUS" != "added" ]] && ! gh api -H "Accept: application/vnd.github.raw" "repos/${GITHUB_REPOSITORY}/contents/${PREVIOUS_PATH}?ref=${MERGE_BASE_SHA}" > "$BASE_CONTENT_FILE" 2>/dev/null; then
    echo "::error::${PREVIOUS_PATH} — could not read the file at ${MERGE_BASE_SHA}"
    ERRORS=$((ERRORS + 1))
    continue
  fi

  BASE_VERSIONS=$(list_versions "$ECOSYSTEM" "$BASE_CONTENT_FILE" | sort -u)
  ADDED_VERSIONS=$(comm -13 <(printf '%s\n' "$BASE_VERSIONS") <(list_versions "$ECOSYSTEM" "$HEAD_CONTENT_FILE" | sort -u))

  while IFS=$'\t' read -r PACKAGE VERSION; do
    [[ -z "$PACKAGE" || -z "$VERSION" ]] && continue
    NEW_VERSIONS=$((NEW_VERSIONS + 1))
    REPLACED_VERSION=$(awk -F'\t' -v package="$PACKAGE" '$1 == package { print $2; exit }' <<< "$BASE_VERSIONS")
    DEPENDENCIES+="${ECOSYSTEM}"$'\t'"${PACKAGE}"$'\t'"${VERSION}"$'\t'"${REPLACED_VERSION}"$'\n'
  done <<< "$ADDED_VERSIONS"
done <<< "$PR_FILES"

UNIQUE_DEPENDENCIES=$(printf '%s' "$DEPENDENCIES" | sort -u)

while IFS=$'\t' read -r ECOSYSTEM PACKAGE VERSION REPLACED_VERSION; do
  [[ -z "$ECOSYSTEM" ]] && continue
  TOTAL=$((TOTAL + 1))

  case "$ECOSYSTEM" in
    action)
      # An action in a subdirectory (actions/cache/restore) is a commit of its owner/repo.
      ACTION_REPOSITORY=$(echo "$PACKAGE" | cut -d/ -f1-2)
      # gh api has no retry or timeout option, so both are applied here.
      for ATTEMPT in 1 2 3; do
        RELEASE_DATE=$(timeout 30 gh api "repos/${ACTION_REPOSITORY}/commits/${VERSION}" --jq '.commit.committer.date' 2>/dev/null) || RELEASE_DATE=""
        [[ -n "$RELEASE_DATE" || "$ATTEMPT" -eq 3 ]] && break
        sleep $((ATTEMPT * 2))
      done
      ;;
    rubygems)
      # A hyphen in a lockfile version is always a platform suffix — RubyGems
      # spells prereleases with a dot — and the release endpoint takes the bare
      # version. built_at is unreliable (some releases carry 1980); created_at
      # is when the version was actually published.
      RELEASE_DATE=$(curl -sf --max-time 30 --retry 3 --retry-all-errors --retry-max-time 90 "https://rubygems.org/api/v2/rubygems/${PACKAGE}/versions/${VERSION%%-*}.json" \
                     | jq -r '.created_at // empty' 2>/dev/null || true)
      ;;
    npm)
      RELEASE_DATE=$(curl -sf --max-time 30 --retry 3 --retry-all-errors --retry-max-time 90 "https://registry.npmjs.org/${PACKAGE/\//%2F}" \
                     | jq -r --arg version "$VERSION" '.time[$version] // empty' 2>/dev/null || true)
      ;;
    pub)
      RELEASE_DATE=$(curl -sf --max-time 30 --retry 3 --retry-all-errors --retry-max-time 90 "https://pub.dev/api/packages/${PACKAGE}/versions/${VERSION}" \
                     | jq -r '.published // empty' 2>/dev/null || true)
      ;;
    pypi)
      RELEASE_DATE=$(curl -sfL --max-time 30 --retry 3 --retry-all-errors --retry-max-time 90 "https://pypi.org/pypi/${PACKAGE}/${VERSION}/json" \
                     | jq -r '[.urls[].upload_time_iso_8601] | min // empty' 2>/dev/null || true)
      ;;
    nuget)
      NUGET_PATH=$(echo "${PACKAGE}/${VERSION}" | tr '[:upper:]' '[:lower:]')
      RELEASE_DATE=$(curl -sf --max-time 30 --retry 3 --retry-all-errors --retry-max-time 90 --compressed "https://api.nuget.org/v3/registration5-gz-semver2/${NUGET_PATH}.json" \
                     | jq -r '.published // empty' 2>/dev/null || true)
      ;;
  esac

  if [[ -z "$RELEASE_DATE" ]]; then
    echo "::error::${PACKAGE} ${VERSION} — could not resolve the ${ECOSYSTEM} release date"
    ERRORS=$((ERRORS + 1))
    continue
  fi

  RELEASE_TS=$(date -u -d "$RELEASE_DATE" +%s 2>/dev/null || true)
  if [[ -z "$RELEASE_TS" ]]; then
    echo "::error::${PACKAGE} ${VERSION} — could not parse release date ${RELEASE_DATE}"
    ERRORS=$((ERRORS + 1))
    continue
  fi

  AGE_SECONDS=$((NOW - RELEASE_TS))
  AGE_DAYS=$((AGE_SECONDS / 86400))

  if [[ "$AGE_DAYS" -lt "$MIN_AGE_FOUND" ]]; then
    MIN_AGE_FOUND=$AGE_DAYS
  fi

  if [[ "$AGE_SECONDS" -lt "$THRESHOLD_SECONDS" ]]; then
    if [[ "$ECOSYSTEM" == "rubygems" && -n "$REPLACED_VERSION" ]] && patches_rubygems_advisory "$PACKAGE" "$REPLACED_VERSION" "$VERSION"; then
      echo "::notice::${PACKAGE} ${VERSION} (${ECOSYSTEM}) — ${AGE_DAYS} days old, accepted because it patches an advisory affecting ${REPLACED_VERSION}"
      SECURITY_EXEMPTIONS=$((SECURITY_EXEMPTIONS + 1))
    else
      echo "::warning::${PACKAGE} ${VERSION} (${ECOSYSTEM}) — ${AGE_DAYS} days old (released ${RELEASE_DATE}); minimum is ${MIN_AGE_DAYS} days"
      VIOLATIONS=$((VIOLATIONS + 1))
    fi
  fi
done <<< "$UNIQUE_DEPENDENCIES"

STATE=""
DESCRIPTION=""

if [[ "$ERRORS" -gt 0 ]]; then
  STATE="error"
  DESCRIPTION="${ERRORS} dependency/dependencies or files failed to resolve"
elif [[ "$TOTAL" -eq 0 ]]; then
  STATE="success"
  DESCRIPTION="No SHA-pinned actions or added dependency versions to verify"
elif [[ "$VIOLATIONS" -gt 0 ]]; then
  STATE="pending"
  DESCRIPTION="${VIOLATIONS}/${TOTAL} dependency/dependencies under ${MIN_AGE_DAYS}-day cooldown; youngest is ${MIN_AGE_FOUND} days old"
elif [[ "$SECURITY_EXEMPTIONS" -gt 0 ]]; then
  STATE="success"
  DESCRIPTION="All ${TOTAL} dependency/dependencies at or above ${MIN_AGE_DAYS} days, except ${SECURITY_EXEMPTIONS} that patch a security advisory"
else
  STATE="success"
  DESCRIPTION="All ${TOTAL} dependency/dependencies at or above ${MIN_AGE_DAYS} days"
fi

gh api -X POST "repos/${GITHUB_REPOSITORY}/statuses/${COMMIT_SHA}" \
  -f state="$STATE" \
  -f context="$STATUS_CONTEXT" \
  -f description="${DESCRIPTION:0:140}" >/dev/null
echo "Posted commit status: state=${STATE} description=${DESCRIPTION}"

if ! PR_LABELS=$(gh api "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/labels" --jq ".[].name" 2>/dev/null); then
  echo "::warning::could not read the labels of PR #${PR_NUMBER}; left '${READY_LABEL}' untouched"
  exit 0
fi

if grep -Fxq "$READY_LABEL" <<< "$PR_LABELS"; then
  HAS_LABEL="yes"
else
  HAS_LABEL="no"
fi

# A PR that adds no dependency version has nothing the team is waiting on, so it gets no label and no comment.
if [[ "$STATE" == "success" && "$HAS_LABEL" == "no" && "$NEW_VERSIONS" -gt 0 ]]; then
  if ! gh api "repos/${GITHUB_REPOSITORY}/labels/${READY_LABEL}" >/dev/null 2>&1; then
    gh api -X POST "repos/${GITHUB_REPOSITORY}/labels" \
      -f name="$READY_LABEL" \
      -f color="0e8a16" \
      -f description="Every new dependency version is past the minimum release age — safe to merge" >/dev/null
  fi
  gh api -X POST "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/labels" \
    -f "labels[]=${READY_LABEL}" >/dev/null
  gh api -X POST "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments" \
    -f body="@${NOTIFY_HANDLE} every new dependency version in this PR was published at least ${MIN_AGE_DAYS} days ago — this PR is mergeable." >/dev/null
  echo "Added label '${READY_LABEL}' and notified @${NOTIFY_HANDLE} on PR #${PR_NUMBER}."
elif [[ "$STATE" != "success" && "$HAS_LABEL" == "yes" ]]; then
  gh api -X DELETE "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/labels/${READY_LABEL}" >/dev/null
  echo "Removed label '${READY_LABEL}' from PR #${PR_NUMBER} (cooldown restarted)."
fi
