#!/bin/bash
# Test script for CORE-2 and CORE-3: dual-mode wrapper build, product allowlist, and path derivation
# CORE-2 acceptance: Baked-mode behavior byte-identical; product mode rejects
# `--product /tmp/x`, `Claude`, extra args with exit 8 and no exec
# CORE-3 acceptance: --validate-only prints distinct roots for four ids; env dump
# equals the documented set; a bundle owned by another user with 0755/0644 passes

set -euo pipefail

TEMP_DIR=""

cleanup() {
  if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
    rm -rf "$TEMP_DIR"
  fi
}

trap cleanup EXIT

echo "=== CORE-2 + CORE-3 Test Suite ==="
echo

# Test 1: Baked mode compilation (existing behavior)
echo "Test 1: Baked mode compilation"
clang -Wall -Wextra -Werror -O2 \
  -DHELPER_SCRIPT='"/tmp/helper.py"' \
  -DSEND_GATE_SCRIPT='"/tmp/send_gate.py"' \
  -DCONFIRM_HELPER='"/tmp/confirm"' \
  -DBRIDGE_ROOT='"/tmp/bridge"' \
  -DHELPER_DISPLAY_NAME='"test-helper"' \
  -fsyntax-only bin/imessage_helper.c
echo "✓ Baked mode compiles successfully"
echo

# Test 2: Product mode compilation
echo "Test 2: Product mode compilation"
clang -Wall -Wextra -Werror -O2 \
  -DIMESSAGE_PRODUCT_BUILD=1 \
  -DHELPER_DISPLAY_NAME='"test-helper"' \
  -o /tmp/test-product-helper bin/imessage_helper.c
echo "✓ Product mode compiles successfully"
echo

# Test 3: Mutual exclusivity (should fail to compile)
echo "Test 3: Mutual exclusivity check"
if clang -Wall -Wextra -Werror -O2 \
  -DIMESSAGE_PRODUCT_BUILD=1 \
  -DHELPER_SCRIPT='"/tmp/helper.py"' \
  -DSEND_GATE_SCRIPT='"/tmp/send_gate.py"' \
  -DCONFIRM_HELPER='"/tmp/confirm"' \
  -DBRIDGE_ROOT='"/tmp/bridge"' \
  -fsyntax-only bin/imessage_helper.c 2>/dev/null; then
  echo "✗ FAIL: Product build should reject baked path macros"
  exit 1
fi
echo "✓ Product build correctly rejects baked path macros"
echo

# Test 4: Product mode rejects path-like argument
echo "Test 4: Reject path-like product ID"
set +e
/tmp/test-product-helper --product /tmp/x 2>/dev/null
exit_code=$?
set -e
if [ $exit_code -ne 8 ]; then
  echo "✗ FAIL: Exit code should be 8, got $exit_code"
  exit 1
fi
echo "✓ Path-like product ID rejected with exit 8"
echo

# Test 5: Product mode rejects case-wrong argument
echo "Test 5: Reject case-wrong product ID"
set +e
/tmp/test-product-helper --product Claude 2>/dev/null
exit_code=$?
set -e
if [ $exit_code -ne 8 ]; then
  echo "✗ FAIL: Exit code should be 8, got $exit_code"
  exit 1
fi
echo "✓ Case-wrong product ID rejected with exit 8"
echo

# Test 6: Product mode rejects extra arguments
echo "Test 6: Reject extra arguments"
set +e
/tmp/test-product-helper --product openai extra-arg 2>/dev/null
exit_code=$?
set -e
if [ $exit_code -ne 8 ]; then
  echo "✗ FAIL: Exit code should be 8, got $exit_code"
  exit 1
fi
echo "✓ Extra arguments rejected with exit 8"
echo

# Test 7: Product mode requires --product
echo "Test 7: Require --product argument"
set +e
/tmp/test-product-helper 2>/dev/null
exit_code=$?
set -e
if [ $exit_code -ne 8 ]; then
  echo "✗ FAIL: Exit code should be 8, got $exit_code"
  exit 1
fi
echo "✓ Missing --product rejected with exit 8"
echo

# Test 8: Product mode rejects duplicate --product arguments
echo "Test 8: Reject duplicate --product arguments"
set +e
/tmp/test-product-helper --product claude --product grok --validate-only 2>/dev/null
exit_code=$?
set -e
if [ $exit_code -ne 8 ]; then
  echo "✗ FAIL: Duplicate --product should exit 8, got $exit_code"
  exit 1
fi
echo "✓ Duplicate --product rejected with exit 8"
echo

# Test 9: Product mode rejects duplicate --validate-only arguments
echo "Test 9: Reject duplicate --validate-only arguments"
set +e
/tmp/test-product-helper --product openai --validate-only --validate-only 2>/dev/null
exit_code=$?
set -e
if [ $exit_code -ne 8 ]; then
  echo "✗ FAIL: Duplicate --validate-only should exit 8, got $exit_code"
  exit 1
