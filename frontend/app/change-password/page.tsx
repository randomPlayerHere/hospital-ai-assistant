"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Button, Card, Field, Spinner } from "@/components/ui";
import { HOME, api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function ChangePasswordPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
  }, [user, loading, router]);

  if (loading || !user) {
    return <Spinner label="Checking your session" />;
  }

  const homeHref = HOME[user.role] ?? "/login";

  return (
    <main className="mx-auto max-w-md p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Change password</h1>
        <Link href={homeHref} className="text-sm font-medium text-blue-800 underline">
          Back to portal
        </Link>
      </div>

      <Card>
        {success ? (
          <div className="space-y-4">
            <Alert kind="success">
              Password updated successfully. All existing sessions have been signed out.
            </Alert>
            <Button
              className="w-full"
              onClick={async () => {
                await logout();
                router.replace("/login");
              }}
            >
              Sign in with new password
            </Button>
          </div>
        ) : (
          <form
            className="space-y-4"
            onSubmit={async (e) => {
              e.preventDefault();
              setError(null);

              if (newPassword !== confirmPassword) {
                setError("New passwords do not match.");
                return;
              }

              if (currentPassword === newPassword) {
                setError("New password must be different from current password.");
                return;
              }

              setSubmitting(true);
              const res = await api.POST("/api/auth/change-password", {
                body: { current_password: currentPassword, new_password: newPassword },
              });
              setSubmitting(false);

              if (res.response.ok) {
                setSuccess(true);
              } else {
                setError(errorMessage(res.error));
              }
            }}
          >
            {error && <Alert kind="error">{error}</Alert>}

            <Field
              label="Current password"
              type="password"
              required
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />

            <Field
              label="New password"
              type="password"
              required
              minLength={12}
              maxLength={128}
              autoComplete="new-password"
              hint="At least 12 characters"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />

            <Field
              label="Confirm new password"
              type="password"
              required
              minLength={12}
              maxLength={128}
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />

            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? "Updating password…" : "Update password"}
            </Button>
          </form>
        )}
      </Card>
    </main>
  );
}
