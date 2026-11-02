"use client";

import { useState } from "react";
import { Alert, Button, Card, Field } from "@/components/ui";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function MFAPage() {
  const { user, reloadMe } = useAuth();

  // Setup / Enable states
  const [setupData, setSetupData] = useState<{ secret: string; otpauth_url: string } | null>(null);
  const [enableCode, setEnableCode] = useState("");

  // Disable states
  const [disablePassword, setDisablePassword] = useState("");
  const [disableCode, setDisableCode] = useState("");

  // UI state
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function startSetup() {
    setError(null);
    setSuccess(null);
    setBusy(true);
    try {
      const res = unwrap(await api.POST("/api/auth/mfa/setup"));
      setSetupData(res);
    } catch (err) {
      setError(errorMessage({ detail: (err as Error).message }));
    } finally {
      setBusy(false);
    }
  }

  async function submitEnable(e: React.FormEvent) {
    e.preventDefault();
    if (!setupData) return;
    setError(null);
    setSuccess(null);
    setBusy(true);
    try {
      await api.POST("/api/auth/mfa/enable", {
        body: { secret: setupData.secret, code: enableCode.trim() },
      });
      setSetupData(null);
      setEnableCode("");
      setSuccess("Two-factor authentication has been enabled successfully.");
      await reloadMe();
    } catch (err) {
      setError(errorMessage({ detail: (err as Error).message }));
    } finally {
      setBusy(false);
    }
  }

  async function submitDisable(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setBusy(true);
    try {
      await api.POST("/api/auth/mfa/disable", {
        body: { password: disablePassword, code: disableCode.trim() },
      });
      setDisablePassword("");
      setDisableCode("");
      setSuccess("Two-factor authentication has been disabled.");
      await reloadMe();
    } catch (err) {
      setError(errorMessage({ detail: (err as Error).message }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-lg p-6">
      <h1 className="mb-4 text-2xl font-bold">Two-Factor Authentication (MFA)</h1>

      {error && <div className="mb-4"><Alert kind="error">{error}</Alert></div>}
      {success && <div className="mb-4"><Alert kind="success">{success}</Alert></div>}

      <Card>
        {user?.mfa_enabled ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-700 font-semibold">
              <span className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-600"></span>
              Two-factor authentication is currently enabled.
            </div>
            <p className="text-sm text-slate-600">
              Your account is protected with a time-based one-time password (TOTP) from your authenticator app.
            </p>

            <hr className="my-4 border-slate-200" />

            <h2 className="text-lg font-semibold text-rose-800">Disable Two-Factor Authentication</h2>
            <p className="text-sm text-slate-600">
              Enter your current account password and a valid 6-digit authenticator code to turn off 2FA.
            </p>

            <form onSubmit={submitDisable} className="space-y-3">
              <Field
                label="Account password"
                type="password"
                required
                value={disablePassword}
                onChange={(e) => setDisablePassword(e.target.value)}
              />
              <Field
                label="Current 6-digit code"
                type="text"
                inputMode="numeric"
                maxLength={6}
                required
                placeholder="123456"
                value={disableCode}
                onChange={(e) => setDisableCode(e.target.value)}
              />
              <Button type="submit" disabled={busy} className="bg-rose-700 hover:bg-rose-800 text-white">
                {busy ? "Disabling…" : "Disable 2FA"}
              </Button>
            </form>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-amber-700 font-semibold">
              <span className="inline-block h-2.5 w-2.5 rounded-full bg-amber-500"></span>
              Two-factor authentication is not enabled.
            </div>
            <p className="text-sm text-slate-600">
              Add an extra layer of security to your hospital account by requiring a 6-digit code from an
              authenticator app (such as Google Authenticator, Authy, 1Password, or Bitwarden) during login.
            </p>

            {!setupData ? (
              <Button onClick={startSetup} disabled={busy}>
                {busy ? "Generating…" : "Set up Authenticator App"}
              </Button>
            ) : (
              <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                <h2 className="text-md font-semibold">1. Configure your authenticator app</h2>
                <p className="text-xs text-slate-600">
                  Open your authenticator app and enter the secret key manually or click the link below:
                </p>
                <div className="rounded bg-white p-2 font-mono text-xs break-all border border-slate-300 select-all">
                  {setupData.secret}
                </div>
                <div className="text-xs">
                  <a
                    href={setupData.otpauth_url}
                    className="text-blue-800 underline"
                  >
                    Open in default authenticator app
                  </a>
                </div>

                <h2 className="text-md font-semibold pt-2">2. Verify 6-digit code</h2>
                <p className="text-xs text-slate-600">
                  Enter the code displayed in your authenticator app to confirm setup:
                </p>

                <form onSubmit={submitEnable} className="space-y-3">
                  <Field
                    label="Verification code"
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    required
                    placeholder="123456"
                    value={enableCode}
                    onChange={(e) => setEnableCode(e.target.value)}
                  />
                  <div className="flex gap-2">
                    <Button type="submit" disabled={busy}>
                      {busy ? "Verifying…" : "Enable 2FA"}
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => setSetupData(null)}
                      disabled={busy}
                    >
                      Cancel
                    </Button>
                  </div>
                </form>
              </div>
            )}
          </div>
        )}
      </Card>
    </main>
  );
}
