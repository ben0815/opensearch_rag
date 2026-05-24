import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Spinner } from "react-bootstrap";

import { auth } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";
import { useInstanceStore } from "@/stores/instanceStore";
import { usePreferencesStore } from "@/stores/preferencesStore";
import { user as userApi } from "@/api/client";

import AppShell from "@/components/AppShell";
import LoginPage from "@/pages/LoginPage";
import ChatPage from "@/pages/ChatPage";
import DocumentsPage from "@/pages/DocumentsPage";
import HistoryPage from "@/pages/HistoryPage";

// Admin pages — lazy to keep initial bundle small
import { lazy, Suspense } from "react";
const AdminLayout = lazy(() => import("@/pages/admin/AdminLayout"));
const AdminUsersPage = lazy(() => import("@/pages/admin/AdminUsersPage"));
const AdminGroupsPage = lazy(() => import("@/pages/admin/AdminGroupsPage"));
const AdminInstancesPage = lazy(() => import("@/pages/admin/AdminInstancesPage"));
const AdminSettingsPage = lazy(() => import("@/pages/admin/AdminSettingsPage"));
const AdminLdapPage = lazy(() => import("@/pages/admin/AdminLdapPage"));
const AdminStatusPage = lazy(() => import("@/pages/admin/AdminStatusPage"));
const AdminAuditPage = lazy(() => import("@/pages/admin/AdminAuditPage"));
const AdminMaintenancePage = lazy(() => import("@/pages/admin/AdminMaintenancePage"));

function AuthGuard({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AdminGuard({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!user?.is_global_admin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  const { setUser } = useAuthStore();
  const { setInstances } = useInstanceStore();
  const { applyTheme, setLanguage } = usePreferencesStore();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    applyTheme();
    // Restore session from cookie
    auth
      .me()
      .then(async (me) => {
        setUser(me);
        if (me.preferences?.language) setLanguage(me.preferences.language);
        try {
          const instances = await userApi.instances();
          setInstances(instances);
        } catch {
          /* instances unavailable — user stays logged in with empty list */
        }
        // Apply default instance preference
        if (me.default_instance_id) {
          useInstanceStore.getState().setSelectedId(me.default_instance_id);
        }
      })
      .catch(() => {
        /* not logged in — stays null */
      })
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="d-flex vh-100 align-items-center justify-content-center">
        <Spinner animation="border" variant="primary" />
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Suspense
        fallback={
          <div className="d-flex vh-100 align-items-center justify-content-center">
            <Spinner animation="border" variant="primary" />
          </div>
        }
      >
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          <Route
            element={
              <AuthGuard>
                <AppShell />
              </AuthGuard>
            }
          >
            <Route index element={<Navigate to="/chat" replace />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="history" element={<HistoryPage />} />

            <Route
              path="admin"
              element={
                <AdminGuard>
                  <AdminLayout />
                </AdminGuard>
              }
            >
              <Route index element={<Navigate to="status" replace />} />
              <Route path="status" element={<AdminStatusPage />} />
              <Route path="users" element={<AdminUsersPage />} />
              <Route path="groups" element={<AdminGroupsPage />} />
              <Route path="instances" element={<AdminInstancesPage />} />
              <Route path="settings" element={<AdminSettingsPage />} />
              <Route path="ldap" element={<AdminLdapPage />} />
              <Route path="audit" element={<AdminAuditPage />} />
              <Route path="maintenance" element={<AdminMaintenancePage />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
