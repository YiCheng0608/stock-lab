#!/usr/bin/env node
// Claude Code PreToolUse hook (.claude/settings.json): blocks the tool calls AGENTS.md forbids.
// - Edit/Write: the target file's checkout is on branch master (the management checkout).
// - Bash/PowerShell: git clean -x/-X, bare git stash, git stash pop/clear, git push --force/-f/
//   --force-with-lease/+refspec, recursive rm of the data directory, docker compose down -v/--volumes
//   of a project not named as a test project with -p.
// - Every file tool, Bash/PowerShell/Monitor, Artifact uploads and codebase-memory: a .env file (`.env`, or `.env.*` not
//   ending in `.example`, in any directory). See ENV RULES below for what each check covers.
// Reads the hook JSON on stdin; exit 2 with the reason on stderr blocks the call, exit 0 allows
// it. Any other exit would be a hook error Claude Code shows without blocking, so this script
// exits 2 on its own errors and on malformed input as well. Rollback: revert
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
  {
    test: (segment, shell) => composeDownDenial(segment.raw, shell),
    reason:
      'docker compose down -v／--volumes 會刪掉 project 的 named volume（正式 project 的 stock-data 就是正式 DB）；' +
      '只放行以 -p 明寫的測試 project（t<n>、task-<n> 開頭，或含 smoke 一詞），例如 docker compose -p task-<issue> down --volumes',
  },
];

