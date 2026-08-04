import React from "react";
import { ExternalLink } from "lucide-react";
import { Card, Badge, SectionTitle } from "../ui";
import changelog from "../../CHANGELOG.md?raw";

/** Render the `**bold**`, `*italic*`, `` `code` `` and `[text](url)` spans of a changelog
 * line. Emphasis recurses, since the changelog nests code inside bold (`**`hr_avg`**`). */
function inline(text) {
  const re = /\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)/g;
  const out = [];
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const key = m.index;
    if (m[1] !== undefined) {
      out.push(<strong key={key} className="font-semibold">{inline(m[1])}</strong>);
    } else if (m[2] !== undefined) {
      out.push(<em key={key}>{inline(m[2])}</em>);
    } else if (m[3] !== undefined) {
      out.push(
        <code key={key} className="rounded bg-gray-100 px-1 font-mono text-[0.85em] dark:bg-neutral-800">
          {m[3]}
        </code>,
      );
    } else {
      out.push(
        <a key={key} href={m[5]} target="_blank" rel="noreferrer" className="text-maroon underline dark:text-gold">
          {inline(m[4])}
        </a>,
      );
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** A deliberately small renderer for our own constrained CHANGELOG.md format —
 * cheaper than pulling in a markdown library. Handles the line kinds we use
 * (## [version] — date, ### section, - bullet, nested - bullet) and folds the
 * changelog's indented wrap-continuations back onto their bullet. Everything
 * before the first `## ` (the H1 and intro) is dropped — the card title stands
 * in for it. */
function renderChangelog(md) {
  const start = md.indexOf("\n## ");
  const body = start === -1 ? md : md.slice(start + 1);

  // Fold "  continuation" lines onto the preceding line; keep indented bullets
  // ("  - ") as their own nested entries.
  const lines = [];
  for (const raw of body.split("\n")) {
    const indented = /^\s+\S/.test(raw);
    if (indented && !/^\s+- /.test(raw) && lines.length) {
      lines[lines.length - 1].text += " " + raw.trim();
    } else {
      lines.push({ text: raw.trim(), nested: indented });
    }
  }

  const out = [];
  lines.forEach((line, i) => {
    const t = line.text;
    if (t.startsWith("## ")) {
      out.push(
        <h3 key={i} className="mt-5 font-display text-sm font-semibold text-maroon first:mt-0 dark:text-gold">
          {t.slice(3).replace(/^\[([^\]]+)\]/, "$1")}
        </h3>,
      );
    } else if (t.startsWith("### ")) {
      out.push(
        <p key={i} className="mt-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
          {t.slice(4)}
        </p>,
      );
    } else if (t === "---") {
      out.push(<hr key={i} className="mt-4 border-gray-100 dark:border-neutral-800" />);
    } else if (t.startsWith("- ")) {
      out.push(
        <li
          key={i}
          className={`mt-1.5 list-disc text-sm text-gray-600 dark:text-neutral-300 ${line.nested ? "ml-8" : "ml-4"}`}
        >
          {inline(t.slice(2))}
        </li>,
      );
    } else if (t) {
      out.push(
        <p key={i} className="mt-2 text-sm text-gray-600 dark:text-neutral-300">
          {inline(t)}
        </p>,
      );
    }
  });
  return out;
}

export default function AboutView({ me }) {
  return (
    <div className="max-w-2xl space-y-4">
      <Card className="p-6">
        <SectionTitle className="mb-2">Wearable Hub — Research console</SectionTitle>
        <p className="text-sm text-gray-600 dark:text-neutral-300">
          Register research subjects' wearables against the Google Health API and review their data.
          Signed in as <span className="font-medium">{me?.email}</span>{" "}
          {me?.is_superuser ? <Badge tone="maroon">superuser</Badge> : <Badge>researcher</Badge>}.
        </p>

        <div className="mt-4 space-y-1 text-sm text-gray-600 dark:text-neutral-300">
          <p><span className="font-semibold text-maroon dark:text-gold">Studies</span> — create studies, manage members, opt in to intraday heart rate, export all subjects.</p>
          <p><span className="font-semibold text-maroon dark:text-gold">Subjects</span> — add subjects (entry codes), review daily + intraday data, export per subject.</p>
          <p><span className="font-semibold text-maroon dark:text-gold">Research staff</span> — superusers manage who can sign in.</p>
        </div>

        <a
          href="/enroll"
          target="_blank"
          rel="noreferrer"
          className="mt-6 inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3.5 py-2 text-sm font-semibold text-maroon transition hover:bg-gray-50 dark:border-neutral-700 dark:text-gold dark:hover:bg-neutral-800"
        >
          Open subject enrollment page <ExternalLink className="h-4 w-4" />
        </a>

        <p className="mt-4 text-xs text-gray-400">Version {__APP_VERSION__}</p>
      </Card>

      <Card className="p-6">
        <SectionTitle>What's new</SectionTitle>
        <div className="mt-3 max-h-[60vh] overflow-y-auto pr-2">{renderChangelog(changelog)}</div>
      </Card>
    </div>
  );
}
