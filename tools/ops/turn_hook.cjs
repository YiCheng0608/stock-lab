#!/usr/bin/env node
// Turn hook of engineer sessions (Issue #595; docs/COORDINATOR.md 無人值守運作,
// docs/ops/MONITOR.md). .claude/settings.json runs it on Stop, SessionEnd and
// UserPromptSubmit with the hook's JSON on stdin. It acts only in a session whose
// project is on a task/<issue>-* branch (an engineer's worktree): on master (the
// coordinator), any other branch, or with STOCK_TURN_HOOK=off (a review session opened
// in a task worktree) it exits 0 at once, prints nothing and writes nothing.
//
// It keeps one state file per session, <data>/logs/sessions/<session id>.json, which the
// event monitor reads (engineer_waiting, engineer_ended events):
//   {"session_id", "issue", "branch", "cwd", "state", "started_at", "ended_at",
//    "commented", "last_message", "background_tasks", "end_reason"}
//   UserPromptSubmit  state "working", started_at. Prints nothing: what it prints on
//                     that event would be added to the session's context.
//   Stop              state "stopped", ended_at, commented, last_message (the last
//                     assistant text, 500 characters at most), background_tasks (how
//                     many were in flight). commented says whether this turn, the entries
//                     after the last prompt a person (or a terminal notice) typed, posted
//                     on an Issue or PR; see commentCommand() for what counts. When it is
//                     false and stop_hook_active is not true, the stop is blocked once with
//                     REASON and the state is "working" (the session goes on); with
//                     stop_hook_active true it never blocks (no loop).
//   SessionEnd        state "ended", ended_at, end_reason (the hook's reason).
// <data> is found as compact_hook.sh finds it: $STOCK_DATA_DIR, then $HOME/stock-lab-data.
// Any error of its own (no transcript, no data directory, a bad input) never blocks:
// exit 0, and the error goes to <data>/logs/turn-hook.log (to stderr when there is no
// data directory). Times are UTC ISO. Test hook: TURN_HOOK_NOW (epoch seconds).
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

const REASON =
  "這一回合沒有在 Issue／PR 留言；如果你在等統籌決定或回覆，先照 docs/WORKFLOW.md「留言類型」以 `提問：` 留在 Issue 再結束；不需要統籌動作就直接結束。";
const MESSAGE_LIMIT = 500;
const SESSION_ID = /^[A-Za-z0-9_-]+$/;
const TASK_BRANCH = /^task\/(\d+)-/;

// A shell command that posts on an Issue or PR: gh issue comment, gh pr comment,
// gh pr create, gh pr review, comment.sh, or gh api on a .../comments endpoint that
// posts (-X/--method POST, or a field or --input, with which gh api posts by default).
// GET reads of the same endpoint (gh api …/comments, gh issue view --comments) do not.
function commentCommand(command) {
  if (typeof command !== "string") return false;
  if (/\bgh\s+(issue|pr)\s+comment\b/.test(command)) return true;
  if (/\bgh\s+pr\s+(create|review)\b/.test(command)) return true;
  if (/\btools\/ops\/comment\.sh\b/.test(command)) return true;
  for (const part of command.split(/&&|\|\||[;|\n]/)) {
    if (!/\bgh\s+api\b/.test(part) || !/\/comments\b/.test(part)) continue;
    if (/(-X|--method)[\s=]+GET\b/i.test(part)) continue;
    if (/(-X|--method)[\s=]+(POST|PATCH)\b/i.test(part)) return true;
    if (/\s(-f|-F|--field|--raw-field|--input)[\s=]/.test(part)) return true;
  }
  return false;
}

function nowIso() {
  const at = process.env.TURN_HOOK_NOW;
  const ms = at && /^\d+$/.test(at) ? Number(at) * 1000 : Date.now();
  return new Date(Math.floor(ms / 1000) * 1000).toISOString().replace(".000Z", "Z");
}

