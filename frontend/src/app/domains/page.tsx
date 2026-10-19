"use client";

import { DomainTable } from "@/components/DomainTable";

export default function DomainsPage() {
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Domains</h1>
          <p>Every registered domain, its hosting assignment, expiration and monitoring state.</p>
        </div>
      </div>
      <DomainTable />
    </>
  );
}
