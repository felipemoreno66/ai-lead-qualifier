"use client";

import { AlertDialog as AlertDialogPrimitive } from "radix-ui";
import * as React from "react";
import { cn } from "@/lib/utils";

/* shadcn/ui AlertDialog, restyled with the "Warm Queue" dialog and button classes (design.css). */

const AlertDialog = AlertDialogPrimitive.Root;
const AlertDialogTrigger = AlertDialogPrimitive.Trigger;

function AlertDialogContent({
  className,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Content>) {
  return (
    <AlertDialogPrimitive.Portal>
      <AlertDialogPrimitive.Overlay className="dialog-overlay" />
      <AlertDialogPrimitive.Content
        data-slot="alert-dialog-content"
        className={cn("dialog", className)}
        {...props}
      />
    </AlertDialogPrimitive.Portal>
  );
}

function AlertDialogTitle({
  children,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Title>) {
  return (
    <AlertDialogPrimitive.Title asChild {...props}>
      <h2>{children}</h2>
    </AlertDialogPrimitive.Title>
  );
}

const AlertDialogDescription = AlertDialogPrimitive.Description;

function AlertDialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("rowbtns", className)} {...props} />;
}

function AlertDialogAction({
  className,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Action>) {
  return <AlertDialogPrimitive.Action className={cn("btn danger", className)} {...props} />;
}

function AlertDialogCancel({
  className,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Cancel>) {
  return <AlertDialogPrimitive.Cancel className={cn("btn", className)} {...props} />;
}

export {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogTrigger,
};
