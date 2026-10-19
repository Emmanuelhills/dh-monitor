"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { DomainForm } from "@/components/DomainForm";
import { useToast } from "@/components/Toast";

export default function NewDomainPage() {
  const router = useRouter();
  const toast = useToast();
  return (
    <>
      <div className="page-header">
        <div>
          <div className="small"><Link href="/domains">← Domains</Link></div>
          <h1>Add domain</h1>
          <p>Automatic registration lookups start in the background after you save.</p>
        </div>
      </div>
      <div className="card">
        <div className="card-body">
          <DomainForm
            onCancel={() => router.back()}
            onSaved={(d) => {
              toast("success", `${d.display_name} added.`);
              router.replace(`/domains/${d.id}`);
            }}
          />
        </div>
      </div>
    </>
  );
}
