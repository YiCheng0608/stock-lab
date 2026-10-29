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

const { commandDenial, denial, envFilesUnder, normalizeTarget, segments } = require('./agent_guard.cjs');

const SCRIPT = path.join(__dirname, 'agent_guard.cjs');
const ROOT = path.resolve(__dirname, '..', '..');
// Tools .claude/settings.json must route through this script; the .env rules need every one
// that reads, searches or writes a file.
const MATCHED_TOOLS = ['Artifact', 'ArtifactData', 'Bash', 'DesignSync', 'Edit', 'Glob', 'Grep', 'Monitor', 'NotebookEdit', 'PowerShell', 'Read', 'Write'];

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

  test('other tools pass and broken input blocks the call', () => {
    assert.equal(hook({ tool_name: 'Read', tool_input: { file_path: path.join(master, 'README.md') } }, env).code, 0);
    const broken = hook('not json');
    assert.equal(broken.code, 2);
    assert.match(broken.stderr, /hook error, call blocked/);
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

  test('a hook error or malformed input blocks the call', () => {
    for (const [label, input] of [
      ['glob that is no valid regex', { tool_name: 'Bash', tool_input: { command: 'cat .[z-a] .e?v' }, cwd: plain }],
      ['Grep glob that is no valid regex', { tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: plain, glob: '![z-a]' } }],
      ['Grep path of the wrong type', { tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: 42 } }],
      ['stdin that is not JSON', 'not json'],
      ['tool_input that is not an object', { tool_name: 'Read', tool_input: 'x' }],
      ['Read file_path of the wrong type', { tool_name: 'Read', tool_input: { file_path: 42 } }],
      ['JSON null', 'null'],
      ['JSON array', '[]'],
      ['tool_input that is an array', { tool_name: 'Read', tool_input: [] }],
      ['tool_name that is not a string', { tool_name: 5, tool_input: {} }],
      ['cwd that is not a string', { tool_name: 'Read', tool_input: { file_path: 'a.md' }, cwd: 5 }],
    ]) {
      const result = hook(input);
      assert.equal(result.code, 2, label);
      assert.doesNotMatch(result.stderr, /not-a-real-token/, label);
    }
    assert.ok(commandDenial('cat .[z-a] .e?v', 'bash', [], plain));
    assert.ok(commandDenial('cat .[z-a]', 'bash', [], plain), 'a glob that does not compile counts as a match');
  });

  test('Monitor runs its command through the Bash rules', () => {
    blocked({ tool_name: 'Monitor', tool_input: { command: 'tail -f frontend/.env.local', description: 'x', timeout_ms: 1000 } });
    blocked({ tool_name: 'Monitor', tool_input: { command: 'grep -r TOKEN .', description: 'x', timeout_ms: 1000 }, cwd: plain });
    assert.match(denial({ tool_name: 'Monitor', tool_input: { command: 'git stash', description: 'x', timeout_ms: 1000 } }), /裸 git stash/);
    allowed({ tool_name: 'Monitor', tool_input: { command: 'tail -f run.log', description: '.env check', timeout_ms: 1000 }, cwd: clean });
    allowed({ tool_name: 'Monitor', tool_input: { ws: { url: 'wss://example.com/x' }, description: 'x', timeout_ms: 1000 } });
  });

  test('Artifact, ArtifactData and DesignSync block an upload of a .env file', () => {
    const url = 'https://claude.ai/artifact/x';
    blocked({ tool_name: 'Artifact', tool_input: { url, asset: true, file_path: 'C:/Users/YiCheng/stock-lab-release/.env' } });
    blocked({ tool_name: 'Artifact', tool_input: { url, asset: true, file_paths: ['a.png', '.env'] } });
    blocked({ tool_name: 'Artifact', tool_input: { file_path: 'page.html', files: { 'notes.txt': 'frontend/.env.local' } } });
    blocked({ tool_name: 'Artifact', tool_input: { file_path: 'page.html', files: { 'notes.txt': { from: '.env.production' } } } });
    blocked({ tool_name: 'ArtifactData', tool_input: { url, action: 'set', collection: 'c', doc_id: 'd', file_path: '.env' } });
    blocked({ tool_name: 'DesignSync', tool_input: { method: 'write_files', files: [{ path: 'a', localPath: '.env' }] } });
    allowed({ tool_name: 'Artifact', tool_input: { file_path: 'page.html', files: { 'a.js': 'a.js' }, description: 'x' } });
    allowed({ tool_name: 'ArtifactData', tool_input: { url, action: 'get', collection: 'c', doc_id: 'd' } });
  });

  // Aliases of plain/.env: its 8.3 short name (Windows) and a link (where links can be made).
  test('uploads through a short name or a link to a .env file are blocked', (t) => {
    const aliases = [];
    const short = shortName(path.join(plain, '.env'));
    if (short) aliases.push(short);
    const link = path.join(tmp, 'upload-link.txt');
    try {
      fs.symlinkSync(path.join(plain, '.env'), link);
      aliases.push(link);
    } catch {
      // no symlink permission (Windows without developer mode)
    }
    if (!aliases.length) {
      t.skip('neither 8.3 names nor symlinks here');
      return;
    }
    const url = 'https://claude.ai/artifact/x';
    for (const alias of aliases) {
      const name = path.basename(alias);
      blocked({ tool_name: 'Artifact', tool_input: { url, asset: true, file_path: alias } });
      blocked({ tool_name: 'Artifact', tool_input: { file_path: 'page.html', root: path.dirname(alias), files: { 'n.txt': name } } });
      blocked({ tool_name: 'ArtifactData', tool_input: { url, action: 'set', collection: 'c', doc_id: 'd', file_path: name }, cwd: path.dirname(alias) });
      blocked({ tool_name: 'DesignSync', tool_input: { method: 'write_files', localDir: path.dirname(alias), files: [{ path: 'a', localPath: name }] } });
    }
    allowed({ tool_name: 'Artifact', tool_input: { url, asset: true, file_path: path.join(clean, 'a.py') } });
  });

  // The 8.3 short name of `file` (Windows), or null when the volume has none.
  const shortName = (file) => {
    if (process.platform !== 'win32') return null;
    const result = spawnSync('cmd.exe', ['/d', '/s', '/c', `"for %I in ("${file}") do @echo %~sI"`], {
      encoding: 'utf8',
      windowsVerbatimArguments: true,
    });
    const short = result.stdout.trim();
    return result.status === 0 && short && path.basename(short) !== path.basename(file) ? short : null;
  };

  test('a short 8.3 name of a .env file is blocked', { skip: process.platform !== 'win32' && 'Windows only' }, (t) => {
    const short = shortName(path.join(plain, '.env'));
    if (!short) {
      t.skip('8.3 names are off on this volume');
      return;
    }
    blocked({ tool_name: 'Read', tool_input: { file_path: short } });
    blocked({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: short } });
    assert.ok(commandDenial(`cat ${path.basename(short)}`, 'bash', [], plain), short);
  });

  test('git grep over untracked files and find -exec are recursive reads', () => {
    assert.ok(commandDenial('git grep --no-index TOKEN', 'bash', [], repo));
    assert.ok(commandDenial(`git -C ${unix(repo)} grep --untracked TOKEN`, 'bash', [], clean));
    assert.ok(commandDenial('find . -type f -exec cat {} +', 'bash', [], plain));
    assert.ok(commandDenial('find . -name "*.txt" -execdir grep TOKEN {} ;', 'bash', [], plain));
    assert.equal(commandDenial('git grep TOKEN', 'bash', [], repo), null, 'tracked files only');
    assert.equal(commandDenial('find . -type f -exec cat {} +', 'bash', [], clean), null);
    assert.equal(commandDenial('git diff --no-index a.txt b.txt', 'bash', [], repo), null, 'not git grep');
  });

  test('fd -x/-X/--exec are recursive reads', () => {
    for (const command of ['fd -H -x cat', 'fd -HX cat', 'fd --exec cat', 'fd -t f --exec-batch grep TOKEN']) {
      assert.ok(commandDenial(command, 'bash', [], plain), command);
    }
    assert.equal(commandDenial('fd -H -x cat', 'bash', [], clean), null);
    assert.equal(commandDenial('fd -e py', 'bash', [], plain), null, 'names only');
  });

  test('a Grep walk that cannot finish blocks; node_modules counts unless git ignores it', () => {
    const deep = path.join(tmp, 'deep');
    fs.mkdirSync(path.join(deep, ...Array.from({ length: 14 }, (_, i) => `d${i}`)), { recursive: true });
    blocked({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: deep } });
    const modules = path.join(tmp, 'modules');
    fake(path.join(modules, 'node_modules', 'pkg', '.env'));
    blocked({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: modules } });
    for (let i = 0; i < 6; i += 1) fs.writeFileSync(path.join(clean, `f${i}.txt`), 'x\n');
    assert.equal(envFilesUnder(clean, undefined, 5), 'too large', 'past the entry limit');
    assert.deepEqual(envFilesUnder(clean, undefined, 50), [], 'under the entry limit');
    fake(path.join(repo, 'node_modules', 'pkg', '.env'));
    fs.appendFileSync(path.join(repo, '.gitignore'), 'node_modules/\n');
    allowed({ tool_name: 'Grep', tool_input: { pattern: 'TOKEN', path: repo } });
  });

  test('powershell -EncodedCommand is blocked', () => {
    for (const [shell, command] of [
      ['powershell', 'powershell -enc SQBFAFgA'],
      ['bash', 'pwsh -NoProfile -EncodedCommand SQBFAFgA'],
      ['bash', 'powershell.exe -e SQBFAFgA'],
      ['powershell', 'pwsh -ec SQBFAFgA'],
      ['powershell', 'powershell /enc SQBFAFgA'],
      ['bash', 'pwsh --EncodedCommand SQBFAFgA'],
      ['powershell', "Start-Process powershell -ArgumentList '-enc SQBFAFgA'"],
    ]) {
      assert.ok(commandDenial(command, shell, [], clean), command);
    }
    assert.equal(commandDenial('powershell -NoProfile -ExecutionPolicy Bypass -File x.ps1', 'bash', [], clean), null);
  });

  // Claude Code runs a call whose hook timed out, so the checks must finish well inside it.
  test('long commands finish fast: no quadratic scan, and the size caps block', () => {
    const start = Date.now();
    segments(`echo ${'a#'.repeat(100000)}`);
    assert.ok(Date.now() - start < 1500, `segments of 200k a#: ${Date.now() - start} ms`);
    for (const command of [`echo ${'a#'.repeat(100000)}`, 'true; '.repeat(100000), `echo ${'x'.repeat(6000000)}`]) {
      const t0 = Date.now();
      assert.match(commandDenial(command, 'bash', [], clean), /命令太長/);
      assert.ok(Date.now() - t0 < 3000, `${command.length} chars: ${Date.now() - t0} ms`);
    }
    const heredoc = "cat > a.txt <<'EOF'\n" + 'line of text\n'.repeat(80000) + 'EOF';
    assert.equal(commandDenial(heredoc, 'bash', [], clean), null, 'a long heredoc body is not checked word by word');
    const huge = "cat > a.txt <<'EOF'\n" + 'l\n'.repeat(3000000) + 'EOF';
    assert.match(commandDenial(huge, 'bash', [], clean), /命令太長/, 'past 5 MB with the heredoc body');
  });

  test('.claude/settings.json routes every file-reading tool to this script', () => {
    const settings = JSON.parse(fs.readFileSync(path.join(ROOT, '.claude', 'settings.json'), 'utf8'));
    const [{ timeout }] = settings.hooks.PreToolUse[0].hooks;
    assert.ok(Number.isFinite(timeout) && timeout >= 30, `explicit hook timeout: ${timeout}`);
    const matcher = new RegExp(`^(?:${settings.hooks.PreToolUse[0].matcher})$`);
    for (const tool of [...MATCHED_TOOLS, 'mcp__codebase-memory-mcp__search_code', 'mcp__codebase-memory-mcp__get_code_snippet']) {
      assert.ok(matcher.test(tool), tool);
    }
  });
});
