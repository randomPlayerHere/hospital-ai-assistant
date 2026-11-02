"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, Badge, Button, Card, Empty, ErrorState, Spinner, useAsync } from "@/components/ui";
import { api, download, errorMessage, unwrap } from "@/lib/api";
import { fmtDateTime } from "@/lib/time";

export default function AdminPatientDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [msg, setMsg] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const data = useAsync(async () => {
    const [p, docs, timeline] = await Promise.all([
      api.GET("/api/patients/{patient_id}", { params: { path: { patient_id: id } } }).then(unwrap),
      api.GET("/api/patients/{patient_id}/documents", { params: { path: { patient_id: id } } }).then(unwrap),
      api.GET("/api/patients/{patient_id}/timeline", { params: { path: { patient_id: id } } }).then(unwrap),
    ]);
    return { p, docs, timeline };
  }, [id]);

  if (data.loading && !data.data) return <Spinner />;
  if (data.error || !data.data) return <ErrorState error={data.error} retry={data.reload} />;
  const { p, docs, timeline } = data.data;

  async function handleExport() {
    try {
      setBusy(true);
      setMsg(null);
      await download(
        `/api/admin/patients/${id}/export`,
        `patient_${p.last_name.toLowerCase()}_${id}_export.json`,
      );
      setMsg({ kind: "success", text: "Patient record exported successfully." });
    } catch (err) {
      setMsg({ kind: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    try {
      setBusy(true);
      setMsg(null);
      const res = await api.POST("/api/admin/patients/{patient_id}/deletion-request", {
        params: { path: { patient_id: id } },
      });
      if (res.data) {
        setMsg({
          kind: "success",
          text: "Erasure request processed: patient soft-deleted and portal user account deactivated.",
        });
        setConfirmDelete(false);
        data.reload();
      } else {
        setMsg({ kind: "error", text: errorMessage(res.error) });
      }
    } catch (err) {
      setMsg({ kind: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Link href="/admin/patients" className="text-xs font-medium text-blue-800 underline">
            ← Back to patients
          </Link>
          <h1 className="text-2xl font-bold mt-1">
            {p.first_name} {p.last_name}
          </h1>
        </div>
      </div>

      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}

      <Card title="GDPR &amp; HIPAA Data Subject Controls">
        <p className="mb-3 text-sm text-slate-700">
          Admin compliance operations for right-to-access and right-to-be-forgotten requests.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" disabled={busy} onClick={handleExport}>
            {busy ? "Exporting…" : "Export complete record (JSON)"}
          </Button>

          {confirmDelete ? (
            <div className="inline-flex items-center gap-2 rounded border border-red-300 bg-red-50 p-2 text-sm">
              <span className="font-semibold text-red-900">Confirm erasure request?</span>
              <Button variant="danger" disabled={busy} onClick={handleDelete}>
                {busy ? "Processing…" : "Yes, soft delete & deactivate"}
              </Button>
              <Button variant="secondary" disabled={busy} onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button variant="danger" disabled={busy} onClick={() => setConfirmDelete(true)}>
              Process deletion request
            </Button>
          )}
        </div>
      </Card>

      <Card title="Demographics">
        <dl className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
          <div>
            <dt className="text-slate-600">Date of birth</dt>
            <dd>{p.date_of_birth}</dd>
          </div>
          <div>
            <dt className="text-slate-600">Phone</dt>
            <dd>{p.phone ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-slate-600">Email</dt>
            <dd>{p.email ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-slate-600">Blood group</dt>
            <dd>{p.blood_group ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-slate-600">Allergies</dt>
            <dd>{p.allergies?.join(", ") || "None recorded"}</dd>
          </div>
          <div>
            <dt className="text-slate-600">Insurance</dt>
            <dd>
              {p.insurance_provider ?? "—"} {p.insurance_id_masked}
            </dd>
          </div>
          <div>
            <dt className="text-slate-600">Emergency contact</dt>
            <dd>
              {p.emergency_contact_name ?? "—"} {p.emergency_contact_phone}
            </dd>
          </div>
        </dl>
      </Card>

      <Card title="Documents">
        {docs.length === 0 ? (
          <Empty>No documents on file.</Empty>
        ) : (
          <ul className="divide-y text-sm">
            {docs.map((d) => (
              <li key={d.id} className="py-2">
                {d.filename} <Badge>{d.doc_type}</Badge> · {fmtDateTime(d.created_at)}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Timeline">
        {timeline.length === 0 ? (
          <Empty>No activity recorded.</Empty>
        ) : (
          <ol className="space-y-1 text-sm">
            {timeline.map((e) => (
              <li key={`${e.kind}-${e.id}`}>
                {fmtDateTime(e.at)} · {e.title}
              </li>
            ))}
          </ol>
        )}
      </Card>
    </>
  );
}
