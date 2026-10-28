// Tests for agent_guard.cjs: node --test tools/ops/agent_guard.test.cjs (CI repository job).
// Git repositories are created in a temporary directory removed after the run; no test writes
// into a real checkout or runs a blocked command.
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { after, before, describe, test } = require('node:test');

const { commandDenial, denial, normalizeTarget } = require('./agent_guard.cjs');

const SCRIPT = path.join(__dirname, 'agent_guard.cjs');
const ROOT = path.resolve(__dirname, '..', '..');
// Tools .claude/settings.json must route through this script; the .env rules need every one
// that reads, searches or writes a file.
const MATCHED_TOOLS = ['Bash', 'Edit', 'Glob', 'Grep', 'NotebookEdit', 'PowerShell', 'Read', 'Write'];

function hook(input, env = process.env) {
  const result = spawnSync(process.execPath, [SCRIPT], {
    input: typeof input === 'string' ? input : JSON.stringify(input),
    encoding: 'utf8',
    env,
  });
  return { code: result.status, stderr: result.stderr };
}

const bash = (command) => ({ tool_name: 'Bash', tool_input: { command } });

describe('Bash rules', () => {
  const blocked = {
    'git clean -x': ['git clean -fdx', 'git clean -xfd', 'git clean -dfx', 'git clean -fX', 'git -C ../x clean -f -x'],
    'bare git stash': ['git stash', 'git stash -u', 'git stash save wip', 'cd a && git stash'],
    'git stash pop': ['git stash pop', 'git stash pop stash@{0}'],
    'git stash clear': ['git stash clear'],
    'force push': [
      'git push --force',
      'git push -f origin x',
      'git push origin x --force-with-lease',
      'git push --force-with-lease=x:abc origin x',
      'git push origin +master',
      'git push -uf origin x',
    ],
    'data dir rm': [
      'rm -rf ~/stock-lab-data',
      'rm -r "C:/Users/me/stock-lab-data/logs"',
      'rm -fr "$STOCK_DATA_DIR"',
      'rm --recursive ${STOCK_DATA_DIR}/raw',
    ],
  };
  for (const [rule, commands] of Object.entries(blocked)) {
    test(`blocks ${rule}`, () => {
      for (const command of commands) assert.ok(commandDenial(command), command);
    });
  }

  test('allows the safe forms', () => {
    for (const command of [
      'git clean -n',
      'git clean -fd',
      'git stash push -u -m task-226',
      'git stash apply 0123abc',
      'git stash list --format="%H %gs"',
      'git stash drop stash@{1}',
      'git stash show -p stash@{0}',
      'git push -u origin task/226-pr-gate',
      'git push origin HEAD --follow-tags',
      'rm -rf build',
      'rm ~/stock-lab-data/logs/handoff-x.json',
      'git status',
    ]) {
      assert.equal(commandDenial(command), null, command);
    }
  });

  test('ignores quoted text, heredoc bodies and comments', () => {
    for (const command of [
      'grep -n "git stash" docs/GITHUB_WORKFLOW.md',
      "git commit -m 'Block git clean -fdx and git push --force'",
      'gh issue comment 1 --body "do not run git stash clear; use push"',
      'cat > note.md <<\'EOF\'\ngit stash\ngit clean -fdx\nEOF\ngit status',
      'cat <<-EOF\n\tgit stash pop\n\tEOF',
      'git status # never git stash here',
    ]) {
      assert.equal(commandDenial(command), null, command);
    }
    assert.ok(commandDenial('cat <<EOF\nx\nEOF\ngit stash clear'), 'command after the heredoc');
  });

  test('checks every segment', () => {
    assert.ok(commandDenial('git status; git stash'));
    assert.ok(commandDenial('git fetch || git push -f'));
    assert.ok(commandDenial('ls\ngit clean -xdf'));
  });

  test('PowerShell quoting', () => {
    assert.ok(commandDenial('git stash clear', 'powershell'));
    assert.ok(commandDenial('Remove-Item -Recurse -Force "$env:STOCK_DATA_DIR\\raw"', 'powershell'));
    assert.equal(commandDenial('Remove-Item -Force C:\\Users\\me\\stock-lab-data\\x.json', 'powershell'), null);
    assert.equal(commandDenial("git commit -m @'\ngit stash 'x'\n'@", 'powershell'), null);
    assert.equal(commandDenial('Write-Output "a `"git stash`" b"', 'powershell'), null);
  });

  test('the allow list overrides the rules for a matching segment only', () => {
    const allow = [/^git push --force-with-lease origin task\/\S+$/];
    assert.equal(commandDenial('git push --force-with-lease origin task/1-x', 'bash', allow), null);
    assert.ok(commandDenial('git push --force origin task/1-x', 'bash', allow));
    assert.ok(commandDenial('git push --force-with-lease origin task/1-x; git stash', 'bash', allow));
  });
});

