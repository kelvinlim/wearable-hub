import React from "react";
import { ExternalLink } from "lucide-react";
import { Card, Badge, SectionTitle } from "../ui";

export default function AboutView({ me }) {
  return (
    <Card className="max-w-2xl p-6">
      <SectionTitle className="mb-2">Wearable Hub — Research console</SectionTitle>
      <p className="text-sm text-gray-600 dark:text-neutral-300">
        Register research subjects' wearables against the Google Health API and review their data.
        Signed in as <span className="font-medium">{me?.email}</span>{" "}
        {me?.is_superuser ? <Badge tone="maroon">superuser</Badge> : <Badge>researcher</Badge>}.
      </p>

      <div className="mt-4 space-y-1 text-sm text-gray-600 dark:text-neutral-300">
        <p><span className="font-semibold text-maroon dark:text-gold">Studies</span> — create studies, manage members, opt in to intraday heart rate, export all subjects.</p>
        <p><span className="font-semibold text-maroon dark:text-gold">Subjects</span> — add subjects (entry codes), review daily + intraday data, export per subject.</p>
        <p><span className="font-semibold text-maroon dark:text-gold">Researchers</span> — superusers manage who can sign in.</p>
      </div>

      <a
        href="/enroll"
        target="_blank"
        rel="noreferrer"
        className="mt-6 inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3.5 py-2 text-sm font-semibold text-maroon transition hover:bg-gray-50 dark:border-neutral-700 dark:text-gold dark:hover:bg-neutral-800"
      >
        Open subject enrollment page <ExternalLink className="h-4 w-4" />
      </a>
    </Card>
  );
}
