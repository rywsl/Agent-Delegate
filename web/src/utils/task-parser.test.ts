import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseGitDiff,
  formatBytes,
  formatDuration,
  calculateCacheEfficiency,
  generateMcpCommand,
  isTaskActive,
} from './task-parser';

test('parseGitDiff parses multi-file patch accurately', () => {
  const diff = `diff --git a/src/auth.py b/src/auth.py
index e69de29..b4d778d 100644
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,3 +10,5 @@
 def verify_token(token: str):
-    return token == "secret"
+    if not token:
+        raise ValueError("Missing token")
+    return token.startswith("dlg_")
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,2 +1,3 @@
 # Delegate
+Updated docs for v0.2.0
`;

  const parsed = parseGitDiff(diff);
  assert.equal(parsed.files.length, 2);
  assert.equal(parsed.files[0].newPath, 'src/auth.py');
  assert.equal(parsed.files[0].deletions, 1);
  assert.equal(parsed.files[0].insertions, 3);
  assert.equal(parsed.files[1].newPath, 'README.md');
  assert.equal(parsed.files[1].insertions, 1);
  assert.equal(parsed.totalInsertions, 4);
  assert.equal(parsed.totalDeletions, 1);
});

test('formatBytes formats numbers properly', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(1024), '1.0 KB');
  assert.equal(formatBytes(1048576), '1.0 MB');
  assert.equal(formatBytes(5242880), '5.0 MB');
});

test('formatDuration formats seconds properly', () => {
  assert.equal(formatDuration(42), '42s');
  assert.equal(formatDuration(125), '2m 5s');
  assert.equal(formatDuration(180), '3m');
});

test('calculateCacheEfficiency calculates ratio', () => {
  assert.equal(calculateCacheEfficiency(8000, 2000), 80);
  assert.equal(calculateCacheEfficiency(0, 5000), 0);
  assert.equal(calculateCacheEfficiency(0, 0), 0);
});

test('generateMcpCommand generates valid Claude Code add command', () => {
  const cmd = generateMcpCommand('https://delegate.acme.corp', 'dlg_99a8b7c6d5');
  assert.equal(
    cmd,
    'claude mcp add --transport http delegate https://delegate.acme.corp/mcp --header "Authorization: Bearer dlg_99a8b7c6d5"'
  );
});

test('isTaskActive identifies active vs terminal statuses', () => {
  assert.equal(isTaskActive('running'), true);
  assert.equal(isTaskActive('queued'), true);
  assert.equal(isTaskActive('preparing'), true);
  assert.equal(isTaskActive('succeeded'), false);
  assert.equal(isTaskActive('failed'), false);
  assert.equal(isTaskActive('cancelled'), false);
});