describe('path forms', () => {
  test('C:\\, C:/ and /c/ are the same file on Windows', () => {
    for (const form of ['C:\\Users\\me\\repo\\a.md', 'C:/Users/me/repo/a.md', '/c/Users/me/repo/a.md', 'c:\\Users\\me\\repo\\a.md']) {
      assert.equal(normalizeTarget(form, 'win32'), 'C:/Users/me/repo/a.md', form);
    }
    assert.equal(normalizeTarget('/cygdrive/c/x', 'win32'), 'C:/x');
    assert.equal(normalizeTarget('/c', 'win32'), 'C:');
  });

  test('POSIX paths stay as given elsewhere', () => {
    assert.equal(normalizeTarget('/c/Users/me/a.md', 'linux'), '/c/Users/me/a.md');
  });
});

describe('hook process', () => {
  let tmp;
  let master;
  let task;
  let detached;
  const env = process.env;
  const git = (cwd, ...args) => {
    const result = spawnSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', ...args], { cwd, env, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
  };

  before(() => {
    tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'guard-')));
    master = path.join(tmp, 'master');
    task = path.join(tmp, 'task');
    detached = path.join(tmp, 'detached');
    for (const dir of [master, task, detached]) {
      fs.mkdirSync(dir);
      git(dir, 'init', '-q', '-b', 'master');
    }
    git(task, 'checkout', '-q', '-b', 'task/1-x');
    git(detached, 'commit', '-q', '--allow-empty', '-m', 'x');
    git(detached, 'checkout', '-q', '--detach');
    fs.writeFileSync(path.join(master, 'README.md'), 'x\n');
  });

  after(() => fs.rmSync(tmp, { recursive: true, force: true }));

  const write = (file) => ({ tool_name: 'Write', tool_input: { file_path: file, content: 'x' } });
  const edit = (file) => ({ tool_name: 'Edit', tool_input: { file_path: file, old_string: 'x', new_string: 'y' } });

  test('Write or Edit into a master checkout exits 2 with the reason', () => {
    for (const input of [
      write(path.join(master, 'README.md')),
      edit(path.join(master, 'README.md')),
      write(path.join(master, 'not', 'yet', 'there.md')),
      write(path.join(master, '.git', 'config')),
    ]) {
      const result = hook(input, env);
      assert.equal(result.code, 2, input.tool_input.file_path);
      assert.match(result.stderr, /在 worktree 改檔/);
    }
  });

  test('every path form of a master checkout is blocked on Windows', { skip: process.platform !== 'win32' }, () => {
    const forward = master.replace(/\\/g, '/');
    const gitBash = forward.replace(/^([A-Za-z]):/, (_, d) => `/${d.toLowerCase()}`);
    for (const form of [master, forward, gitBash]) {
      assert.equal(hook(write(`${form}${form === master ? '\\' : '/'}a.md`), env).code, 2, form);
    }
  });

  test('Write elsewhere exits 0', () => {
    for (const file of [
      path.join(task, 'a.md'),
      path.join(task, 'new', 'dir', 'a.md'),
      path.join(detached, 'a.md'),
      path.join(tmp, 'plain', 'a.md'),
    ]) {
      const result = hook(write(file), env);
      assert.equal(result.code, 0, `${file}: ${result.stderr}`);
    }
  });

  test('a relative path resolves against the session cwd', () => {
    assert.equal(hook({ ...write('README.md'), cwd: master }, env).code, 2);
    assert.equal(hook({ ...write('README.md'), cwd: task }, env).code, 0);
  });

  test('Bash: allowed 0, blocked 2 with the reason', () => {
    assert.equal(hook(bash('git stash push -u -m x')).code, 0);
    assert.equal(hook(bash('git stash apply 0123abc')).code, 0);
    for (const command of ['git stash', 'git clean -fdx', 'git stash clear']) {
      const result = hook(bash(command));
      assert.equal(result.code, 2, command);
      assert.match(result.stderr, /^agent_guard: 擋下/);
    }
    assert.equal(hook({ tool_name: 'PowerShell', tool_input: { command: 'git stash pop' } }).code, 2);
  });

  test('other tools pass and broken input is a non-blocking error', () => {
    assert.equal(hook({ tool_name: 'Read', tool_input: { file_path: path.join(master, 'README.md') } }, env).code, 0);
    const broken = hook('not json');
    assert.equal(broken.code, 1);
    assert.match(broken.stderr, /hook error/);
  });

  test('.claude/settings.json runs this script for every matched tool', { skip: process.platform === 'win32' && 'Git Bash vs WSL bash on PATH; checked by hand' }, () => {
    const settings = JSON.parse(fs.readFileSync(path.join(ROOT, '.claude', 'settings.json'), 'utf8'));
    const [entry] = settings.hooks.PreToolUse;
    assert.deepEqual(entry.matcher.split('|').sort(), [...MATCHED_TOOLS, 'mcp__codebase-memory-mcp__.*'].sort());
    const [{ command }] = entry.hooks;
    const run = (input) =>
      spawnSync('bash', ['-c', command], { input: JSON.stringify(input), env: { ...env, CLAUDE_PROJECT_DIR: ROOT }, encoding: 'utf8' });
    assert.equal(run(bash('git stash clear')).status, 2);
    assert.equal(run(bash('git status')).status, 0);
    assert.equal(run(write(path.join(master, 'README.md'))).status, 2);
  });
});

