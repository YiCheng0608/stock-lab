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

const { commandDenial, normalizeTarget } = require('./agent_guard.cjs');

const SCRIPT = path.join(__dirname, 'agent_guard.cjs');
const ROOT = path.resolve(__dirname, '..', '..');

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

  test('.claude/settings.json runs this script for Edit, Write, Bash and PowerShell', { skip: process.platform === 'win32' && 'Git Bash vs WSL bash on PATH; checked by hand' }, () => {
    const settings = JSON.parse(fs.readFileSync(path.join(ROOT, '.claude', 'settings.json'), 'utf8'));
    const [entry] = settings.hooks.PreToolUse;
    assert.deepEqual(entry.matcher.split('|').sort(), ['Bash', 'Edit', 'PowerShell', 'Write']);
    const [{ command }] = entry.hooks;
    const run = (input) =>
      spawnSync('bash', ['-c', command], { input: JSON.stringify(input), env: { ...env, CLAUDE_PROJECT_DIR: ROOT }, encoding: 'utf8' });
    assert.equal(run(bash('git stash clear')).status, 2);
    assert.equal(run(bash('git status')).status, 0);
    assert.equal(run(write(path.join(master, 'README.md'))).status, 2);
  });
});