// Splits a command into segments at unquoted ; && || | & and newlines. `raw` keeps quoted text;
// `bare` replaces it with an empty quote pair so a rule only sees words the shell runs. Heredoc
// bodies and comments are dropped from both: they are input and notes, not commands.
function segments(command, shell = 'bash') {
  const out = [];
  let raw = '';
  let bare = '';
  let last = ''; // last character of `bare`: reading bare[bare.length - 1] flattens it, quadratic
  const heredocs = [];
  const add = (r, b = r) => {
    raw += r;
    bare += b;
    if (b) last = b[b.length - 1];
  };
  const flush = () => {
    if (raw.trim()) out.push({ raw: raw.trim(), bare: bare.trim() });
    raw = '';
    bare = '';
    last = '';
  };
  const escape = shell === 'powershell' ? '`' : '\\';
  let i = 0;
  while (i < command.length) {
    const ch = command[i];
    const rest = command.slice(i);
    if (ch === escape) {
      add(command.slice(i, i + 2));
      i += 2;
      continue;
    }
    const here = shell === 'powershell' && /^@(['"])\r?\n/.exec(rest);
    if (here) {
      const close = command.indexOf(`\n${here[1]}@`, i);
      const end = close < 0 ? command.length : close + 3;
      add(command.slice(i, end), '""');
      i = end;
      continue;
    }
    if (ch === "'" || ch === '"') {
      let j = i + 1;
      while (j < command.length && command[j] !== ch) j += ch === '"' && command[j] === escape ? 2 : 1;
      add(command.slice(i, j + 1), ch + ch);
      i = j + 1;
      continue;
    }
    const heredoc = shell === 'bash' && /^<<(-?)\s*(['"]?)([A-Za-z_][\w-]*)\2/.exec(rest);
    if (heredoc) {
      heredocs.push({ strip: heredoc[1] === '-', word: heredoc[3] });
      add('<<' + heredoc[3]);
      i += heredoc[0].length;
      continue;
    }
    if (ch === '#' && (last === '' || /\s/.test(last))) {
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
    add(ch);
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
// A walk for .env files under a search root gives up (and blocks) past these.
const WALK_DEPTH = 12;
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
// A glob that is no valid regex here ([z-a]) counts as a match: the shell may still expand it.
function globMatches(glob, name, shell) {
  if (shell === 'bash' && name.startsWith('.') && !glob.startsWith('.')) return false;
  try {
    return new RegExp(globRegex(glob), 'i').test(name);
  } catch {
    return true;
  }
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

// .env files under `root`, skipping the paths in `skip` and .git (links not followed); 'too
// large' past WALK_LIMIT entries or below WALK_DEPTH levels, where the walk cannot vouch.
function envFilesUnder(root, skip = new Set(), limit = WALK_LIMIT) {
  const found = [];
  let seen = 0;
  const walk = (dir, depth) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return true; // unreadable to the search too
    }
    for (const entry of entries) {
      seen += 1;
      if (seen > limit) return false;
      const full = path.join(dir, entry.name);
      if (skip.has(full)) continue;
      if (entry.isFile() && isEnvName(entry.name)) found.push(full);
      if (entry.isDirectory() && entry.name !== '.git') {
        if (depth >= WALK_DEPTH || !walk(full, depth + 1)) return false;
      }
    }
    return true;
  };
  return walk(root, 0) ? found : 'too large';
}

// The files and whole directories git ignores under `root`, which ripgrep (and so Grep) leaves
// out; empty outside a repository.
function gitIgnoredUnder(root) {
  const result = spawnSync('git', ['-C', root, 'ls-files', '-z', '--others', '--ignored', '--exclude-standard', '--directory'], {
    encoding: 'utf8',
    timeout: 10000,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.status !== 0) return new Set();
  return new Set(result.stdout.split('\0').filter(Boolean).map((p) => path.resolve(root, p.replace(/\/$/, ''))));
}

// The reason a search over `roots` would read a .env file, or null. `ignored` skips the paths
// git ignores; `keep` filters the file names the search would open.
function searchDenial(roots, { ignored = false, keep = () => true } = {}) {
  for (const root of roots) {
    if (!root) return `${ENV_REASON}；搜尋目錄含變數或無法解析，看不出會不會碰到 .env`;
    if (!isDir(root)) continue;
    const files = envFilesUnder(root, ignored ? gitIgnoredUnder(root) : undefined);
    if (files === 'too large') {
      return `${ENV_REASON}；${root} 超過 ${WALK_LIMIT} 個項目或 ${WALK_DEPTH} 層，無法確認底下沒有 .env，請改搜較小的目錄`;
    }
    const hit = files.find((file) => keep(path.basename(file)));
    if (hit) return `${ENV_REASON}；${root} 底下有 ${hit}，遞迴搜尋或複製會讀到它`;
  }
  return null;
}

// Commands that read every file under a directory: [command regex, recursive flag regex or null
// when the command always recurses, subcommand regex]. ripgrep skips hidden files such as .env
// unless told not to; git grep reads untracked and ignored files with --no-index/--untracked.
const RECURSIVE_READERS = [
  [/^(?:e|f|z)?grep$/i, /^(?:-[A-Za-z]*[rR][A-Za-z]*|--(?:dereference-)?recursive|--directories=recurse)$/],
  [/^(?:rg|ripgrep)$/i, /^(?:-[A-Za-z]*(?:u[A-Za-z]*u|\.)[A-Za-z]*|--hidden|--no-ignore[\w-]*)$/],
  [/^git$/i, /^--(?:no-index|untracked)$/, /^grep$/],
  [/^find$/i, /^-(?:exec|execdir|ok|okdir)$/],
  [/^(?:fd|fdfind)$/i, /^(?:-[A-Za-z]*[xX]|--exec(?:-batch)?)$/],
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
const CHDIR = /^(?:cd|pushd|Set-Location|sl|chdir)$/i;
const INTERPRETER = /^(?:python[\d.]*|py|node|deno|bun|bash|sh|zsh|pwsh|powershell|ruby|perl|php)(?:\.exe)?$/i;
// powershell -EncodedCommand (and its -e/-ec/-enc abbreviations, with -, -- or / in front)
// hides the script in base64; a quoted '-enc ...' passed on (Start-Process -ArgumentList) too.
const POWERSHELL = /^(?:pwsh|powershell)(?:\.exe)?$/i;
const ENCODED = /^(?:--?|\/)(?:e|ec|en\w*)(?=\s|$)/i;

// The target of `file` with links and 8.3 short names (ENV~1) resolved, or null.
function realName(file) {
  try {
    return fs.realpathSync.native(file);
  } catch {
    return null;
  }
}

// Docker commands that print a container's environment, where compose put the env file's values
// (#353, #360; OPERATIONS §1.2). Blocked: compose config/convert unless -q/--quiet,
// --no-interpolate or --services is written bare after config (not as the value of the option
// before it: `--profile -q`), with no -o/--output, --environment or --variables and no flag set
// with `=` that could turn one back off (`--quiet=false`); inspect of a container, image or
// service unless --format/-f reads no Env, no whole Config, not `.` and not `$`; run/exec whose
// command holds an env/printenv word or `environ`. Not covered: a variable echoed by name
// (`sh -c 'echo $TOKEN'`), other ways a program inside prints its environment.
const DOCKER = /^docker(?:-compose)?(?:\.exe)?$/i;
// docker and docker compose options before the subcommand that take a value.
const DOCKER_VALUE_OPTION = /^(?:-[cHlfp]|--(?:config|context|host|log-level|tlscacert|tlscert|tlskey|file|project-name|env-file|profile|project-directory|ansi|parallel|progress))$/;
// Words that name a group of subcommands: `docker compose config`, `docker container inspect`.
const DOCKER_GROUP = /^(?:compose|stack|container|image|service|network|volume|context|buildx|builder|plugin|node|secret|system)$/i;
const COMPOSE_SAFE = /^(?:-q|--quiet|--no-interpolate|--services)$/;
const COMPOSE_PRINTS = /^(?:-o|--output(?:=|$)|--environment$|--variables$)/;
// A safe flag given a value (--quiet=true), or any flag set to false the way pflag reads it.
const COMPOSE_FLAG_VALUE = /^(?:(?:-q|--quiet|--no-interpolate|--services)=|-[^=]*=(?:false|f|0)$)/i;
// compose config options that take a value: a safe flag right after one is that value.
const CONFIG_VALUE_OPTION = /^(?:-o|--(?:output|format|hash))$/;
// inspect of these shows no environment.
const INSPECT_SAFE_GROUP = /^(?:network|volume|context)$/i;
const ENV_WORD = /^(?:env|printenv)(?:\.exe)?$/i;

// The --format/-f value of an inspect, or null without one.
function inspectFormat(args) {
  for (const [i, arg] of args.entries()) {
    if (arg === '--format' || arg === '-f') return args[i + 1] ?? '';
    if (arg.startsWith('--format=')) return arg.slice('--format='.length);
    if (/^-f./.test(arg)) return arg.slice(2);
  }
  return null;
}

// A format that reads no environment: no Env field, no whole Config/ContainerConfig, no bare `.`
// and no `$` (the template's root object, as `.`; variables are blocked along with it).
const safeFormat = (format) =>
  Boolean(format) &&
  !/env/i.test(format) &&
  !format.includes('$') &&
  !/(?<!Host)Config\b(?!\.\w)/.test(format) &&
  !/(?:^|[\s({|])\.(?=\s*(?:$|[\s)}|]))/.test(format);

// Whether compose config with these words (compose's own, from after `compose`) prints nothing of
// the env file: a bare safe flag after config/convert that is not the value of the word before it,
// nothing that writes or lists values, and no flag set with `=` that may undo the safe one.
function quietConfig(rest) {
  if (rest.some((t) => COMPOSE_PRINTS.test(t) || COMPOSE_FLAG_VALUE.test(t))) return false;
  const at = rest.findIndex((t) => /^(?:config|convert)$/i.test(t));
  return rest.some(
    (t, j) => j > at && COMPOSE_SAFE.test(t) && !DOCKER_VALUE_OPTION.test(rest[j - 1]) && !CONFIG_VALUE_OPTION.test(rest[j - 1]),
  );
}

// A word without the ( $( @( or backtick that open a subshell or a command substitution, an
// assignment in front of one (`out=$(docker`), and the ) or backtick that close it (#341, PR #370
// review): `(docker compose down -v)` runs docker as much as the bare command does.
const unwrap = (text) => text.replace(/^(?:\w+=(?=[$@(`]))?(?:[$@]?\(|`)+/, '').replace(/[)`]+$/, '');

// The docker commands in `raw`, each as `sub` (the subcommand words, lowercased; `compose` first
// for docker-compose), `args` (the words after them) and `all` (every word after docker, options
// included). A quoted word that starts a command with docker (`sh -c "docker compose config"`)
// counts as a command too; one that only mentions docker (a commit message) does not. Words are
// taken as the shell runs them inside a subshell or a command substitution (unwrap).
function dockerCommands(raw, shell) {
  const texts = words(raw, shell).map((w) => unwrap(w.text));
  const found = [];
  for (const text of texts) {
    if (text !== raw && /\s/.test(text) && /docker/i.test(text)) {
      for (const inner of segments(text, shell)) {
        const first = words(inner.raw, shell)
          .map((w) => unwrap(w.text))
          .find((t) => !/^\w+=/.test(t));
        if (first && DOCKER.test(path.basename(normalizeTarget(first)))) found.push(...dockerCommands(inner.raw, shell));
      }
    }
  }
  const at = texts.findIndex((t) => DOCKER.test(path.basename(normalizeTarget(t))));
  if (at < 0) return found;
  const sub = /compose/i.test(path.basename(normalizeTarget(texts[at]))) ? ['compose'] : [];
  let i = at + 1;
  while (i < texts.length) {
    const text = texts[i];
    i += text.startsWith('-') && DOCKER_VALUE_OPTION.test(text) ? 2 : 1;
    if (text.startsWith('-')) continue;
    sub.push(text.toLowerCase());
    if (!DOCKER_GROUP.test(text)) break;
  }
  found.push({ sub, args: texts.slice(i), all: texts.slice(at + 1) });
  return found;
}

// The words after compose (or stack), subcommand included, or [] when it is not compose. Any word
// counts as the subcommand: an option this parser does not know (one that takes a value) must
// not hide it.
function composeWords({ sub, args }) {
  const compose = sub.findIndex((s) => s === 'compose' || s === 'stack');
  return compose < 0 ? [] : [...sub.slice(compose + 1), ...args];
}

// compose down that removes the project's named volumes: -v (alone or among short flags) or
// --volumes in any form, after `down` (#341). Allowed only when every -p/--project-name names a
// test project, by the rule of tools/compose/test_project.sh: production is stock-lab and
// STOCK_COMPOSE_PROJECT; a test project starts with t<n> or task-<n>, or has smoke as one of its
// words. Without -p compose takes the project from COMPOSE_PROJECT_NAME, the env file or the
// directory, which the hook cannot see, so that is blocked too.
const TEST_PROJECT = /^(?:t\d+|task-\d+)(?:[-_][a-z0-9_-]*)?$|^(?=[a-z0-9][a-z0-9_-]*$)(?:.*[-_])?smoke(?:[-_].*)?$/;
function downRemovesVolumes(command) {
  const rest = composeWords(command);
  const down = rest.findIndex((t) => /^down$/i.test(t));
  if (down < 0) return false;
  const volumes = rest.slice(down + 1).some((t) => /^--volumes(?:=|$)/i.test(t) || /^-(?!-)[A-Za-z]*v/.test(t));
  if (!volumes) return false;
  const projects = [];
  command.all.forEach((t, j) => {
    if (t === '-p' || t === '--project-name') projects.push(command.all[j + 1] ?? '');
    else if (t.startsWith('--project-name=')) projects.push(t.slice('--project-name='.length));
    else if (/^-p./.test(t)) projects.push(t.slice(2));
  });
  const production = process.env.STOCK_COMPOSE_PROJECT;
  return !projects.length || projects.some((p) => p === 'stock-lab' || p === production || !TEST_PROJECT.test(p));
}

const composeDownDenial = (raw, shell) => dockerCommands(raw, shell).some(downRemovesVolumes);

// The reason a docker command in `raw` prints environment values, or null.
function dockerDenial(raw, shell) {
  for (const command of dockerCommands(raw, shell)) {
    const reason = dockerEnvDenial(command);
    if (reason) return reason;
  }
  return null;
}

function dockerEnvDenial({ sub, args }) {
  const command = sub[sub.length - 1];
  const rest = composeWords({ sub, args });
  if (rest.some((t) => /^(?:config|convert)$/i.test(t))) {
    if (quietConfig(rest)) return null;
    return (
      `${ENV_REASON}；compose config 會把 env file 的值展開印出，只放行 config 後面直接寫 -q／--quiet、` +
      '--no-interpolate、--services（不加 -o／--output、--environment、--variables，也不寫 --quiet=false 這類帶 = 的旗標）'
    );
  }
  if (command === 'inspect' && !INSPECT_SAFE_GROUP.test(sub[sub.length - 2] || '')) {
    if (safeFormat(inspectFormat(args))) return null;
    return (
      `${ENV_REASON}；docker inspect 會印出容器的環境變數（env file 的值），` +
      "請加 --format 只取需要的欄位，例如 --format '{{.State.Status}}'（不取 Env、整個 .Config、. 或 $）"
    );
  }
  if (command === 'run' || command === 'exec') {
    const printer = args
      .flatMap((a) => a.split(/[\s;|&()`'"]+/))
      .find((t) => ENV_WORD.test(path.basename(normalizeTarget(t))) || /environ/i.test(t));
    if (printer) return `${ENV_REASON}；docker ${sub.join(' ')} 裡的 ${printer} 會印出容器的環境變數（env file 的值）`;
  }
  return null;
}

// The reason one Bash/PowerShell segment reads or writes a .env file, or null. `ctx` carries the
// session cwd (null when a `cd` made it unknown) and whether a later segment reads piped input.
function envSegmentDenial(segment, shell, ctx) {
  const named = envMention(segment.raw);
  if (named) return `${ENV_REASON}（命令提到 ${named}）`;
  const docker = dockerDenial(segment.raw, shell);
  if (docker) return docker;
  const list = words(segment.raw, shell).filter((w) => !/^[<>]|^\d?>/.test(w.text));
  const [head, ...args] = list.map((w) => w.text.replace(/^\(+/, ''));
  if (!head) return null;
  const texts = words(segment.raw, shell).map((w) => w.text.replace(/^\d*[<>]+&?/, ''));
  const shellAt = texts.findIndex((t) => POWERSHELL.test(path.basename(normalizeTarget(t))));
  if (shellAt >= 0 && texts.slice(shellAt + 1).some((t) => ENCODED.test(t))) {
    return `${ENV_REASON}；-EncodedCommand 的內容看不出會不會讀 .env，改用明文 -Command`;
  }
  for (const text of texts) {
    const file = resolveWord(text, ctx.cwd);
    const real = file && realName(file);
    if (real && isEnvName(path.basename(real))) return `${ENV_REASON}（${text} 就是 ${real}）`;
  }
  const matches = ([command, flag, sub]) =>
    command.test(head) && (!flag || args.some((a) => flag.test(a))) && (!sub || args.some((a) => sub.test(a)));
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

// Past these sizes the checks could outrun the hook timeout, and Claude Code runs a call whose
// hook timed out (checked by hand, #353): block instead. Heredoc bodies count only toward the
// first; they are dropped before the per-word checks.
const MAX_COMMAND = 5000000;
const MAX_CHECKED = 100000;
const TOO_LONG = '命令太長，hook 無法在逾時前檢查完；長內容請先用 Write 寫檔';

// The reason a Bash/PowerShell command is blocked, or null. `cwd` is the session's directory.
function commandDenial(command, shell = 'bash', allow = ALLOW, cwd = process.cwd()) {
  if (command.length > MAX_COMMAND) return `擋下：${TOO_LONG}（${command.length} 字元，上限 ${MAX_COMMAND}）`;
  const list = segments(command, shell);
  const checked = list.reduce((sum, s) => sum + s.raw.length, 0);
  if (checked > MAX_CHECKED) return `擋下：${TOO_LONG}（heredoc 以外 ${checked} 字元，上限 ${MAX_CHECKED}）`;
  const ctx = { cwd: normalizeTarget(cwd), piped: false };
  const heads = list.map((s) => words(s.raw, shell)[0]?.text || '');
  const lastReader = heads.findLastIndex((head) => PIPE_READERS.test(head));
  // Heredoc and here-string bodies are dropped from segments; fed to an interpreter they are code.
  const script = list.find((s, i) => INTERPRETER.test(path.basename(normalizeTarget(heads[i]))));
  const inBody = script && !allow.some((re) => re.test(script.raw)) && envMention(command);
  if (inBody) return `擋下「${script.raw}」：${ENV_REASON}（交給直譯器的內容提到 ${inBody}）。真的需要時請使用者執行`;
  for (const [index, segment] of list.entries()) {
    if (allow.some((re) => re.test(segment.raw))) continue;
    for (const rule of RULES) {
      if (rule.test ? rule.test(segment, shell) : rule.re.test(segment.bare)) {
        return (
          `擋下「${segment.raw}」：${rule.reason}。真的需要時請使用者執行，` +
          '或在 tools/ops/agent_guard.cjs 開頭的放行清單加一條（另開 PR）'
        );
      }
    }
    ctx.piped = index < lastReader;
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

// The reason a file tool's path is a .env file, or null; a link or short name is judged by the
// file it names.
function envFileDenial(file, cwd) {
  if (typeof file !== 'string' || !file) return null;
  const named = envMention(file);
  if (named) return `${file}：${ENV_REASON}`;
  try {
    // .native also expands 8.3 short names (ENV~1), which fs.realpathSync leaves as given.
    const real = fs.realpathSync.native(path.resolve(normalizeTarget(cwd || process.cwd()), normalizeTarget(file)));
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
  const compiles = (glob) => {
    try {
      return Boolean(new RegExp(globRegex(glob.replace(/^!/, '').split('/').pop())));
    } catch {
      return false;
    }
  };
  if (!globs.every(compiles)) return `${ENV_REASON}；glob ${tool.glob} 無法解析，看不出會不會搜到 .env`;
  const hits = (glob, name) => globMatches(glob.split('/').pop(), name, 'grep');
  const only = globs.filter((g) => !g.startsWith('!'));
  const not = globs.filter((g) => g.startsWith('!')).map((g) => g.slice(1));
  const keep = (name) => (!only.length || only.some((g) => hits(g, name))) && !not.some((g) => hits(g, name));
  return searchDenial([root], { ignored: true, keep });
}

// Upload and MCP tools take local paths under keys of their own, relative to the session cwd or
// to their `root`/`localDir`: every string is judged by name and, when it is an existing path,
// by the file it names (links, 8.3 short names). Too many strings block (hook timeout).
const MAX_STRINGS = 5000;
function uploadDenial(tool, cwd) {
  const strings = [];
  const collect = (value) => {
    if (typeof value === 'string') strings.push(value);
    else if (value && typeof value === 'object') Object.values(value).forEach(collect);
  };
  collect(tool);
  if (strings.length > MAX_STRINGS) return `${ENV_REASON}；輸入有 ${strings.length} 個字串，hook 無法在逾時前檢查完`;
  const base = normalizeTarget(cwd || process.cwd());
  const bases = [base, ...[tool.root, tool.localDir].filter((b) => typeof b === 'string' && b).map((b) => path.resolve(base, normalizeTarget(b)))];
  for (const text of strings) {
    const named = envMention(text);
    if (named) return `${named}：${ENV_REASON}`;
    if (!text || text.length > 1024 || /[\r\n\0]/.test(text)) continue;
    for (const dir of bases) {
      const real = realName(path.resolve(dir, normalizeTarget(text)));
      if (real && isEnvName(path.basename(real))) return `${text} 就是 ${real}：${ENV_REASON}`;
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

// Tool input fields this script reads as text. Any other type is malformed input, which blocks.
const TEXT_FIELDS = ['file_path', 'notebook_path', 'path', 'glob', 'type', 'pattern', 'command'];
// Tools that upload or read local files under keys of their own: every string is checked.
const UPLOADERS = /^(?:Artifact|ArtifactData|DesignSync|mcp__codebase-memory-mcp__.*)$/;

function denial(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new TypeError('hook input is not an object');
  const tool = input.tool_input ?? {};
  if (typeof tool !== 'object' || Array.isArray(tool)) throw new TypeError('tool_input is not an object');
  const name = input.tool_name;
  if (typeof name !== 'string') throw new TypeError('tool_name is not a string');
  if (input.cwd != null && typeof input.cwd !== 'string') throw new TypeError('cwd is not a string');
  if (!UPLOADERS.test(name)) {
    for (const field of TEXT_FIELDS) {
      if (tool[field] != null && typeof tool[field] !== 'string') throw new TypeError(`tool_input.${field} is not a string`);
    }
  }
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
    case 'Monitor': // runs its command in the Bash tool's shell
      return typeof tool.command === 'string'
        ? commandDenial(tool.command, name === 'PowerShell' ? 'powershell' : 'bash', ALLOW, input.cwd || process.cwd())
        : null;
    default: {
      return UPLOADERS.test(name) ? uploadDenial(tool, input.cwd) : null;
    }
  }
}

function main() {
  let reason;
  try {
    reason = denial(JSON.parse(fs.readFileSync(0, 'utf8')));
  } catch (error) {
    // Only exit 2 blocks: any other exit lets the call run unchecked, so an error blocks too.
    process.stderr.write(`agent_guard: hook error, call blocked: ${error.message}\n`);
    process.exit(2);
  }
  if (reason) {
    process.stderr.write(`agent_guard: ${reason}。\n`);
    process.exit(2);
  }
}

if (require.main === module) main();

module.exports = { ALLOW, commandDenial, denial, envFilesUnder, envMention, normalizeTarget, segments };