// .env files: every fixture is a fake file in a temporary directory; no test opens a real .env.
describe('.env rules', () => {
  const NAMED = ['.env', 'frontend/.env.local', 'C:/Users/YiCheng/stock-lab-release/.env'];
  const EXAMPLES = ['.env.example', 'frontend/.env.local.example', 'C:/Users/YiCheng/stock-lab-release/.env.example'];
  let tmp;
  let plain; // not a repository: .env, .env.example and sub/.env.local
  let repo; // a repository whose .gitignore leaves out .env
  let clean; // only .env.example
  const fake = (file) => {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, 'FAKE_TOKEN=not-a-real-token\n');
  };

  before(() => {
    tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'guard-env-')));
    plain = path.join(tmp, 'plain');
    repo = path.join(tmp, 'repo');
    clean = path.join(tmp, 'clean');
    for (const file of ['.env', '.env.example', path.join('sub', '.env.local')]) fake(path.join(plain, file));
    fake(path.join(repo, '.env'));
    fs.writeFileSync(path.join(repo, '.gitignore'), '.env\n.env.*\n!.env.example\n');
    assert.equal(spawnSync('git', ['init', '-q', repo]).status, 0);
    fake(path.join(clean, '.env.example'));
    fs.writeFileSync(path.join(clean, 'a.py'), 'x = 1\n');
  });

  after(() => fs.rmSync(tmp, { recursive: true, force: true }));

  const blocked = (input) => {
    const reason = denial(input);
    assert.ok(reason, JSON.stringify(input));
    assert.match(reason, /\.env/);
  };
  const allowed = (input) => assert.equal(denial(input), null, JSON.stringify(input));
  const unix = (dir) => dir.replace(/\\/g, '/'); // bash takes a backslash as an escape

  test('Read, Edit, Write and NotebookEdit block a .env file and pass .env.example', () => {
    const forms = [...NAMED, 'C:\\Users\\YiCheng\\stock-lab-release\\.env', '/c/Users/YiCheng/stock-lab-release/.env', '.env.production', '.ENV'];
    for (const file of forms) {
      blocked({ tool_name: 'Read', tool_input: { file_path: file }, cwd: clean });
      blocked({ tool_name: 'Edit', tool_input: { file_path: file, old_string: 'a', new_string: 'b' }, cwd: clean });
      blocked({ tool_name: 'Write', tool_input: { file_path: file, content: 'x' }, cwd: clean });
      blocked({ tool_name: 'NotebookEdit', tool_input: { notebook_path: file, new_source: 'x' }, cwd: clean });
    }
    for (const file of [...EXAMPLES, 'process.env.ts', '.envrc', 'docs/env.md']) {
      allowed({ tool_name: 'Read', tool_input: { file_path: file }, cwd: clean });
      allowed({ tool_name: 'Write', tool_input: { file_path: path.join(clean, file), content: 'x' }, cwd: clean });
    }
  });

  test('Read through a link to a .env file is blocked', (t) => {
    const link = path.join(tmp, 'notes.txt');
    try {
      fs.symlinkSync(path.join(plain, '.env'), link);
    } catch {
      t.skip('no symlink permission');
      return;
    }
    blocked({ tool_name: 'Read', tool_input: { file_path: link } });
  });

  test('Grep blocks a .env path or glob and a directory whose .env it would read', () => {
    for (const file of NAMED) blocked({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: file }, cwd: clean });
    blocked({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: clean, glob: '.env*' } });
    blocked({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: plain } });
    blocked({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: path.join(plain, 'sub') } });
    blocked({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN' }, cwd: plain });
    blocked({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: plain, glob: '*' } });
  });

  test('Grep passes a search that leaves every .env out', () => {
    allowed({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: path.join(clean, '.env.example') } });
    allowed({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: clean } });
    allowed({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: repo } }); // .gitignore'd: ripgrep skips it
    allowed({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: plain, glob: '*.py' } });
    allowed({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: plain, glob: '!.env*' } });
    allowed({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: plain, type: 'py' } });
  });

  test('Glob blocks a .env pattern or path', () => {
    for (const pattern of ['**/.env', '.env.*', '**/.env*', 'frontend/.env.local']) blocked({ tool_name: 'Glob', tool_input: { pattern } });
    blocked({ tool_name: 'Glob', tool_input: { pattern: '*', path: 'C:/Users/YiCheng/stock-lab-release/.env' } });
    for (const pattern of ['**/*.py', '**/.env.example', '**/*']) allowed({ tool_name: 'Glob', tool_input: { pattern } });
  });

  test('codebase-memory tools block a .env path; other MCP tools are not checked', () => {
    blocked({ tool_name: 'mcp__codebase-memory-mcp__get_code_snippet', tool_input: { qualified_name: 'frontend/.env.local' } });
    blocked({ tool_name: 'mcp__codebase-memory-mcp__search_code', tool_input: { pattern: 'TOKEN', file_pattern: '.env' } });
    allowed({ tool_name: 'mcp__codebase-memory-mcp__search_code', tool_input: { pattern: 'env_file', file_pattern: '*.yml' } });
    allowed({ tool_name: 'mcp__claude_ai_Claude_Docs__update', tool_input: { payload: 'copy .env.example to .env' } });
  });

  // One entry per way a shell reads or writes a file; {f} is each of NAMED.
  const READS = {
    cat: ['bash', 'cat {f}'],
    type: ['powershell', 'type {f}'],
    'Get-Content': ['powershell', 'Get-Content -Raw "{f}"'],
    less: ['bash', 'less {f}'],
    head: ['bash', 'head -n 5 {f}'],
    tail: ['bash', 'tail {f}'],
    grep: ['bash', 'grep TOKEN {f}'],
    rg: ['bash', 'rg -n TOKEN "{f}"'],
    'Select-String': ['powershell', "Select-String -Path '{f}' -Pattern TOKEN"],
    cp: ['bash', 'cp {f} /tmp/x'],
    'Copy-Item': ['powershell', 'Copy-Item {f} $env:TEMP\\x'],
    source: ['bash', 'source {f}'],
    'dot source': ['bash', '. {f}'],
    python: ['bash', `python -c "print(open('{f}').read())"`],
    'python heredoc': ['bash', 'python - <<EOF\nprint(open("{f}").read())\nEOF'],
    'docker cp': ['bash', 'docker cp {f} app:/app/x'],
    'input redirect': ['bash', 'wc -c < {f}'],
    'output redirect': ['bash', 'echo FAKE >> {f}'],
    rm: ['bash', 'rm -f {f}'],
  };
  for (const [method, [shell, template]] of Object.entries(READS)) {
    test(`Bash/PowerShell: ${method} of a .env path is blocked, of .env.example passes`, () => {
      for (const file of NAMED) assert.ok(commandDenial(template.replaceAll('{f}', file), shell, [], clean), `${method} ${file}`);
      for (const file of EXAMPLES) assert.equal(commandDenial(template.replaceAll('{f}', file), shell, [], clean), null, `${method} ${file}`);
    });
  }

  test('Bash/PowerShell: docker compose config is blocked', () => {
    for (const command of ['docker compose config', 'docker compose -f compose.yml config --services', 'docker-compose config', 'docker compose convert']) {
      assert.ok(commandDenial(command, 'bash', [], clean), command);
    }
    assert.equal(commandDenial('docker compose ps', 'bash', [], clean), null);
  });

  test('Bash/PowerShell: a glob that expands to a .env file is blocked', () => {
    assert.ok(commandDenial('cat .*', 'bash', [], plain));
    assert.ok(commandDenial('cat .e?v', 'bash', [], plain));
    assert.ok(commandDenial(`cat ${unix(plain)}/.[e]*`, 'bash', [], clean));
    assert.ok(commandDenial('Get-Content *', 'powershell', [], plain));
    assert.ok(commandDenial('ls -a .* | xargs cat', 'bash', [], plain));
    assert.equal(commandDenial('cat *', 'bash', [], plain), null, 'bash * skips dot files');
    assert.equal(commandDenial('cat .*', 'bash', [], clean), null, 'nothing to expand to');
    assert.equal(commandDenial('ls -a .*', 'bash', [], plain), null, 'names only');
  });

  test('Bash/PowerShell: a recursive read of a directory holding a .env file is blocked', () => {
    for (const [shell, command] of [
      ['bash', `grep -rn TOKEN ${unix(plain)}`],
      ['bash', `grep -R TOKEN "${unix(path.join(plain, 'sub'))}"`],
      ['bash', 'grep -rn TOKEN .'],
      ['bash', `cd ${unix(plain)} && grep -r TOKEN`],
      ['bash', `rg --hidden TOKEN ${unix(plain)}`],
      ['bash', `rg -uu TOKEN ${unix(plain)}`],
      ['bash', `cp -r ${unix(plain)} /tmp/copy`],
      ['bash', `tar czf x.tgz ${unix(plain)}`],
      ['bash', `find ${unix(plain)} -type f | xargs cat`],
      ['powershell', `Get-ChildItem -Recurse ${plain} | Select-String TOKEN`],
      ['powershell', `Copy-Item -Recurse ${plain} C:\\x`],
      ['powershell', `findstr /s TOKEN ${plain}\\*`],
    ]) {
      assert.ok(commandDenial(command, shell, [], plain), command);
    }
    assert.ok(commandDenial('cd "$SOMEWHERE" && grep -rn TOKEN .', 'bash', [], clean), 'unknown directory');
    for (const [shell, command] of [
      ['bash', `grep -rn TOKEN ${unix(clean)}`],
      ['bash', `rg TOKEN ${unix(plain)}`], // ripgrep skips hidden files
      ['bash', `cp -r ${unix(clean)} /tmp/copy`],
      ['bash', `ls -R ${unix(plain)}`],
      ['powershell', `Get-ChildItem -Recurse ${plain}`],
      ['bash', `cd ${unix(clean)} && grep -rn TOKEN .`],
    ]) {
      assert.equal(commandDenial(command, shell, [], plain), null, command);
    }
  });

  test('Bash/PowerShell: commands that only look like .env pass', () => {
    for (const [shell, command] of [
      ['bash', 'node -e "console.log(process.env.HOME)"'],
      ['powershell', 'Write-Output $env:PATH'],
      ['bash', 'cat .envrc'],
      ['bash', 'cp .env.example /tmp/x'],
      ['bash', "cat > note.md <<'EOF'\ncopy .env.example to .env\nEOF"],
      ['bash', 'git status'],
    ]) {
      assert.equal(commandDenial(command, shell, [], clean), null, command);
    }
  });

  test('the hook process exits 2 on Read and cat of a fake .env file', () => {
    const file = path.join(plain, '.env');
    for (const input of [
      { tool_name: 'Read', tool_input: { file_path: file } },
      { tool_name: 'Bash', tool_input: { command: `cat "${file}"` } },
      { tool_name: 'PowerShell', tool_input: { command: `Get-Content '${file}'` } },
      { tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: plain } },
    ]) {
      const result = hook(input);
      assert.equal(result.code, 2, input.tool_name);
      assert.match(result.stderr, /^agent_guard: .*\.env/);
      assert.doesNotMatch(result.stderr, /not-a-real-token/);
    }
    assert.equal(hook({ tool_name: 'Read', tool_input: { file_path: path.join(plain, '.env.example') } }).code, 0);
  });

  test('.claude/settings.json routes every file-reading tool to this script', () => {
    const settings = JSON.parse(fs.readFileSync(path.join(ROOT, '.claude', 'settings.json'), 'utf8'));
    const matcher = new RegExp(`^(?:${settings.hooks.PreToolUse[0].matcher})$`);
    for (const tool of [...MATCHED_TOOLS, 'mcp__codebase-memory-mcp__search_code', 'mcp__codebase-memory-mcp__get_code_snippet']) {
      assert.ok(matcher.test(tool), tool);
    }
  });
});
