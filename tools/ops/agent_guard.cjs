#!/usr/bin/env node
// Claude Code PreToolUse hook (.claude/settings.json): blocks the tool calls AGENTS.md forbids.
// - Edit/Write: the target file's checkout is on branch master (the management checkout).
// - Bash/PowerShell: git clean -x/-X, bare git stash, git stash pop/clear, git push --force/-f/
//   --force-with-lease/+refspec, recursive rm of the data directory.
// Reads the hook JSON on stdin; exit 2 with the reason on stderr blocks the call, exit 0 allows
// it, any other exit is a hook error Claude Code shows without blocking. Rollback: revert
// .claude/settings.json. Tests: tools/ops/agent_guard.test.cjs (node --test).
'use strict';

// Allowed commands: one regex per entry, tested against each whole command segment (trimmed,
// quotes kept). An entry here overrides every Bash/PowerShell rule below; add one in a PR.
// Example: /^git push --force-with-lease origin task\/\S+$/
const ALLOW = [];

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

// git with its global options (-C <dir>, -c <k=v>, --no-pager, ...) before the subcommand.
const GIT = String.raw`(?:^|[\s(&;|])git(?:\s+(?:-C|-c|--git-dir|--work-tree)(?:\s+|=)\S+|\s+--?[\w-]+(?:=\S+)?)*\s+`;
const DATA_DIR = /stock-lab-data|STOCK_DATA_DIR/i;
const REMOVE = /(?:^|[\s(&;|])(?:rm|Remove-Item|ri|rmdir)(?=\s)/i;
const RECURSIVE = /\s(?:-[dfiIrRv]*[rR][dfiIrRv]*|--recursive|-rec\w*|-r)(?=[\s:]|$)/i;

const RULES = [
  {
    re: new RegExp(GIT + String.raw`clean\b.*\s-[A-Za-z]*[xX]`),
    reason: 'git clean -x／-X 會刪除 .gitignore 內的檔案（.local 副本、依賴、資料）',
  },
  {
    re: new RegExp(GIT + String.raw`stash\s+pop\b`),
    reason: 'stash 堆疊所有 worktree 共用，pop 可能取走別的 session 的變更；改用 git stash apply <sha>，再依 tag 找到自己那筆 drop',
  },
  {
    re: new RegExp(GIT + String.raw`stash\s+clear\b`),
    reason: 'git stash clear 會清掉所有 worktree 共用的 stash',
  },
  {
    re: new RegExp(GIT + String.raw`stash(?!\s+(?:push|apply|list|drop|show)\b)(?=\s|$)`),
    reason: '裸 git stash 進共用堆疊後分不出是誰的；改用 git stash push -u -m <唯一 tag>',
  },
  {
    re: new RegExp(
      GIT +
        String.raw`push\b(?:.*\s(?:--force(?:-with-lease)?(?:=\S*)?|-[A-Za-z]*f[A-Za-z]*)(?=\s|$)|.*\s\+\S)`,
    ),
    reason: '主線規則禁止強推（--force-with-lease 與 +refspec 也擋）',
  },
  {
    test: (segment) => REMOVE.test(segment.bare) && RECURSIVE.test(segment.bare) && DATA_DIR.test(segment.raw),
    reason: '不得刪資料目錄（AGENTS.md「工具」）',
  },
];

// Splits a command into segments at unquoted ; && || | & and newlines. `raw` keeps quoted text;
// `bare` replaces it with an empty quote pair so a rule only sees words the shell runs. Heredoc
// bodies and comments are dropped from both: they are input and notes, not commands.
function segments(command, shell = 'bash') {
  const out = [];
  let raw = '';
  let bare = '';
  const heredocs = [];
  const flush = () => {
    if (raw.trim()) out.push({ raw: raw.trim(), bare: bare.trim() });
    raw = '';
    bare = '';
  };
  const escape = shell === 'powershell' ? '`' : '\\';
  let i = 0;
  while (i < command.length) {
    const ch = command[i];
    const rest = command.slice(i);
    if (ch === escape) {
      raw += command.slice(i, i + 2);
      bare += command.slice(i, i + 2);
      i += 2;
      continue;
    }
    const here = shell === 'powershell' && /^@(['"])\r?\n/.exec(rest);
    if (here) {
      const close = command.indexOf(`\n${here[1]}@`, i);
      const end = close < 0 ? command.length : close + 3;
      raw += command.slice(i, end);
      bare += '""';
      i = end;
      continue;
    }
    if (ch === "'" || ch === '"') {
      let j = i + 1;
      while (j < command.length && command[j] !== ch) j += ch === '"' && command[j] === escape ? 2 : 1;
      raw += command.slice(i, j + 1);
      bare += ch + ch;
      i = j + 1;
      continue;
    }
    const heredoc = shell === 'bash' && /^<<(-?)\s*(['"]?)([A-Za-z_][\w-]*)\2/.exec(rest);
    if (heredoc) {
      heredocs.push({ strip: heredoc[1] === '-', word: heredoc[3] });
      raw += '<<' + heredoc[3];
      bare += '<<' + heredoc[3];
      i += heredoc[0].length;
      continue;
    }
    if (ch === '#' && /(^|\s)$/.test(bare)) {
      while (i < command.length && command[i] !== '\n') i += 1;
      continue;
    }
    if (ch === '\n') {
      flush();
      i += 1;
      while (heredocs.length) {
        const { strip, word } = heredocs.shift();
        while (i < command.length) {
          const eol = command.indexOf('\n', i);
          const line = command.slice(i, eol < 0 ? command.length : eol).replace(/\r$/, '');
          i = eol < 0 ? command.length : eol + 1;
          if ((strip ? line.replace(/^\t+/, '') : line) === word) break;
        }
      }
      continue;
    }
    if (ch === ';' || ch === '|' || ch === '&') {
      flush();
      i += command[i + 1] === ch ? 2 : 1;
      continue;
    }
    raw += ch;
    bare += ch;
    i += 1;
  }
  flush();
  return out;
}

// The reason a Bash/PowerShell command is blocked, or null.
function commandDenial(command, shell = 'bash', allow = ALLOW) {
  for (const segment of segments(command, shell)) {
    if (allow.some((re) => re.test(segment.raw))) continue;
    for (const rule of RULES) {
      if (rule.test ? rule.test(segment) : rule.re.test(segment.bare)) {
        return (
          `擋下「${segment.raw}」：${rule.reason}。真的需要時請使用者執行，` +
          '或在 tools/ops/agent_guard.cjs 開頭的放行清單加一條（另開 PR）'
        );
      }
    }
  }
  return null;
}

// C:\x, C:/x and Git Bash /c/x name the same file on Windows; elsewhere paths stay as given.
function normalizeTarget(file, platform = process.platform) {
  if (platform !== 'win32') return file;
  return file
    .replace(/\\/g, '/')
    .replace(/^(?:\/(?:cygdrive\/)?([a-zA-Z])(?=\/|$)|([a-zA-Z]):)/, (_, posix, dos) => `${(posix || dos).toUpperCase()}:`);
}

// The nearest existing directory holding `file`, or null.
function existingDir(file) {
  let dir = file;
  for (;;) {
    try {
      if (fs.statSync(dir).isDirectory()) return dir;
    } catch {
      // not there yet: try the parent
    }
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

// The branch checked out where `dir` is, or null (not a repository, detached HEAD).
function branchAt(dir) {
  const result = spawnSync('git', ['-C', dir, 'symbolic-ref', '--short', '-q', 'HEAD'], {
    encoding: 'utf8',
    timeout: 10000,
  });
  if (result.error) throw result.error;
  return result.status === 0 ? result.stdout.trim() : null;
}

function fileDenial(file, cwd) {
  if (typeof file !== 'string' || !file) return null;
  const target = path.resolve(normalizeTarget(cwd || process.cwd()), normalizeTarget(file));
  const dir = existingDir(target);
  if (dir && branchAt(dir) === 'master') {
    return `${file} 所在的 checkout 在 master：在 worktree 改檔，不在 master 管理 checkout 改檔（AGENTS.md「工具」）`;
  }
  return null;
}

function denial(input) {
  const tool = input.tool_input || {};
  switch (input.tool_name) {
    case 'Edit':
    case 'Write':
      return fileDenial(tool.file_path, input.cwd);
    case 'Bash':
      return typeof tool.command === 'string' ? commandDenial(tool.command, 'bash') : null;
    case 'PowerShell':
      return typeof tool.command === 'string' ? commandDenial(tool.command, 'powershell') : null;
    default:
      return null;
  }
}

function main() {
  let reason;
  try {
    reason = denial(JSON.parse(fs.readFileSync(0, 'utf8')));
  } catch (error) {
    process.stderr.write(`agent_guard: hook error, call not checked: ${error.message}\n`);
    process.exit(1);
  }
  if (reason) {
    process.stderr.write(`agent_guard: ${reason}。\n`);
    process.exit(2);
  }
}

if (require.main === module) main();

module.exports = { ALLOW, commandDenial, denial, normalizeTarget, segments };
