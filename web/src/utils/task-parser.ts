/**
 * Pure utility functions for Agent-Delegate tasks, diff parsing, event timeline normalization,
 * and MCP client command formatting.
 */

export interface DiffLine {
  type: 'add' | 'del' | 'context' | 'header';
  text: string;
  oldLineNumber?: number;
  newLineNumber?: number;
}

export interface ParsedDiffFile {
  oldPath: string;
  newPath: string;
  insertions: number;
  deletions: number;
  lines: DiffLine[];
}

export interface ParsedDiff {
  files: ParsedDiffFile[];
  totalInsertions: number;
  totalDeletions: number;
}

/**
 * Parses raw git patch text into structured per-file additions, deletions and lines.
 */
export function parseGitDiff(rawDiff: string): ParsedDiff {
  if (!rawDiff || !rawDiff.trim()) {
    return { files: [], totalInsertions: 0, totalDeletions: 0 };
  }

  const lines = rawDiff.split('\n');
  const files: ParsedDiffFile[] = [];
  let currentFile: ParsedDiffFile | null = null;
  let oldLine = 0;
  let newLine = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith('diff --git ')) {
      if (currentFile) {
        files.push(currentFile);
      }
      const match = line.match(/diff --git a\/(.*) b\/(.*)/);
      const oldPath = match ? match[1] : 'unknown';
      const newPath = match ? match[2] : oldPath;
      currentFile = {
        oldPath,
        newPath,
        insertions: 0,
        deletions: 0,
        lines: [],
      };
      continue;
    }

    if (!currentFile) {
      // If header appears without 'diff --git', initialize a generic file
      if (line.startsWith('--- a/') || line.startsWith('+++ b/')) {
        const path = line.slice(6);
        currentFile = {
          oldPath: path,
          newPath: path,
          insertions: 0,
          deletions: 0,
          lines: [],
        };
      }
      continue;
    }

    if (line.startsWith('@@ ')) {
      const match = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (match) {
        oldLine = parseInt(match[1], 10);
        newLine = parseInt(match[2], 10);
      }
      currentFile.lines.push({
        type: 'header',
        text: line,
      });
      continue;
    }

    if (line.startsWith('+') && !line.startsWith('+++')) {
      currentFile.insertions++;
      currentFile.lines.push({
        type: 'add',
        text: line.slice(1),
        newLineNumber: newLine++,
      });
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      currentFile.deletions++;
      currentFile.lines.push({
        type: 'del',
        text: line.slice(1),
        oldLineNumber: oldLine++,
      });
    } else if (line.startsWith(' ') || line === '') {
      currentFile.lines.push({
        type: 'context',
        text: line.startsWith(' ') ? line.slice(1) : line,
        oldLineNumber: oldLine++,
        newLineNumber: newLine++,
      });
    }
  }

  if (currentFile) {
    files.push(currentFile);
  }

  const totalInsertions = files.reduce((acc, f) => acc + f.insertions, 0);
  const totalDeletions = files.reduce((acc, f) => acc + f.deletions, 0);

  return { files, totalInsertions, totalDeletions };
}

/**
 * Formats byte size into human readable string (KB, MB, GB).
 */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || isNaN(bytes)) return '0 B';
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(i === 0 ? 0 : 1)} ${sizes[i]}`;
}

/**
 * Formats seconds into human duration e.g. "2m 14s" or "48s".
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return '0s';
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
}

/**
 * Calculates prompt cache efficiency percentage.
 */
export function calculateCacheEfficiency(
  cacheRead: number = 0,
  promptTokens: number = 0
): number {
  const total = cacheRead + promptTokens;
  if (total <= 0) return 0;
  return Math.round((cacheRead / total) * 100);
}

/**
 * Builds the MCP setup snippet for Claude Code CLI.
 */
export function generateMcpCommand(baseUrl: string, apiKey: string): string {
  const cleanUrl = baseUrl.replace(/\/+$/, '');
  return `claude mcp add --transport http delegate ${cleanUrl}/mcp --header "Authorization: Bearer ${apiKey}"`;
}

/**
 * Check if a task status is active (queued, preparing, running) vs terminal.
 */
export function isTaskActive(status: string): boolean {
  return ['queued', 'preparing', 'running'].includes(status.toLowerCase());
}
