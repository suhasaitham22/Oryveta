import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "flex h-12 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 text-base md:text-sm text-[var(--ink)] placeholder:text-[var(--muted)] focus-visible:border-[var(--accent)] disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
