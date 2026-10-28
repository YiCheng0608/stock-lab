#!/usr/bin/env node
// Claude Code PreToolUse hook (.claude/settings.json): blocks the tool calls AGENTS.md forbids.
// - Edit/Write: the target file's checkout is on branch master (the management checkout).
// - Bash/PowerShell: git clean -x/-X, bare git stash, git stash pop/clear, git push --force/-f/
//   --force-with-lease/+refspec, recursive rm of the data directory.
// - Every file tool, Bash/PowerShell and codebase-memory: a .env file (`.env`, or `.env.*` not
//   ending in `.example`, in any directory). See ENV RULES below for what each check covers.
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

// ENV RULES. The token the user keeps in .env must not reach an agent: block every tool call
// that names a .env file, and the commands that read one without naming it. Conservative on
// purpose: a command that only mentions a .env path (a commit message, a grep for the text) is
// blocked too. Not covered: obfuscated names (.e''nv, $(printf .env)), variables holding the
// path, and programs that open .env on their own (load_dotenv, compose env_file, docker build).
const ENV_REASON = '不得讀取、複製或改動 .env（agent 只看 .env.example；.env 由使用者自己建，AGENTS.md）';
// A .env name: after a path separator, quote, space or similar, and not inside a longer word
// (process.env, .envrc). A trailing * or ? counts: `.env*` matches the file.
const ENV_NAME = /(?:^|[\s'"`=:/\\<>(,@{[])(\.env(?:\.[\w.*?-]*)?)(?=$|[\s'"`/\\)>,;:|&}\]*?])/gi;
const isEnvName = (name) => /^\.env(?:\..*)?$/i.test(name) && !/\.example$/i.test(name);
// Directories a walk skips: not where a user keeps a .env, and too large to walk on every call.
const WALK_SKIP = new Set(['.git', 'node_modules']);
const WALK_DEPTH = 8;
const WALK_LIMIT = 50000;

// The first .env name in `text`, or null.
function envMention(text) {
  if (typeof text !== 'string') return null;
  for (const match of text.matchAll(ENV_NAME)) {
    if (isEnvName(match[1].replace(/[*?]+$/, ''))) return match[1];
  }
  return null;
}

// A shell glob as an anchored regex: * ? [..] {a,b}; `**` and `*` both stay inside one name here.
function globRegex(glob) {
  let out = '';
  for (let i = 0; i < glob.length; i += 1) {
    const ch = glob[i];
    if (ch === '*') out += '[^/\\\\]*';
    else if (ch === '?') out += '[^/\\\\]';
    else if (ch === '[') {
      const end = glob.indexOf(']', i + 1);
      if (end < 0) out += '\\[';
      else {
        out += `[${glob.slice(i + 1, end).replace(/^!/, '^').replace(/\\/g, '\\\\')}]`;
        i = end;
      }
    } else if (ch === '{') {
      const end = glob.indexOf('}', i + 1);
      if (end < 0) out += '\\{';
      else {
        out += `(?:${glob.slice(i + 1, end).split(',').map(globRegex).map((r) => r.slice(1, -1)).join('|')})`;
        i = end;
      }
    } else out += ch.replace(/[.+^$()|\\]/g, '\\$&');
  }
  return `^${out}$`;
}

// Whether a glob over file names matches `name`. Bash leaves a leading dot to an explicit `.`.
function globMatches(glob, name, shell) {
  if (shell === 'bash' && name.startsWith('.') && !glob.startsWith('.')) return false;
  return new RegExp(globRegex(glob), 'i').test(name);
}

// Shell words of a segment: quotes removed, `quoted` set when any part was quoted.
function words(raw, shell) {
  const escape = shell === 'powershell' ? '`' : '\\';
  const out = [];
  let word = null;
  for (let i = 0; i < raw.length; i += 1) {
    const ch = raw[i];
    if (/\s/.test(ch)) {
      if (word) out.push(word);
      word = null;
      continue;
    }
    word = word || { text: '', quoted: false };
    if (ch === escape && shell === 'bash' && i + 1 < raw.length) {
      word.text += raw[i + 1];
      i += 1;
    } else if (ch === "'" || ch === '"') {
      const end = raw.indexOf(ch, i + 1);
      const stop = end < 0 ? raw.length : end;
      word.text += raw.slice(i + 1, stop);
      word.quoted = true;
      i = stop;
    } else word.text += ch;
  }
  if (word) out.push(word);
  return out;
}

const HOME = process.env.HOME || process.env.USERPROFILE || '';

// An absolute path for a shell word, or null when it holds a variable or command substitution.
function resolveWord(text, cwd) {
  if (!text || /[$`]|^%|%$/.test(text)) return null;
  const home = text === '~' || /^~[/\\]/.test(text) ? HOME + text.slice(1) : text;
  if (!cwd && !path.isAbsolute(normalizeTarget(home))) return null;
  return path.resolve(normalizeTarget(cwd || '/'), normalizeTarget(home));
}

const isDir = (dir) => {
  try {
    return fs.statSync(dir).isDirectory();
  } catch {
    return false;
  }
};

// The .env names in `dir`; an unreadable directory counts as holding one (a hook error would
// let the call through).
function envNamesIn(dir) {
  try {
    return fs.readdirSync(dir).filter(isEnvName);
  } catch {
    return ['.env'];
  }
}

// .env files under `root` (links not followed), or 'too large' past WALK_LIMIT entries.
function envFilesUnder(root) {
  const found = [];
  let seen = 0;
  const walk = (dir, depth) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return true;
    }
    for (const entry of entries) {
      seen += 1;
      if (seen > WALK_LIMIT) return false;
      if (entry.isFile() && isEnvName(entry.name)) found.push(path.join(dir, entry.name));
      if (entry.isDirectory() && !WALK_SKIP.has(entry.name) && depth < WALK_DEPTH) {
        if (!walk(path.join(dir, entry.name), depth + 1)) return false;
      }
    }
    return true;
  };
  return walk(root, 0) ? found : 'too large';
}

// Whether git (and so ripgrep, which honours .gitignore) leaves `file` out of a search.
function gitIgnored(file) {
  const result = spawnSync('git', ['-C', path.dirname(file), 'check-ignore', '-q', path.basename(file)], {
    timeout: 10000,
  });
  return result.status === 0;
}

// The reason a search over `roots` would read a .env file, or null. `ignored` skips the files
// git ignores; `keep` filters the file names the search would open.
function searchDenial(roots, { ignored = false, keep = () => true } = {}) {
  for (const root of roots) {
    if (!root) return `${ENV_REASON}；搜尋目錄含變數或無法解析，看不出會不會碰到 .env`;
    if (!isDir(root)) continue;
    const files = envFilesUnder(root);
    if (files === 'too large') return `${ENV_REASON}；${root} 太大，無法確認底下沒有 .env，請改搜較小的目錄`;
    const hit = files.find((file) => keep(path.basename(file)) && !(ignored && gitIgnored(file)));
    if (hit) return `${ENV_REASON}；${root} 底下有 ${hit}，遞迴搜尋或複製會讀到它`;
  }
  return null;
}

// Commands that read every file under a directory: [command regex, recursive flag regex or null
// when the command always recurses]. ripgrep skips hidden files such as .env unless told not to.
const RECURSIVE_READERS = [
  [/^(?:e|f|z)?grep$/i, /^(?:-[A-Za-z]*[rR][A-Za-z]*|--(?:dereference-)?recursive|--directories=recurse)$/],
  [/^(?:rg|ripgrep)$/i, /^(?:-[A-Za-z]*(?:u[A-Za-z]*u|\.)[A-Za-z]*|--hidden|--no-ignore[\w-]*)$/],
  [/^findstr$/i, /^\/s$/i],
  [/^(?:cp|Copy-Item|copy|cpi)$/i, /^(?:-[A-Za-z]*[rRa][A-Za-z]*|--recursive|--archive|-rec\w*)$/i],
  [/^(?:robocopy|xcopy|tar|zip|7z|Compress-Archive|rsync|scp)$/i, null],
];
// A recursive listing piped into a reader: `gci -Recurse | sls x`, `find . | xargs cat`.
const LISTERS = [
  [/^(?:Get-ChildItem|gci|ls|dir)$/i, /^-(?:r|rec\w*|s)$/i],
  [/^find$/i, null],
];
const PIPE_READERS = /^(?:Select-String|sls|Get-Content|gc|cat|type|Copy-Item|cpi|cp|xargs|ForEach-Object|%)$/i;
const COMPOSE_CONFIG = /(?:^|[\s(])(?:docker(?:\.exe)?\s+(?:compose|stack)|docker-compose)\b.*\s(?:config|convert)(?=\s|$)/i;
const CHDIR = /^(?:cd|pushd|Set-Location|sl|chdir)$/i;
const INTERPRETER = /^(?:python[\d.]*|py|node|deno|bun|bash|sh|zsh|pwsh|powershell|ruby|perl|php)(?:\.exe)?$/i;

// The reason one Bash/PowerShell segment reads or writes a .env file, or null. `ctx` carries the
// session cwd (null when a `cd` made it unknown) and whether a later segment reads piped input.
function envSegmentDenial(segment, shell, ctx) {
  const named = envMention(segment.raw);
  if (named) return `${ENV_REASON}（命令提到 ${named}）`;
  if (COMPOSE_CONFIG.test(segment.bare)) return `${ENV_REASON}；compose config 會把 .env 的值展開印出`;
  const list = words(segment.raw, shell).filter((w) => !/^[<>]|^\d?>/.test(w.text));
  const [head, ...args] = list.map((w) => w.text.replace(/^\(+/, ''));
  if (!head) return null;
  const matches = ([command, flag]) => command.test(head) && (!flag || args.some((a) => flag.test(a)));
  // A listing prints names, not contents: its globs matter only when its output is read on.
  const listing = LISTERS.some(([command]) => command.test(head));
  for (const word of listing && !ctx.piped ? [] : list.slice(1)) {
    if (!/[*?[]/.test(word.text) || /[$`{]/.test(word.text) || (shell === 'bash' && word.quoted)) continue;
    const glob = word.text.split(/[/\\]/).pop();
    const dir = resolveWord(word.text.slice(0, word.text.length - glob.length) || '.', ctx.cwd);
    const names = dir && isDir(dir) ? envNamesIn(dir) : ['.env', '.env.local'];
    const hit = names.find((name) => globMatches(glob, name, shell));
    if (hit) return `${ENV_REASON}（${word.text} 會展開到 ${hit}）`;
  }
  const roots = () => {
    const dirs = args.filter((a) => !a.startsWith('-')).map((a) => resolveWord(a, ctx.cwd));
    const existing = dirs.filter((d) => d === null || isDir(d));
    return existing.length ? existing : [ctx.cwd];
  };
  if (RECURSIVE_READERS.some(matches)) return searchDenial(roots());
  if (ctx.piped && LISTERS.some(matches)) return searchDenial(roots());
  return null;
}

// The reason a Bash/PowerShell command is blocked, or null. `cwd` is the session's directory.
function commandDenial(command, shell = 'bash', allow = ALLOW, cwd = process.cwd()) {
  const list = segments(command, shell);
  const ctx = { cwd: normalizeTarget(cwd), piped: false };
  // Heredoc and here-string bodies are dropped from segments; fed to an interpreter they are code.
  const script = list.find((s) => INTERPRETER.test(path.basename(normalizeTarget(words(s.raw, shell)[0]?.text || ''))));
  const inBody = script && !allow.some((re) => re.test(script.raw)) && envMention(command);
  if (inBody) return `擋下「${script.raw}」：${ENV_REASON}（交給直譯器的內容提到 ${inBody}）。真的需要時請使用者執行`;
  for (const [index, segment] of list.entries()) {
    if (allow.some((re) => re.test(segment.raw))) continue;
    for (const rule of RULES) {
      if (rule.test ? rule.test(segment) : rule.re.test(segment.bare)) {
        return (
          `擋下「${segment.raw}」：${rule.reason}。真的需要時請使用者執行，` +
          '或在 tools/ops/agent_guard.cjs 開頭的放行清單加一條（另開 PR）'
        );
      }
    }
    ctx.piped = list.slice(index + 1).some((later) => PIPE_READERS.test(words(later.raw, shell)[0]?.text || ''));
    const reason = envSegmentDenial(segment, shell, ctx);
    if (reason) return `擋下「${segment.raw}」：${reason}。真的需要時請使用者執行`;
    const [head, ...rest] = words(segment.raw, shell).map((w) => w.text);
    if (head && CHDIR.test(head)) {
      const target = rest.find((w) => !/^-\w/.test(w)) || '~';
      ctx.cwd = target === '-' ? null : resolveWord(target, ctx.cwd);
    }
  }
  return null;
}

// The reason a file tool's path is a .env file, or null; a link is judged by its target too.
function envFileDenial(file, cwd) {
  if (typeof file !== 'string' || !file) return null;
  const named = envMention(file);
  if (named) return `${file}：${ENV_REASON}`;
  try {
    const real = fs.realpathSync(path.resolve(normalizeTarget(cwd || process.cwd()), normalizeTarget(file)));
    if (isEnvName(path.basename(real))) return `${file} 連到 ${real}：${ENV_REASON}`;
  } catch {
    // not there yet: the name above is all there is to judge
  }
  return null;
}

// Grep is ripgrep with hidden files on and .gitignore honoured: a directory search reads every
// .env under it that git does not ignore, unless `glob` or `type` leaves it out.
function grepDenial(tool, cwd) {
  const named = envMention(tool.path) || envMention(tool.glob);
  if (named) return `${named}：${ENV_REASON}`;
  const base = normalizeTarget(cwd || process.cwd());
  const root = tool.path ? path.resolve(base, normalizeTarget(tool.path)) : base;
  if (!isDir(root)) return envFileDenial(tool.path, cwd);
  if (typeof tool.type === 'string' && tool.type && !/env/i.test(tool.type)) return null;
  const globs = typeof tool.glob === 'string' ? tool.glob.split(/\s+/).filter(Boolean) : [];
  const hits = (glob, name) => globMatches(glob.split('/').pop(), name, 'grep');
  const only = globs.filter((g) => !g.startsWith('!'));
  const not = globs.filter((g) => g.startsWith('!')).map((g) => g.slice(1));
  const keep = (name) => (!only.length || only.some((g) => hits(g, name))) && !not.some((g) => hits(g, name));
  return searchDenial([root], { ignored: true, keep });
}

// Every string in a tool input that names a .env file (MCP tools take paths under many keys).
function envInInput(value) {
  if (typeof value === 'string') return envMention(value);
  if (value && typeof value === 'object') {
    for (const item of Object.values(value)) {
      const named = envInInput(item);
      if (named) return named;
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
  const name = input.tool_name;
  switch (name) {
    case 'Edit':
    case 'Write':
      return envFileDenial(tool.file_path, input.cwd) || fileDenial(tool.file_path, input.cwd);
    case 'Read':
      return envFileDenial(tool.file_path, input.cwd);
    case 'NotebookEdit':
      return envFileDenial(tool.notebook_path, input.cwd);
    case 'Grep':
      return grepDenial(tool, input.cwd);
    case 'Glob': {
      const named = envMention(tool.pattern) || envMention(tool.path);
      return named ? `${named}：${ENV_REASON}` : null;
    }
    case 'Bash':
    case 'PowerShell':
      return typeof tool.command === 'string'
        ? commandDenial(tool.command, name === 'Bash' ? 'bash' : 'powershell', ALLOW, input.cwd || process.cwd())
        : null;
    default: {
      if (!/^mcp__codebase-memory/.test(name || '')) return null;
      const named = envInInput(tool);
      return named ? `${named}：${ENV_REASON}` : null;
    }
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

module.exports = { ALLOW, commandDenial, denial, envMention, normalizeTarget, segments };
