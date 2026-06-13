import React from "react";
import { cn } from "./lib";

const VARIANTS = {
  primary: "bg-maroon text-white hover:bg-maroon-dark",
  gold: "bg-gold text-maroon hover:bg-gold-dark",
  ghost:
    "bg-transparent text-maroon border border-gray-300 hover:bg-gray-50 dark:text-gold dark:border-neutral-700 dark:hover:bg-neutral-800",
  danger: "bg-red-700 text-white hover:bg-red-800",
  subtle: "bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-neutral-800 dark:text-neutral-200 dark:hover:bg-neutral-700",
};

export function Button({ variant = "primary", className, ...props }) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold transition-colors disabled:opacity-50 disabled:cursor-default",
        VARIANTS[variant],
        className
      )}
      {...props}
    />
  );
}

export function Card({ className, children }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-gray-200 bg-white shadow-sm dark:border-neutral-800 dark:bg-neutral-900",
        className
      )}
    >
      {children}
    </div>
  );
}

const TONES = {
  gray: "bg-gray-100 text-gray-600 dark:bg-neutral-800 dark:text-neutral-300",
  green: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  gold: "bg-gold/25 text-maroon dark:text-gold",
  maroon: "bg-maroon/10 text-maroon dark:bg-maroon/40 dark:text-gold",
};

export function Badge({ tone = "gray", className, children }) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", TONES[tone], className)}>
      {children}
    </span>
  );
}

const inputCls =
  "rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-maroon focus:ring-2 focus:ring-maroon/20 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-100";

export function Input({ className, ...props }) {
  return <input className={cn(inputCls, className)} {...props} />;
}

export function Select({ className, children, ...props }) {
  return (
    <select className={cn(inputCls, "pr-8", className)} {...props}>
      {children}
    </select>
  );
}

export function SectionTitle({ children, className }) {
  return <h3 className={cn("font-display text-base font-semibold text-maroon dark:text-gold", className)}>{children}</h3>;
}

// Light table helpers (CRMS look): uppercase muted headers, hairline rows.
export function Th({ className, children }) {
  return (
    <th className={cn("px-4 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400", className)}>
      {children}
    </th>
  );
}

export function Td({ className, children, ...props }) {
  return (
    <td className={cn("px-4 py-3 text-sm text-gray-800 dark:text-neutral-200", className)} {...props}>
      {children}
    </td>
  );
}

export function Empty({ children }) {
  return <div className="px-4 py-8 text-center text-sm text-gray-400">{children}</div>;
}
