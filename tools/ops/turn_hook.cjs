#!/usr/bin/env node
// Turn hook of engineer sessions (Issue #595). What it does for the coordinator and its
// known limits are written once, in docs/COORDINATOR.md 無人值守運作 (工程師 session 的
// 狀態); the monitor's events from its files in docs/ops/MONITOR.md.
// .claude/settings.json runs it on Stop, StopFailure, SessionEnd and UserPromptSubmit
// with the hook's JSON on stdin. It acts only in a session whose project is on a
// task/<issue>-* branch (an engineer's worktree): on master (the coordinator), any other
// branch, a detached HEAD, outside git, or with STOCK_TURN_HOOK=off (a review session
// opened in a task worktree) it exits 0 at once, prints nothing and writes nothing.
//
// It keeps one state file per session, <data>/logs/sessions/<session id>.json:
//   {"session_id", "issue", "branch", "cwd", "state", "started_at", "ended_at",
//    "commented", "commented_at", "last_message", "background_tasks", "end_reason",
//    "error", "error_details"}
//   UserPromptSubmit  state "working", started_at. Prints nothing: what it prints on
//                     that event would be added to the session's context. It runs for
//                     a task notification too (seen in this session's transcript, #595).
//   Stop              state "stopped", ended_at, commented, commented_at, last_message
//                     (the last assistant text, 500 characters at most), background_tasks
//                     (how many were in flight). commented is true when this turn (the
//                     entries after the last prompt: one typed, a terminal notice or a task
//                     notification; isMeta entries such as Stop hook feedback are not
//                     prompts) has a successful Issue/PR comment (commentCommand) and the
//                     last one was at most RECENT before the stop: a comment two hours
//                     before a question asked in the terminal does not count. When it is
//                     false and stop_hook_active is not true, the stop is blocked once
//                     with REASON and the state is "working" (the session goes on); with
//                     stop_hook_active true it never blocks (no loop).
//   StopFailure       (the turn ended on an API error; Stop does not run then) state
//                     "failed", ended_at, error, error_details, last_message (the error
//                     text the hook gets).
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
// The last comment of the turn counts only this close to its end (#595 review).
const RECENT_MS = 10 * 60 * 1000;
const SESSION_ID = /^[A-Za-z0-9_-]+$/;
const TASK_BRANCH = /^task\/(\d+)-/;

// A shell command that posts on an Issue or PR: gh issue comment, gh pr comment,
// gh pr create, gh pr review, comment.sh, or gh api on a .../comments endpoint that
// posts (-X/--method POST, or a field or --input, with which gh api posts by default).
// GET reads of the same endpoint (gh api …/comments, gh issue view --comments) do not.
// A plain string match: the words inside an echo or a heredoc count too.
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

function nowMs() {
  const at = process.env.TURN_HOOK_NOW;
  return at && /^\d+$/.test(at) ? Number(at) * 1000 : Date.now();
}

