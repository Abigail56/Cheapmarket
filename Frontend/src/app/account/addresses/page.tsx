"use client";

import { useCallback, useEffect, useState } from "react";

import { PinIcon, PlusIcon } from "@/components/icons";
import { Alert, EmptyState, Field, PageLoading, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { localPhone, money } from "@/lib/format";
import type { Address, AddressInput, Zone } from "@/lib/types";
import { useToast } from "@/providers/toast";

const BLANK: AddressInput = {
  label: "Home",
  street: "",
  landmark: "",
  city: "",
  state: "",
  phone: "",
  zone_id: null,
  is_default: false,
};

export default function AddressesPage() {
  const toast = useToast();
  const [addresses, setAddresses] = useState<Address[] | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [editing, setEditing] = useState<Address | "new" | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const [a, z] = await Promise.all([
        api<Address[]>("/users/me/addresses"),
        api<Zone[]>("/delivery-zones", { auth: false }),
      ]);
      setAddresses(a);
      setZones(z.filter((x) => x.is_active));
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    void load(); // eslint-disable-line react-hooks/set-state-in-effect -- fetch on mount
  }, [load]);

  if (error) return <EmptyState title="Couldn't load your addresses">Please refresh the page.</EmptyState>;
  if (!addresses) return <PageLoading />;

  const zoneName = (id: string | null) => zones.find((z) => z.id === id)?.name;

  async function remove(a: Address) {
    if (!window.confirm(`Delete “${a.label}”?`)) return;
    try {
      await api(`/users/me/addresses/${a.id}`, { method: "DELETE" });
      toast("Address deleted");
      await load();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Couldn't delete", "error");
    }
  }

  async function makeDefault(a: Address) {
    try {
      await api(`/users/me/addresses/${a.id}`, { method: "PATCH", body: { is_default: true } });
      await load();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Couldn't update", "error");
    }
  }

  if (editing) {
    return (
      <AddressForm
        initial={editing === "new" ? { ...BLANK, is_default: addresses.length === 0 } : editing}
        id={editing === "new" ? null : editing.id}
        zones={zones}
        onDone={async (saved) => {
          setEditing(null);
          if (saved) {
            toast("Address saved");
            await load();
          }
        }}
      />
    );
  }

  return (
    <div className="space-y-4">
      {!addresses.length ? (
        <EmptyState
          title="No saved addresses"
          action={
            <button type="button" className="btn-primary" onClick={() => setEditing("new")}>
              <PlusIcon width={18} height={18} /> Add an address
            </button>
          }
        >
          You can choose a saved address at checkout.
        </EmptyState>
      ) : (
        <>
          <ul className="grid gap-4 md:grid-cols-2">
            {addresses.map((a) => (
              <li key={a.id} className="card flex flex-col gap-3 p-5">
                <div className="flex items-start justify-between gap-2">
                  <p className="flex items-center gap-2 font-bold text-slate-900">
                    <PinIcon width={18} height={18} className="text-brand-600" /> {a.label}
                  </p>
                  {a.is_default && (
                    <span className="rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold text-brand-800">
                      Default
                    </span>
                  )}
                </div>
                <p className="text-sm text-slate-700">
                  {[a.street, a.landmark, a.city, a.state].filter(Boolean).join(", ")}
                </p>
                <p className="text-xs text-slate-500">
                  {zoneName(a.zone_id) ? `Zone: ${zoneName(a.zone_id)}` : "No delivery zone set"}
                  {a.phone ? ` · ${localPhone(a.phone)}` : ""}
                </p>
                <div className="mt-auto flex flex-wrap gap-2 pt-2">
                  <button type="button" className="btn-secondary px-3 py-1.5" onClick={() => setEditing(a)}>
                    Edit
                  </button>
                  {!a.is_default && (
                    <button type="button" className="btn-ghost px-3 py-1.5" onClick={() => makeDefault(a)}>
                      Make default
                    </button>
                  )}
                  <button type="button" className="btn-ghost px-3 py-1.5 text-red-600" onClick={() => remove(a)}>
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <button type="button" className="btn-secondary" onClick={() => setEditing("new")}>
            <PlusIcon width={18} height={18} /> Add another address
          </button>
        </>
      )}
    </div>
  );
}

function AddressForm({
  initial,
  id,
  zones,
  onDone,
}: {
  initial: AddressInput;
  id: string | null;
  zones: Zone[];
  onDone: (saved: boolean) => void;
}) {
  const [form, setForm] = useState<AddressInput>({ ...initial, phone: localPhone(initial.phone) });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set =
    (k: keyof AddressInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setForm((f) => ({ ...f, [k]: e.target.value }));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const v: Record<string, string> = {};
    if (form.street.trim().length < 3) v.street = "Enter the street address";
    if (form.city.trim().length < 2) v.city = "Enter the city or area";
    if (form.state.trim().length < 2) v.state = "Enter the state";
    if (!form.zone_id) v.zone_id = "Choose the delivery zone";
    setErrors(v);
    if (Object.keys(v).length) return;
    setBusy(true);
    setError("");
    const body = {
      label: form.label.trim() || "Home",
      street: form.street.trim(),
      landmark: form.landmark?.trim() || null,
      city: form.city.trim(),
      state: form.state.trim(),
      phone: form.phone?.trim() || null,
      zone_id: form.zone_id || null,
      is_default: form.is_default,
    };
    try {
      await api(id ? `/users/me/addresses/${id}` : "/users/me/addresses", { method: id ? "PATCH" : "POST", body });
      onDone(true);
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fields);
      setError(err instanceof Error ? err.message : "Couldn't save the address");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="card space-y-4 p-5" noValidate>
      <h2 className="text-lg font-bold">{id ? "Edit address" : "New address"}</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Label" htmlFor="a-label" hint="e.g. Home, Office, Mum's place">
          <input id="a-label" className="input" maxLength={50} value={form.label} onChange={set("label")} />
        </Field>
        <Field label="Phone for this address (optional)" htmlFor="a-phone">
          <input id="a-phone" className="input" type="tel" inputMode="tel" value={form.phone ?? ""} onChange={set("phone")} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Street address" htmlFor="a-street" error={errors.street}>
            <input id="a-street" className="input" value={form.street} onChange={set("street")} autoComplete="street-address" />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Landmark (optional)" htmlFor="a-landmark">
            <input id="a-landmark" className="input" value={form.landmark ?? ""} onChange={set("landmark")} />
          </Field>
        </div>
        <Field label="City / area" htmlFor="a-city" error={errors.city}>
          <input id="a-city" className="input" value={form.city} onChange={set("city")} />
        </Field>
        <Field label="State" htmlFor="a-state" error={errors.state}>
          <input id="a-state" className="input" value={form.state} onChange={set("state")} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Delivery zone" htmlFor="a-zone" error={errors.zone_id}>
            <select id="a-zone" className="input" value={form.zone_id ?? ""} onChange={set("zone_id")}>
              <option value="">Choose…</option>
              {zones.map((z) => (
                <option key={z.id} value={z.id}>
                  {z.name}: {money(z.delivery_fee)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700 sm:col-span-2">
          <input
            type="checkbox"
            className="h-4 w-4 accent-brand-600"
            checked={form.is_default}
            onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))}
          />
          Use as my default address
        </label>
      </div>
      {error && <Alert>{error}</Alert>}
      <div className="flex gap-3">
        <button className="btn-primary" disabled={busy}>
          {busy && <Spinner className="h-4 w-4" />}
          Save address
        </button>
        <button type="button" className="btn-ghost" onClick={() => onDone(false)} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}
