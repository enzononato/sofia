import { Suspense } from "react";
import { InboxLayout } from "@/components/inbox/inbox-layout";

export default function InboxPage() {
  return (
    <Suspense fallback={null}>
      <InboxLayout />
    </Suspense>
  );
}
