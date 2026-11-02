"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Card, Empty, ErrorState, Field, Spinner, useAsync } from "@/components/ui";
import { api, errorMessage, unwrap } from "@/lib/api";
import { todayLocal } from "@/lib/time";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
type Win = { weekday: number; start_time: string; end_time: string };

function SlotConfig({
  doctorId,
  initialMinutes,
  onUpdated,
}: {
  doctorId: string;
  initialMinutes: number;
  onUpdated: () => void;
}) {
  const [minutes, setMinutes] = useState(initialMinutes);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    setMinutes(initialMinutes);
  }, [initialMinutes]);

  return (
    <Card title="Appointment slot duration">
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setSaving(true);
          setMsg(null);
          const res = await api.PUT("/api/doctors/{doctor_id}/slot-config", {
            params: { path: { doctor_id: doctorId } },
            body: { slot_minutes: Number(minutes) },
          });
          setSaving(false);
          if (res.data) {
            setMsg({ kind: "success", text: `Slot duration updated to ${res.data.slot_minutes} minutes.` });
            onUpdated();
          } else {
            setMsg({ kind: "error", text: errorMessage(res.error) });
          }
        }}
      >
        <div>
          <label htmlFor="slot-minutes" className="block text-sm font-medium">
            Slot duration
          </label>
          <select
            id="slot-minutes"
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
            className="mt-1 rounded border border-slate-500 px-3 py-2 text-sm"
          >
            {[10, 15, 20, 30, 45, 60].map((m) => (
              <option key={m} value={m}>
                {m} minutes
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save slot duration"}
        </Button>
      </form>
      <p className="mt-2 text-xs text-slate-600">
        Controls how free bookable slots are partitioned across your working hours.
      </p>
    </Card>
  );
}

export default function AvailabilityPage() {
  const me = useAsync(async () => unwrap(await api.GET("/api/doctors/me")), []);
  const id = me.data?.id;
  const avail = useAsync(
    async () =>
      id
        ? unwrap(
            await api.GET("/api/doctors/{doctor_id}/availability", { params: { path: { doctor_id: id } } }),
          )
        : [],
    [id],
  );
  const exc = useAsync(
    async () =>
      id
        ? unwrap(
            await api.GET("/api/doctors/{doctor_id}/exceptions", { params: { path: { doctor_id: id } } }),
          )
        : [],
    [id],
  );
  const [draft, setDraft] = useState<Win[] | null>(null);
  const [msg, setMsg] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [leave, setLeave] = useState({ start_date: todayLocal(), end_date: todayLocal(), reason: "" });

  if (me.loading || avail.loading) return <Spinner />;
  if (me.error || !id) return <ErrorState error={me.error} retry={me.reload} />;
  const windows: Win[] =
    draft ??
    (avail.data ?? []).map((a) => ({
      weekday: a.weekday,
      start_time: a.start_time.slice(0, 5),
      end_time: a.end_time.slice(0, 5),
    }));
  const set = (i: number, patch: Partial<Win>) =>
    setDraft(windows.map((w, j) => (j === i ? { ...w, ...patch } : w)));

  return (
    <>
      <h1 className="text-2xl font-bold">Availability &amp; leave</h1>
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}

      <SlotConfig
        doctorId={id}
        initialMinutes={me.data?.slot_minutes ?? 30}
        onUpdated={me.reload}
      />

      <Card
        title="Weekly schedule"
        actions={
          <Button
            variant="secondary"
            onClick={() => setDraft([...windows, { weekday: 0, start_time: "09:00", end_time: "17:00" }])}
          >
            Add window
          </Button>
        }
      >
        {windows.length === 0 ? (
          <Empty>No working hours set. Patients cannot book you until you add some.</Empty>
        ) : (
          <ul className="space-y-2">
            {windows.map((w, i) => (
              <li key={i} className="flex flex-wrap items-end gap-2">
                <div>
                  <label htmlFor={`day-${i}`} className="block text-sm font-medium">
                    Day
                  </label>
                  <select
                    id={`day-${i}`}
                    value={w.weekday}
                    onChange={(e) => set(i, { weekday: Number(e.target.value) })}
                    className="mt-1 rounded border border-slate-500 px-2 py-2 text-sm"
                  >
                    {DAYS.map((d, n) => (
                      <option key={d} value={n}>
                        {d}
                      </option>
                    ))}
                  </select>
                </div>
                <Field
                  label="From"
                  type="time"
                  value={w.start_time}
                  onChange={(e) => set(i, { start_time: e.target.value })}
                />
                <Field
                  label="To"
                  type="time"
                  value={w.end_time}
                  onChange={(e) => set(i, { end_time: e.target.value })}
                />
                <Button
                  variant="secondary"
                  aria-label={`Remove window ${i + 1}`}
                  onClick={() => setDraft(windows.filter((_, j) => j !== i))}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex gap-2">
          <Button
            onClick={async () => {
              const res = await api.PUT("/api/doctors/{doctor_id}/availability", {
                params: { path: { doctor_id: id } },
                body: windows.map((w) => ({
                  ...w,
                  start_time: `${w.start_time}:00`,
                  end_time: `${w.end_time}:00`,
                })),
              });
              if (res.data) {
                setMsg({ kind: "success", text: "Schedule saved." });
                setDraft(null);
                avail.reload();
              } else setMsg({ kind: "error", text: errorMessage(res.error) });
            }}
          >
            Save schedule
          </Button>
          {draft && (
            <Button variant="secondary" onClick={() => setDraft(null)}>
              Reset
            </Button>
          )}
        </div>
      </Card>
      <Card title="Scheduled leave / exceptions">
        <form
          className="grid gap-3 md:grid-cols-4"
          onSubmit={async (e) => {
            e.preventDefault();
            const res = await api.POST("/api/doctors/{doctor_id}/exceptions", {
              params: { path: { doctor_id: id } },
              body: {
                start_date: leave.start_date,
                end_date: leave.end_date,
                reason: leave.reason || null,
              },
            });
            if (res.data) {
              setMsg({ kind: "success", text: "Leave added." });
              setLeave({ start_date: todayLocal(), end_date: todayLocal(), reason: "" });
              exc.reload();
            } else setMsg({ kind: "error", text: errorMessage(res.error) });
          }}
        >
          <Field
            label="From"
            type="date"
            required
            value={leave.start_date}
            onChange={(e) => setLeave({ ...leave, start_date: e.target.value })}
          />
          <Field
            label="To"
            type="date"
            required
            value={leave.end_date}
            onChange={(e) => setLeave({ ...leave, end_date: e.target.value })}
          />
          <Field
            label="Reason"
            value={leave.reason}
            onChange={(e) => setLeave({ ...leave, reason: e.target.value })}
          />
          <Button type="submit">Add leave</Button>
        </form>
        {(exc.data ?? []).length === 0 ? (
          <Empty>No leave scheduled.</Empty>
        ) : (
          <ul className="mt-3 divide-y text-sm">
            {exc.data?.map((x) => (
              <li key={x.id} className="flex items-center justify-between py-2">
                <span>
                  {x.start_date} to {x.end_date}
                  {x.reason ? ` · ${x.reason}` : ""}
                </span>
                <Button
                  variant="secondary"
                  onClick={async () => {
                    await api.DELETE("/api/doctors/{doctor_id}/exceptions/{exc_id}", {
                      params: { path: { doctor_id: id, exc_id: x.id } },
                    });
                    exc.reload();
                  }}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
