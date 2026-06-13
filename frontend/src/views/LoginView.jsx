import React from "react";
import { Activity } from "lucide-react";
import { apiBase } from "../api";

export default function LoginView() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-neutral-950">
      <div className="w-[22rem] rounded-2xl border border-gray-200 bg-white p-10 text-center shadow-lg dark:border-neutral-800 dark:bg-neutral-900">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-maroon text-gold">
          <Activity className="h-8 w-8" strokeWidth={2.5} />
        </div>
        <h1 className="font-display text-2xl font-bold text-maroon dark:text-gold">Wearable Hub</h1>
        <p className="mt-1 text-sm text-gray-500">Researcher console</p>
        <a
          href={`${apiBase}/auth/login`}
          className="mt-6 inline-block w-full rounded-lg bg-maroon px-4 py-2.5 font-semibold text-white transition hover:bg-maroon-dark"
        >
          Sign in with Google
        </a>
      </div>
    </div>
  );
}
