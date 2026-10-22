/**
 * Live Ops Copilot panel (Open Agent Hackathon 2026, team Mirror Works).
 *
 * New work: this file and copilot.css. It talks to the separate Live Ops Copilot
 * service (github.com/anugurashmitha8/liveops-copilot), a multi-agent team on a
 * Meterless World Model and H-MEM memory:
 *   GET  /issues       current ranked problems, with how long memory has seen each
 *   POST /investigate  run the agents on one problem; returns the checked answer
 *
 * Same pattern as the other map tools: the hook returns a toolbar button and a panel.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./copilot.css";

/** Same origin: Live Ops' nginx passes /copilot/ to the Copilot service, so the page's
 *  Content-Security-Policy (connect-src 'self') stays as it is. */
const COPILOT_URL: string =
  (globalThis as { LIVEOPS_COPILOT_URL?: string }).LIVEOPS_COPILOT_URL ?? "/copilot";

type Severity = "high" | "medium" | "low";

export type CopilotIssue = {
  key: string;
  type: string;
  severity: Severity | string;
  summary: string;
  entities: string[];
  first_seen: string | null;
  seen_count: number | null;
};

type Round = {
  round: number;
  cause: string | null;
  explanation: string | null;
  actions: string[] | null;
  verdict: string;
  problems: string[];
};

export type CopilotAnswer = {
  verified: boolean;
  message: string;
  issue: { key: string; summary: string };
  memory: string;
  rounds: Round[];
  run_id: string;
};

async function call<T>(path: string, method: "GET" | "POST" = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`${COPILOT_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 502 || res.status === 504) {
    throw new Error(res.status === 504
      ? "The agents took too long to answer. Try again."
      : "Can't reach the Copilot service. Start it with \"uvicorn api:app --host 0.0.0.0 --port 8100\".");
  }
  if (!res.ok) {
    let detail = `The Copilot service answered ${res.status}.`;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* keep the status message */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function errorText(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  if (/failed to fetch|networkerror|load failed/i.test(msg)) {
    return `Can't reach the Copilot service. Start it with "uvicorn api:app --host 0.0.0.0 --port 8100".`;
  }
  return msg;
}

function minutesBetween(from: string | null, to: string | null): number | null {
  if (!from || !to) return null;
  const a = Date.parse(from);
  const b = Date.parse(to);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.max(0, Math.round((b - a) / 60000));
}

/** "patient:P7307230" and "bed:4E-406A" mentioned in an answer, for Show on map. */
function mapIds(text: string): string[] {
  const out = new Set<string>();
  for (const m of text.matchAll(/\b(patient|bed):([A-Za-z0-9&_-]+)/g)) out.add(`${m[1]}:${m[2]}`);
  return [...out];
}

type Options = {
  enabled: boolean;
  /** Show a record on the map by its source id (e.g. "P7307230"); false when it isn't on the map. */
  onShow?: (nativeId: string) => boolean;
};