// $HOME as Git Bash spells it (/c/Users/...) or as Windows does.
function home() {
  const value = process.env.HOME;
  if (!value) return os.homedir();
  const m = /^\/([A-Za-z])(\/.*)?$/.exec(value);
  if (m && process.platform === "win32") return `${m[1].toUpperCase()}:${m[2] || "/"}`;
  return value;
}

function dataDir() {
  return process.env.STOCK_DATA_DIR || path.join(home(), "stock-lab-data");
}

// The checked-out branch of DIR's git checkout, read from its HEAD (no git process:
// SessionEnd has a 1.5-second budget). A worktree's .git is a file "gitdir: <path>".
function branchOf(dir) {
  let current = path.resolve(dir);
  for (;;) {
    const dotGit = path.join(current, ".git");
    let stat = null;
    try {
      stat = fs.statSync(dotGit);
    } catch {
      stat = null;
    }
    if (stat) {
      let gitDir = dotGit;
      if (stat.isFile()) {
        const m = /^gitdir:\s*(.+?)\s*$/m.exec(fs.readFileSync(dotGit, "utf8"));
        if (!m) return "";
        gitDir = path.resolve(current, m[1]);
      }
      const head = fs.readFileSync(path.join(gitDir, "HEAD"), "utf8");
      const ref = /^ref:\s*refs\/heads\/(.+?)\s*$/m.exec(head);
      return ref ? ref[1] : "";
    }
    const parent = path.dirname(current);
    if (parent === current) return "";
    current = parent;
  }
}

function readJson(file) {
  try {
    const value = JSON.parse(fs.readFileSync(file, "utf8"));
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

function writeJson(file, value) {
  const tmp = path.join(path.dirname(file), `.${path.basename(file)}.tmp.${process.pid}`);
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2) + "\n", "utf8");
  fs.renameSync(tmp, file);
}

function clip(text, limit) {
  const chars = Array.from(typeof text === "string" ? text.trim() : "");
  return chars.length > limit ? chars.slice(0, limit).join("") : chars.join("");
}

function textOf(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((b) => b && b.type === "text" && typeof b.text === "string")
    .map((b) => b.text)
    .join("\n");
}

// A prompt someone typed (or a terminal notice), not a tool result, a meta entry or a
// compaction summary.
function isPrompt(entry) {
  if (!entry || entry.type !== "user" || entry.isMeta || entry.isCompactSummary) return false;
  const message = entry.message || {};
  const content = message.content;
  if (typeof content === "string") return true;
  if (!Array.isArray(content)) return false;
  return !content.some((b) => b && b.type === "tool_result");
}

