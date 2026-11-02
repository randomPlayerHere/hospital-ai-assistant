"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert, Badge, Button, Card, Empty, ErrorState, Field, Spinner, useAsync } from "@/components/ui";
import { api, download, errorMessage, unwrap, type Schemas } from "@/lib/api";

export default function AdminPatientsPage() {
  const [q, setQ] = useState("");
  const [queryTerm, setQueryTerm] = useState("");
  const [msg, setMsg] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [busyActionId, setBusyActionId] = useState<string | null>(null);

  const patients = useAsync(
    async () =>
      unwrap(
        await api.GET("/api/patients", {
          params: { query: { q: queryTerm || undefined, size: 50 } },
        }),
      ),
    [queryTerm],
  );

  async function handleExport(p: Schemas["PatientOut"]) {
    try {
      setBusyActionId(p.id);
      setMsg(null);
      await download(
        `/api/admin/patients/${p.id}/export`,
        `patient_${p.last_name.toLowerCase()}_${p.id}_export.json`,
      );
      setMsg({ kind: "success", text: `Exported full record for ${p.first_name} ${p.last_name}.` });
    } catch (err) {
      setMsg({ kind: "error", text: (err as Error).message });
    } finally {
      setBusyActionId(null);
    }
  }

  async function handleDelete(p: Schemas["PatientOut"]) {
    try {
      setBusyActionId(p.id);
      setMsg(null);
      const res = await api.POST("/api/admin/patients/{patient_id}/deletion-request", {
        params: { path: { patient_id: p.id } },
      });
      if (res.data) {
        setMsg({
          kind: "success",
          text: `Processed erasure request for ${p.first_name} ${p.last_name}: account disabled and patient soft-deleted.`,
        });
        setConfirmDeleteId(null);
        patients.reload();
      } else {
        setMsg({ kind: "error", text: errorMessage(res.error) });
      }
    } catch (err) {
      setMsg({ kind: "error", text: (err as Error).message });
    } finally {
      setBusyActionId(null);
    }
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">Patients &amp; Data Privacy</h1>
      </div>

      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}

      <Card title="Search & Data Governance">
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setQueryTerm(q);
          }}
        >
          <Field
            label="Name, phone or patient ID"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="max-w-md"
          />
          <Button type="submit">Search</Button>
          {queryTerm && (
            <Button
              variant="secondary"
              type="button"
              onClick={() => {
                setQ("");
                setQueryTerm("");
              }}
            >
              Clear
            </Button>
          )}
        </form>
        <p className="mt-2 text-xs text-slate-600">
          Provides GDPR/HIPAA compliance controls: full data exports and formal erasure requests.
        </p>
      </Card>

      <Card title={queryTerm ? `Search results for "${queryTerm}"` : "All patients"}>
        {patients.loading ? (
          <Spinner />
        ) : patients.error ? (
          <ErrorState error={patients.error} retry={patients.reload} />
        ) : (patients.data?.items ?? []).length === 0 ? (
          <Empty>No patients found.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Patient records</caption>
              <thead>
                <tr className="text-left text-slate-700 border-b">
                  <th scope="col" className="pb-2">Name</th>
                  <th scope="col" className="pb-2">DOB</th>
                  <th scope="col" className="pb-2">Phone</th>
                  <th scope="col" className="pb-2">Insurance</th>
                  <th scope="col" className="pb-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {patients.data?.items.map((p) => {
                  const isBusy = busyActionId === p.id;
                  const isConfirming = confirmDeleteId === p.id;

                  return (
                    <tr key={p.id} className="py-2">
                      <td className="py-2.5 font-medium">
                        <Link
                          href={`/admin/patients/${p.id}`}
                          className="text-blue-800 underline hover:text-blue-900"
                        >
                          {p.first_name} {p.last_name}
                        </Link>
                      </td>
                      <td>{p.date_of_birth}</td>
                      <td>{p.phone ?? "—"}</td>
                      <td>
                        {p.insurance_provider ? (
                          <span>
                            {p.insurance_provider} <Badge tone="blue">{p.insurance_id_masked}</Badge>
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="text-right">
                        <div className="inline-flex flex-wrap items-center justify-end gap-1.5">
                          <Button
                            variant="secondary"
                            disabled={isBusy}
                            onClick={() => handleExport(p)}
                            aria-label={`Export data for ${p.first_name} ${p.last_name}`}
                          >
                            Export JSON
                          </Button>

                          {isConfirming ? (
                            <div className="inline-flex items-center gap-1 bg-red-50 p-1 rounded border border-red-200">
                              <span className="text-xs text-red-800 font-semibold px-1">Confirm erasure?</span>
                              <Button
                                variant="danger"
                                disabled={isBusy}
                                onClick={() => handleDelete(p)}
                              >
                                {isBusy ? "Processing…" : "Yes, delete"}
                              </Button>
                              <Button
                                variant="secondary"
                                disabled={isBusy}
                                onClick={() => setConfirmDeleteId(null)}
                              >
                                Cancel
                              </Button>
                            </div>
                          ) : (
                            <Button
                              variant="danger"
                              disabled={isBusy}
                              onClick={() => setConfirmDeleteId(p.id)}
                              aria-label={`Request deletion for ${p.first_name} ${p.last_name}`}
                            >
                              Erasure request
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
