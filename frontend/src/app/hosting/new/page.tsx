"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { HostingForm } from "@/components/HostingForm";
import { useToast } from "@/components/Toast";

export default function NewHostingPage() {
  const router = useRouter();
  const toast = useToast();
  return (
    <>
      <div className="page-header">
        <div>
          <div className="small"><Link href="/hosting">← Hosting accounts</Link></div>
          <h1>Add hosting account</h1>
          <p>Most providers don&apos;t publish subscription dates, so enter the expiration date manually unless an integration is configured.</p>
        </div>
      </div>
      <div className="card">
        <div className="card-body">
          <HostingForm
            onCancel={() => router.back()}
            onSaved={(h) => {
              toast("success", `${h.name} added.`);
              router.replace(`/hosting/${h.id}`);
            }}
          />
        </div>
      </div>
    </>
  );
}