// {commented, lastText} of the turn: the entries after the last prompt. A comment counts
// when its tool call has a result that is not an error (a failed gh exits non-zero).
function scanTurn(transcriptPath) {
  const entries = [];
  for (const line of fs.readFileSync(transcriptPath, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try {
      entries.push(JSON.parse(line));
    } catch {
      // a partial last line
    }
  }
  let start = 0;
  entries.forEach((entry, i) => {
    if (isPrompt(entry)) start = i + 1;
  });
  const calls = new Set();
  let commented = false;
  let lastText = "";
  for (const entry of entries.slice(start)) {
    if (!entry || typeof entry !== "object") continue;
    const content = entry.message && entry.message.content;
    if (entry.type === "assistant" && Array.isArray(content)) {
      for (const block of content) {
        if (!block) continue;
        if (block.type === "tool_use" && block.input && commentCommand(block.input.command)) {
          calls.add(block.id);
        }
      }
      const text = textOf(content);
      if (text.trim()) lastText = text;
    } else if (entry.type === "user" && Array.isArray(content)) {
      for (const block of content) {
        if (block && block.type === "tool_result" && calls.has(block.tool_use_id) && block.is_error !== true) {
          commented = true;
        }
      }
    }
  }
  return { commented, lastText };
}

function main() {
  if ((process.env.STOCK_TURN_HOOK || "").toLowerCase() === "off") return 0;
  let raw = "";
  try {
    raw = fs.readFileSync(0, "utf8");
  } catch {
    raw = "";
  }
  let input;
  try {
    input = JSON.parse(raw);
  } catch {
    return 0;
  }
  if (!input || typeof input !== "object") return 0;
  const project = process.env.CLAUDE_PROJECT_DIR || input.cwd;
  if (!project) return 0;
  let branch = "";
  try {
    branch = branchOf(project);
  } catch {
    return 0;
  }
  const task = TASK_BRANCH.exec(branch);
  if (!task) return 0;

  const data = dataDir();
  const logs = path.join(data, "logs");
  const logError = (message) => {
    const line = `${nowIso()} ${input.hook_event_name || "?"} session=${input.session_id || "?"} ${message}\n`;
    try {
      fs.appendFileSync(path.join(logs, "turn-hook.log"), line, "utf8");
    } catch {
      process.stderr.write(`turn_hook: ${line}`);
    }
  };
  try {
    if (!fs.statSync(data).isDirectory()) throw new Error("not a directory");
  } catch {
    process.stderr.write(`turn_hook: 資料目錄不在：${data}\n`);
    return 0;
  }
  const sessionId = input.session_id;
  if (typeof sessionId !== "string" || !SESSION_ID.test(sessionId)) {
    logError("bad session_id");
    return 0;
  }
  const event = input.hook_event_name;
  const dir = path.join(logs, "sessions");
  const file = path.join(dir, `${sessionId}.json`);
  try {
    fs.mkdirSync(dir, { recursive: true });
    const previous = readJson(file) || {};
    const state = {
      ...previous,
      session_id: sessionId,
      issue: Number(task[1]),
      branch,
      cwd: input.cwd || previous.cwd || project,
    };
    if (event === "UserPromptSubmit") {
      Object.assign(state, { state: "working", started_at: nowIso() });
      writeJson(file, state);
      return 0;
    }
    if (event === "SessionEnd") {
      Object.assign(state, { state: "ended", ended_at: nowIso(), end_reason: input.reason || "unknown" });
      writeJson(file, state);
      return 0;
    }
    if (event !== "Stop") return 0;
    let scan = null;
    let error = "";
    try {
      if (typeof input.transcript_path !== "string" || !input.transcript_path) throw new Error("no transcript_path");
      scan = scanTurn(input.transcript_path);
    } catch (e) {
      error = `transcript unreadable: ${e && e.message ? e.message : e}`;
    }
    const message =
      typeof input.last_assistant_message === "string" && input.last_assistant_message.trim()
        ? input.last_assistant_message
        : scan
          ? scan.lastText
          : "";
    Object.assign(state, {
      state: "stopped",
      ended_at: nowIso(),
      // null: the transcript could not be read, so nobody knows; the monitor treats it
      // as no comment.
      commented: scan ? scan.commented : null,
      last_message: clip(message, MESSAGE_LIMIT),
      background_tasks: Array.isArray(input.background_tasks) ? input.background_tasks.length : 0,
    });
    delete state.end_reason;
    const block = !error && !scan.commented && input.stop_hook_active !== true;
    if (block) {
      // Blocked, the session goes on working (no UserPromptSubmit follows): not stopped,
      // or a continuation longer than 30 minutes would read as waiting. Its next stop
      // (stop_hook_active) writes stopped again.
      Object.assign(state, { state: "working", started_at: nowIso() });
    }
    writeJson(file, state);
    if (error) {
      logError(error);
      return 0;
    }
    if (block) {
      process.stdout.write(JSON.stringify({ decision: "block", reason: REASON }) + "\n");
    }
    return 0;
  } catch (e) {
    logError(`error: ${e && e.message ? e.message : e}`);
    return 0;
  }
}

module.exports = { commentCommand, scanTurn, REASON };

if (require.main === module) {
  let code = 0;
  try {
    code = main();
  } catch {
    code = 0;
  }
  process.exitCode = code;
}
