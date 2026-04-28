#!/usr/bin/env bash
# Public-safe secret scanner. Catches the most common patterns that must NEVER
# land in this public repository. Designed to run in CI and locally.
# 公共安全 secret 扫描脚本：拦截最常见的不可入仓机密模式。CI 与本地均可运行。
#
# Usage:
#   bash scripts/secret-scan-public.sh             # scan tracked files
#   bash scripts/secret-scan-public.sh --staged    # scan only staged changes
#
# Exit code 0 = clean, 1 = potential secret found.

set -u

mode="tracked"
if [ "${1:-}" = "--staged" ]; then
  mode="staged"
fi

if [ "$mode" = "staged" ]; then
  files=$(git diff --cached --name-only --diff-filter=ACM)
else
  files=$(git ls-files)
fi

# Allow-list paths where example/placeholder strings are expected.
# 允许列出示例占位符的路径
allow_re='^(SECURITY\.md|README\.md|README_CN\.md|\.env\.example|config/config\.example\.yaml|scripts/secret-scan-public\.sh|\.github/workflows/.*\.ya?ml)$'

# Pattern -> human description. Be conservative to keep false positives low.
patterns=(
  'gh[pousr]_[A-Za-z0-9]{30,}|GitHub fine-grained / classic PAT'
  'github_pat_[A-Za-z0-9_]{20,}|GitHub fine-grained PAT'
  'sk-[A-Za-z0-9]{32,}|OpenAI-style API key'
  'sk-ant-[A-Za-z0-9_-]{20,}|Anthropic API key'
  'AKIA[0-9A-Z]{16}|AWS access key id'
  'AIza[0-9A-Za-z_-]{35}|Google API key'
  '-----BEGIN (RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY-----|Private key block'
  'xox[abprs]-[A-Za-z0-9-]{10,}|Slack token'
  'endpoint=sb://[^[:space:]"]+|Service Bus / Event Hub conn string'  # scanner-pattern
  'DefaultEndpointsProtocol=https;AccountName=[^;[:space:]]+;AccountKey=[A-Za-z0-9+/=]{20,}|Azure Storage conn string'  # scanner-pattern
  'AccountKey=[A-Za-z0-9+/=]{60,}|Azure key in conn string'
  'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}|JWT-like token'
)

# Forbidden file paths — must never exist in repo.
forbidden_paths=(
  '^\.env$'
  '^config/config\.yaml$'
  '^secrets/'
  '\.pem$'
  '\.pfx$'
  '\.p12$'
  '_id_rsa$'
)

fail=0
report() {
  echo "::warning::secret-scan: $*"
  fail=1
}

# Check forbidden paths
for f in $files; do
  for fp in "${forbidden_paths[@]}"; do
    if echo "$f" | grep -Eq "$fp"; then
      report "forbidden file present: $f"
    fi
  done
done

# Pattern scan
for f in $files; do
  [ -f "$f" ] || continue
  # Skip binary
  if file "$f" | grep -q 'binary'; then continue; fi
  if echo "$f" | grep -Eq "$allow_re"; then
    skip_examples=1
  else
    skip_examples=0
  fi
  for entry in "${patterns[@]}"; do
    pat="${entry%%|*}"
    desc="${entry##*|}"
    matches=$(grep -nE "$pat" "$f" 2>/dev/null || true)
    if [ -n "$matches" ]; then
      if [ "$skip_examples" = "1" ]; then
        # In allow-listed files, only flag if the line is NOT obviously a placeholder.
        # 在允许文件中：仅当不是占位符时才告警
        flagged=$(echo "$matches" | grep -viE 'YOUR_|EXAMPLE|PLACEHOLDER|<.*>|\.\.\.|scanner-pattern' || true)
        if [ -z "$flagged" ]; then continue; fi
        matches="$flagged"
      fi
      # Print only file:line numbers, NEVER the matched value.
      lines=$(echo "$matches" | awk -F: '{print $1}' | xargs)
      report "$desc in $f at lines: $lines"
    fi
  done
done

if [ "$fail" -eq 0 ]; then
  echo "secret-scan: PASS — no obvious secrets detected ($(echo "$files" | wc -w) files)."
  exit 0
else
  echo "secret-scan: FAIL — review the warnings above. Do NOT commit secrets."
  exit 1
fi
