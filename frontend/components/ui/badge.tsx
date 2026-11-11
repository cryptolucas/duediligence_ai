import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-none", {
  variants: {
    variant: {
      default: "border-transparent bg-primary text-primary-foreground",
      secondary: "border-transparent bg-secondary text-secondary-foreground",
      outline: "text-foreground",
      critical: "border-transparent bg-destructive text-destructive-foreground",
      high: "border-transparent bg-orange-100 text-orange-800",
      medium: "border-transparent bg-amber-100 text-amber-800",
      positive: "border-transparent bg-emerald-100 text-emerald-800",
      muted: "border-transparent bg-muted text-muted-foreground",
    },
  },
  defaultVariants: { variant: "default" },
});

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
