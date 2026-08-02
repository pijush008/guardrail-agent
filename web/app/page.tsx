"use client";

import { useState, useRef, useEffect } from "react";
import { api, type ChatResponse } from "@/lib/api";

type Message = {
  role: "user" | "agent";
  content: string;
  meta?: ChatResponse;
};

const SUGGESTIONS = [
  "What are the goals for Project Phoenix in Q3?",
  "Are there any blocked Jira issues?",
  "Who is the engineering lead for Project Phoenix?",
  "Send a reminder email to the finance team about invoice 1042.",
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    setMessages((m) => [
      ...m,
      {
        role: "user",
        content: file ? `${question}\n\n📎 ${file.name}` : question,
      },
    ]);
    setInput("");
    const attached = file;
    setFile(null);
    setBusy(true);
    try {
      const res = attached
        ? await api.chatWithFile(question, attached)
        : await api.chat(question);
      setMessages((m) => [...m, { role: "agent", content: res.answer, meta: res }]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: "agent", content: `Service error: ${(err as Error).message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-7rem)] max-w-3xl flex-col">
      <h1 className="mb-1 text-2xl font-bold text-ink-200">Ask the guardrail agent</h1>
      <p className="mb-4 text-sm text-ink-400">
        Answers cite the evidence they came from; every high-stakes action is gated behind
        a human approval.
      </p>

      {messages.length === 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              className="rounded-lg border border-ink-700 bg-ink-800 px-3 py-1.5 text-left text-xs text-ink-300 hover:border-accent"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="flex-1 space-y-4 overflow-y-auto rounded-xl border border-ink-700 bg-ink-900/50 p-4">
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
        {busy && (
          <div className="text-sm text-ink-400">
            <span className="animate-pulse">Agent is working…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        className="mt-4 flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about Project Phoenix, blockers, invoices…"
            className="flex-1 rounded-xl border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-ink-200 placeholder:text-ink-500 focus:border-accent focus:outline-none"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-accent px-5 text-sm font-semibold text-ink-950 disabled:opacity-50"
          >
            Send
          </button>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <label className="flex cursor-pointer items-center gap-1 rounded-lg border border-ink-700 bg-ink-800 px-2.5 py-1.5 text-ink-300 hover:border-accent">
            <span>📎 Attach PDF</span>
            <input
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          {file && (
            <span className="flex items-center gap-1 text-ink-400">
              {file.name}
              <button
                type="button"
                onClick={() => setFile(null)}
                className="text-bad hover:underline"
              >
                remove
              </button>
            </span>
          )}
          <span className="ml-auto text-ink-500">
            Uploaded PDFs are scanned for injection &amp; PII-redacted before use.
          </span>
        </div>
      </form>
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-accent text-ink-950"
            : "border border-ink-700 bg-ink-800 text-ink-200"
        }`}
      >
        <div className="whitespace-pre-wrap">{message.content}</div>
        {message.meta && (
          <div className="mt-3 space-y-2 border-t border-ink-700/60 pt-2 text-xs">
            <div className="flex flex-wrap gap-1.5">
              {message.meta.evidence.map((e) => (
                <span
                  key={e.id}
                  className="rounded bg-ink-700/60 px-2 py-0.5 text-ink-300"
                >
                  {e.source}:{e.id}
                  {e.redacted ? " 🔒" : ""}
                </span>
              ))}
              <span className="rounded bg-ink-700/60 px-2 py-0.5 text-ink-400">
                {message.meta.latency_ms}ms · {message.meta.tokens} tokens
              </span>
            </div>
            {message.meta.citation_valid && (
              <div className="text-ok">
                ✓ citations validated ({message.meta.citations.length})
              </div>
            )}
            {message.meta.citation_errors.length > 0 && (
              <div className="text-bad">✗ {message.meta.citation_errors.join("; ")}</div>
            )}
            {message.meta.blocked && (
              <div className="rounded bg-bad/10 p-2 text-bad">
                Blocked: {message.meta.block_reason}
              </div>
            )}
            {message.meta.pending_action_id && (
              <div className="rounded bg-warn/10 p-2 text-warn">
                ⏳ High-stakes action awaiting approval — see Approvals.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
