"use client";

import { HostingTable } from "@/components/HostingTable";

export default function HostingPage() {
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Hosting accounts</h1>
          <p>Hosting subscriptions, their expiration dates and the domains that depend on them.</p>
        </div>
      </div>
      <HostingTable />
    </>
  );
}