fi
echo "✓ Duplicate --validate-only rejected with exit 8"
echo

# Test 10: Validate-only requires bundle structure  
echo "Test 10: Validate-only requires bundle (exits 9 without)"
set +e
output=$(/tmp/test-product-helper --product claude --validate-only 2>&1)
exit_code=$?
set -e
if [ $exit_code -ne 9 ]; then
  echo "✗ FAIL: Exit code should be 9 (bundle not found), got $exit_code"
  echo "  Output: $output"
  exit 1
fi
echo "✓ Validate-only correctly requires bundle structure"
echo

# Test 11: Product mode without --validate-only exits 9 (not in bundle)
echo "Test 11: Product mode exec exits 9 when not in bundle"
set +e
/tmp/test-product-helper --product openai 2>/dev/null
exit_code=$?
set -e
if [ $exit_code -ne 9 ]; then
  echo "✗ FAIL: Exit code should be 9 (bundle not found), got $exit_code"
  exit 1
fi
echo "✓ Product mode exec correctly returns exit 9"
echo

echo "=== CORE-3 Tests ==="
echo

# Test 12: Create fake bundle structure and test distinct roots
echo "Test 12: Distinct roots for four product IDs"
TEMP_DIR=$(mktemp -d)

# Create fake bundle structure
BUNDLE_PATH="$TEMP_DIR/TestApp.app"
mkdir -p "$BUNDLE_PATH/Contents/Helpers"
mkdir -p "$BUNDLE_PATH/Contents/Resources/core/bin"
mkdir -p "$BUNDLE_PATH/Contents/Frameworks/Python.framework/Versions/Current/bin"

# Create Info.plist
echo '<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.test.app</string>
</dict>
</plist>' > "$BUNDLE_PATH/Contents/Info.plist"

# Create dummy files
touch "$BUNDLE_PATH/Contents/Resources/core/bin/helper.py"
touch "$BUNDLE_PATH/Contents/Resources/core/bin/send_gate.py"
touch "$BUNDLE_PATH/Contents/Helpers/imessage-confirm"
touch "$BUNDLE_PATH/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"

# Compile product-mode helper into the bundle
clang -Wall -Wextra -Werror -O2 \
  -DIMESSAGE_PRODUCT_BUILD=1 \
  -DAPP_SUPPORT_DIRNAME='"TestBridgePro"' \
  -DPYTHON_RELPATH='"Versions/Current/bin/python3"' \
  -DHELPER_DISPLAY_NAME='"test-helper"' \
  -o "$BUNDLE_PATH/Contents/Helpers/test-helper" \
  bin/imessage_helper.c

echo "  ✓ Compiled product-mode helper in bundle"

# Test distinct roots for each product ID
for id in claude grok openai manager; do
  if ! output=$("$BUNDLE_PATH/Contents/Helpers/test-helper" --product "$id" --validate-only); then
    echo "✗ FAIL: --product $id --validate-only should succeed"
    exit 1
  fi
  
  if ! echo "$output" | grep -q "\"product\":\"$id\""; then
    echo "✗ FAIL: JSON output should contain product ID $id"
    exit 1
  fi
  
  if ! echo "$output" | grep -q "\"bridge_root\":"; then
    echo "✗ FAIL: JSON output should contain bridge_root"
    exit 1
  fi
  
  if ! echo "$output" | grep -q "/TestBridgePro/bridges/$id"; then
    echo "✗ FAIL: Bridge root should contain /TestBridgePro/bridges/$id"
    exit 1
  fi
  
  # Check policy_dir for host roles only
  if [ "$id" != "manager" ]; then
    if ! echo "$output" | grep -q "\"policy_dir\":"; then
      echo "✗ FAIL: Host role should have policy_dir"
      exit 1
    fi
    if ! echo "$output" | grep -q "/TestBridgePro/policies/$id"; then
      echo "✗ FAIL: Policy dir should contain /TestBridgePro/policies/$id"
      exit 1
    fi
  else
    if echo "$output" | grep -q "\"policy_dir\":"; then
      echo "✗ FAIL: Manager role should not have policy_dir"
      exit 1
    fi
  fi
  
  echo "  ✓ $id: distinct root verified"
done
echo "✓ All product IDs have distinct roots"
echo

# Test 13: Verify bundle path resolution
echo "Test 13: Bundle path components in output"
output=$("$BUNDLE_PATH/Contents/Helpers/test-helper" --product claude --validate-only)
if ! echo "$output" | grep -q "\"helper_py\":\".*TestApp.app/Contents/Resources/core/bin/helper.py\""; then
  echo "✗ FAIL: helper_py path not resolved correctly"
  exit 1
fi
if ! echo "$output" | grep -q "\"python_interp\":\".*Python.framework/Versions/Current/bin/python3\""; then
  echo "✗ FAIL: python_interp path not resolved correctly"
  exit 1
fi
echo "✓ Bundle-relative paths resolved correctly"
echo

echo "=== All CORE-2 + CORE-3 tests passed ==="