export function useCopilot({ enabled, onShow }: Options) {
  const [open, setOpen] = useState(false);
  const [issues, setIssues] = useState<CopilotIssue[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [answer, setAnswer] = useState<CopilotAnswer | null>(null);
  const busy = useRef(false);

  const refresh = useCallback(async () => {
    if (busy.current) return; // the service runs one job at a time
    setLoading(true);
    try {
      const data = await call<{ as_of: string; issues: CopilotIssue[] }>("/issues");
      setIssues(data.issues);
      setAsOf(data.as_of);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled || !open) return;
    void refresh();
    const t = window.setInterval(() => void refresh(), 60_000);
    return () => window.clearInterval(t);
  }, [enabled, open, refresh]);

  useEffect(() => {
    if (!running) return;
    setElapsed(0);
    const t = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(t);
  }, [running]);

  const investigate = useCallback(async (key: string) => {
    busy.current = true;
    setRunning(key);
    setAnswer(null);
    setError(null);
    try {
      setAnswer(await call<CopilotAnswer>("/investigate", "POST", { key }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      busy.current = false;
      setRunning(null);
    }
  }, []);

  const high = issues.filter((i) => i.severity === "high").length;

  const button = enabled ? (
    <button
      type="button"
      className={`btn ${open ? "primary" : ""}`}
      aria-pressed={open}
      title="Live Ops Copilot: AI agents explain why a problem is happening, with checked evidence"
      onClick={() => setOpen((o) => !o)}
    >
      Copilot
      {high > 0 && <span className="cp-count" aria-label={`${high} urgent`}>{high}</span>}
    </button>
  ) : null;

  const panel = enabled && open ? (
    <aside className="lm-glass cp-panel" aria-label="Live Ops Copilot">
      <header className="cp-head">
        <h2>Copilot</h2>
        <p className="cp-sub">AI agents find why things are stuck. A second agent checks every claim before you see it.</p>
        <button type="button" className="cp-close" aria-label="Close Copilot" onClick={() => setOpen(false)}>×</button>
      </header>

      {error && <p className="cp-error" role="alert">{error}</p>}

      {running ? (
        <Working elapsed={elapsed} />
      ) : answer ? (
        <AnswerView answer={answer} onShow={onShow} onBack={() => setAnswer(null)} />
      ) : (
        <IssueList issues={issues} asOf={asOf} loading={loading} onWhy={investigate} onRefresh={() => void refresh()} />
      )}
    </aside>
  ) : null;

  return { button, panel, open, setOpen };
}

function IssueList(props: {
  issues: CopilotIssue[];
  asOf: string | null;
  loading: boolean;
  onWhy: (key: string) => void;
  onRefresh: () => void;
}) {
  const { issues, asOf, loading, onWhy, onRefresh } = props;
  if (loading && issues.length === 0) return <p className="cp-muted">Checking the hospital…</p>;
  return (
    <>
      <div className="cp-bar">
        <span className="cp-muted">
          {issues.length === 0 ? "No problems found right now." : `${issues.length} problem${issues.length === 1 ? "" : "s"} found`}
          {asOf ? `, as of ${new Date(asOf).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}
        </span>
        <button type="button" className="btn" onClick={onRefresh} disabled={loading}>{loading ? "Checking…" : "Check again"}</button>
      </div>
      <ul className="cp-issues">
        {issues.map((i) => {
          const open = minutesBetween(i.first_seen, asOf);
          return (
            <li key={i.key} className={`cp-issue cp-issue--${i.severity}`}>
              <p className="cp-issue-text">{i.summary}</p>
              <div className="cp-issue-foot">
                <span className="cp-muted">
                  {i.severity === "high" ? "Urgent" : i.severity === "medium" ? "Worth a look" : "Watching"}
                  {open !== null && open > 0 ? `, open ${open} min` : ""}
                </span>
                <button type="button" className="btn primary" onClick={() => onWhy(i.key)}>Find out why</button>
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}

const STEPS = [
  "Pull fresh data from both systems through Zetaris",
  "Re-check the problem",
  "Investigator explains the cause, citing records",
  "Critic checks every cited record and value",
  "Write the answer, or mark it unverified",
];

function Working({ elapsed }: { elapsed: number }) {
  return (
    <div className="cp-working" aria-live="polite">
      <p className="cp-working-head">The agents are working · {elapsed}s</p>
      <p className="cp-muted">Usually 30 to 60 seconds. What they do:</p>
      <ol className="cp-steps">
        {STEPS.map((s) => <li key={s}>{s}</li>)}
      </ol>
    </div>
  );
}

function AnswerView(props: { answer: CopilotAnswer; onShow?: (nativeId: string) => boolean; onBack: () => void }) {
  const { answer, onShow, onBack } = props;
  const message = answer.message.replace(/\*\*/g, "");
  const ids = useMemo(() => mapIds(message), [message]);
  const [missing, setMissing] = useState<string | null>(null);
  return (
    <div className="cp-answer">
      <button type="button" className="cp-back" onClick={onBack}>Back to all problems</button>

      <div className={`cp-verdict ${answer.verified ? "cp-verdict--ok" : "cp-verdict--open"}`}>
        {answer.verified
          ? `Checked and confirmed by the Critic (${answer.rounds.length} round${answer.rounds.length === 1 ? "" : "s"})`
          : `Not confirmed: the agents disagreed after ${answer.rounds.length} rounds`}
      </div>

      <p className="cp-issue-text">{answer.issue.summary}</p>
      <div className="cp-message">{message}</div>

      {ids.length > 0 && onShow && (
        <div className="cp-chips" aria-label="Records in this answer">
          {ids.map((id) => (
            <button key={id} type="button" className="cp-chip"
              onClick={() => setMissing(onShow(id.split(":")[1]) ? null : id)}>
              Show {id.replace(":", " ")}
            </button>
          ))}
          {missing && <p className="cp-muted">{missing.replace(":", " ")} isn't on the map right now.</p>}
        </div>
      )}

      {answer.memory && (
        <section className="cp-section">
          <h3>What the Copilot remembers</h3>
          <p className="cp-muted cp-pre">{answer.memory}</p>
        </section>
      )}

      <section className="cp-section">
        <h3>How the agents got there</h3>
        <ol className="cp-rounds">
          {answer.rounds.map((r) => (
            <li key={r.round} className={r.verdict === "pass" ? "cp-round--pass" : "cp-round--revise"}>
              <p><strong>Investigator:</strong> {r.cause ?? "No cause given."}</p>
              <p><strong>Critic:</strong> {r.verdict === "pass" ? "Confirmed." : "Sent back."}</p>
              {r.problems.length > 0 && (
                <ul className="cp-problems">{r.problems.map((p, n) => <li key={n}>{p}</li>)}</ul>
              )}
            </li>
          ))}
        </ol>
      </section>
      <p className="cp-muted cp-run">Run {answer.run_id}</p>
    </div>
  );
}