function iso(ms) {
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
// "" for a detached HEAD or outside git.
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
  try {
    fs.writeFileSync(tmp, JSON.stringify(value, null, 2) + "\n", "utf8");
    fs.renameSync(tmp, file);
  } catch (e) {
    try {
      fs.rmSync(tmp, { force: true });
    } catch {
      // nothing more to do
    }
    throw e;
  }
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

// A prompt (typed, a terminal notice, a task notification), not a tool result, an
// isMeta entry (Stop hook feedback, for one) or a compaction summary.
function isPrompt(entry) {
  if (!entry || entry.type !== "user" || entry.isMeta || entry.isCompactSummary) return false;
  const message = entry.message || {};
  const content = message.content;
  if (typeof content === "string") return true;
  if (!Array.isArray(content)) return false;
  return !content.some((b) => b && b.type === "tool_result");
}

function stamp(entry) {
  const ms = entry && typeof entry.timestamp === "string" ? Date.parse(entry.timestamp) : NaN;
  return Number.isFinite(ms) ? ms : null;
}

// {commented, commentedAt, lastText} of the turn ending at END_MS: the entries after the
// last prompt. A comment is a tool call commentCommand() matches that has a result which
// is not an error (a failed gh exits non-zero); its time is the result's timestamp (the
// call's when the result has none). commented: the last such comment is at most RECENT_MS
// before the end; a comment with no timestamp at all does not count.
function scanTurn(transcriptPath, endMs) {
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
  const calls = new Map();
  let commentedAt = null;
  let lastText = "";
  for (const entry of entries.slice(start)) {
    if (!entry || typeof entry !== "object") continue;
    const content = entry.message && entry.message.content;
    if (entry.type === "assistant" && Array.isArray(content)) {
      for (const block of content) {
        if (block && block.type === "tool_use" && block.input && commentCommand(block.input.command)) {
          calls.set(block.id, stamp(entry));
        }
      }
      const text = textOf(content);
      if (text.trim()) lastText = text;
    } else if (entry.type === "user" && Array.isArray(content)) {
      for (const block of content) {
        if (block && block.type === "tool_result" && calls.has(block.tool_use_id) && block.is_error !== true) {
          const at = stamp(entry) ?? calls.get(block.tool_use_id);
          if (at !== null && (commentedAt === null || at > commentedAt)) commentedAt = at;
        }
      }
    }
  }
  const commented = commentedAt !== null && endMs - commentedAt <= RECENT_MS;
  return { commented, commentedAt, lastText };
}

function errorText(e) {
  return e && e.message ? e.message : String(e);
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
  if (!project || typeof project !== "string") return 0;
  let branch = "";
  try {
    branch = branchOf(project);
  } catch {
    return 0;
  }
  const task = TASK_BRANCH.exec(branch);
  if (!task) return 0;

  const now = nowMs();
  const data = dataDir();
  const logs = path.join(data, "logs");
  const logError = (message) => {
    const line = `${iso(now)} ${input.hook_event_name || "?"} session=${input.session_id || "?"} ${message}\n`;
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
  if (!["UserPromptSubmit", "Stop", "StopFailure", "SessionEnd"].includes(event)) return 0;
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
      cwd: typeof input.cwd === "string" ? input.cwd : previous.cwd || project,
    };
    // What only one state means: gone when the session moves to another.
    for (const key of ["end_reason", "error", "error_details"]) delete state[key];
    if (event === "UserPromptSubmit") {
      Object.assign(state, { state: "working", started_at: iso(now) });
      writeJson(file, state);
      return 0;
    }
    if (event === "SessionEnd") {
      Object.assign(state, {
        state: "ended",
        ended_at: iso(now),
        end_reason: typeof input.reason === "string" ? input.reason : "unknown",
      });
      writeJson(file, state);
      return 0;
    }
    if (event === "StopFailure") {
      Object.assign(state, {
        state: "failed",
        ended_at: iso(now),
        error: typeof input.error === "string" ? input.error : "unknown",
        error_details: clip(
          typeof input.error_details === "string" ? input.error_details : JSON.stringify(input.error_details ?? ""),
          MESSAGE_LIMIT,
        ),
        last_message: clip(input.last_assistant_message, MESSAGE_LIMIT),
      });
      writeJson(file, state);
      return 0;
    }
    let scan = null;
    let error = "";
    try {
      if (typeof input.transcript_path !== "string" || !input.transcript_path) throw new Error("no transcript_path");
      scan = scanTurn(input.transcript_path, now);
    } catch (e) {
      error = `transcript unreadable: ${errorText(e)}`;
    }
    const message =
      typeof input.last_assistant_message === "string" && input.last_assistant_message.trim()
        ? input.last_assistant_message
        : scan
          ? scan.lastText
          : "";
    Object.assign(state, {
      state: "stopped",
      ended_at: iso(now),
      // null: the transcript could not be read, so nobody knows; the monitor treats it
      // as no comment.
      commented: scan ? scan.commented : null,
      commented_at: scan && scan.commentedAt !== null ? iso(scan.commentedAt) : null,
      last_message: clip(message, MESSAGE_LIMIT),
      background_tasks: Array.isArray(input.background_tasks) ? input.background_tasks.length : 0,
    });
    const block = !error && !scan.commented && input.stop_hook_active !== true;
    if (block) {
      // Blocked, the session goes on working (no UserPromptSubmit follows): not stopped,
      // or a continuation longer than 30 minutes would read as waiting. Its next stop
      // (stop_hook_active) writes stopped again.
      Object.assign(state, { state: "working", started_at: iso(now) });
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
    logError(`error: ${errorText(e)}`);
    return 0;
  }
}

module.exports = { commentCommand, scanTurn, REASON, RECENT_MS };

if (require.main === module) {
  let code = 0;
  try {
    code = main();
  } catch {
    code = 0;
  }
  process.exitCode = code;
}
