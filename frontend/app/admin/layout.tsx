import { RoleShell } from "@/components/Shell";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleShell
      role="admin"
      title="Administration"
      nav={[
        { href: "/admin", label: "Dashboard" },
        { href: "/admin/patients", label: "Patients & Privacy" },
        { href: "/admin/users", label: "Users" },
        { href: "/admin/audit", label: "Audit logs" },
      ]}
    >
      {children}
    </RoleShell>
  );
}
