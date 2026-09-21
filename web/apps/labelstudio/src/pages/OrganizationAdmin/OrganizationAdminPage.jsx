/**
 * AOI 组织管理页（注入点 4 注册；契约 §3.1/§4.0，D5）。
 * 仅 super_admin（`system.users`）可用：任命/卸任管理员与操作员、禁用/启用用户。
 * 「删除用户」为停用组合拳（见契约 §3.1 停用语义），硬删不在平台语义内。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, ToastType, useToast } from "@humansignal/ui";
import { confirm } from "../../components/Modal/Modal";
import { aoiFetch } from "../../aoi/api";
import { usePerms } from "../../aoi/usePerms";

const ROLE_LABELS = {
  operator: "操作员",
  admin: "管理员",
  super_admin: "超级管理员",
};

const USERS_QUERY_KEY = ["aoi", "users"];
const th = { padding: "8px 12px", fontWeight: 600 };
const td = { padding: "8px 12px" };

const UserRow = ({ user, busy, onToggleRole, onToggleActive }) => {
  const isSuperAdmin = user.roles.includes("super_admin");

  return (
    <tr style={{ borderBottom: "1px solid #f0f0f0" }}>
      <td style={td}>{user.email}</td>
      <td style={td}>{user.is_active ? "正常" : "已禁用"}</td>
      <td style={td}>
        {user.roles.length ? user.roles.map((code) => ROLE_LABELS[code] ?? code).join("、") : "无角色"}
      </td>
      <td style={td}>
        {isSuperAdmin ? (
          "—"
        ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <Button size="compact" disabled={busy} onClick={() => onToggleRole(user, "admin")}>
              {user.roles.includes("admin") ? "取消管理员" : "设为管理员"}
            </Button>
            <Button size="compact" disabled={busy} onClick={() => onToggleRole(user, "operator")}>
              {user.roles.includes("operator") ? "取消操作员" : "设为操作员"}
            </Button>
            <Button
              size="compact"
              look="outlined"
              variant="negative"
              disabled={busy}
              onClick={() => onToggleActive(user)}
            >
              {user.is_active ? "禁用" : "启用"}
            </Button>
          </div>
        )}
      </td>
    </tr>
  );
};

export const OrganizationAdminPage = () => {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { has, isLoading: permsLoading } = usePerms();

  const usersQuery = useQuery({
    queryKey: USERS_QUERY_KEY,
    queryFn: () => aoiFetch("/api/core/users?page_size=200"),
    enabled: !permsLoading && has("system.users"),
  });

  const onError = (error) => toast.show({ message: error.message, type: ToastType.error });
  const invalidateUsers = () => queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY });

  const assignRoles = useMutation({
    mutationFn: ({ userId, roles }) =>
      aoiFetch(`/api/core/users/${userId}/roles`, { method: "POST", body: JSON.stringify({ roles }) }),
    onSuccess: invalidateUsers,
    onError,
  });
  const setActive = useMutation({
    mutationFn: ({ userId, active }) =>
      aoiFetch(`/api/core/users/${userId}/${active ? "activate" : "deactivate"}`, {
        method: "POST",
        body: "{}",
      }),
    onSuccess: invalidateUsers,
    onError,
  });

  const busy = assignRoles.isPending || setActive.isPending;

  const handleToggleRole = (user, code) => {
    const roles = user.roles.includes(code) ? user.roles.filter((item) => item !== code) : [...user.roles, code];
    assignRoles.mutate({ userId: user.id, roles });
  };

  const handleToggleActive = (user) => {
    const activate = () => setActive.mutate({ userId: user.id, active: !user.is_active });

    if (user.is_active) {
      confirm({
        title: "禁用用户",
        body: `确定禁用 ${user.email} 吗？该账号将立即失去访问权限（已签发的令牌同时失效），其角色会被清空；后续可重新启用并重新任命。`,
        okText: "禁用",
        buttonLook: "negative",
        onOk: activate,
      });
    } else {
      activate();
    }
  };

  if (permsLoading) {
    return (
      <div style={{ padding: 24 }}>
        <h2 style={{ marginBottom: 8 }}>Organization Admin</h2>
        <p style={{ color: "#8c8c8c" }}>加载中…</p>
      </div>
    );
  }

  if (!has("system.users")) {
    return (
      <div style={{ padding: 24 }}>
        <h2 style={{ marginBottom: 8 }}>Organization Admin</h2>
        <p style={{ color: "#8c8c8c" }}>无权访问此页面（需要超级管理员权限）。</p>
      </div>
    );
  }

  const users = usersQuery.data?.items ?? [];

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 8 }}>Organization Admin</h2>
      <p style={{ color: "#8c8c8c", marginBottom: 16 }}>
        管理平台账号：任命/卸任管理员与操作员、禁用或启用用户。超级管理员账号由系统维护，不在此页操作。
      </p>
      {usersQuery.isLoading ? (
        <p>加载中…</p>
      ) : usersQuery.isError ? (
        <p style={{ color: "#cf1322" }}>用户列表加载失败：{usersQuery.error.message}</p>
      ) : (
        <>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #d9d9d9" }}>
                <th style={th}>邮箱</th>
                <th style={th}>状态</th>
                <th style={th}>角色</th>
                <th style={th}>操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <UserRow
                  key={user.id}
                  user={user}
                  busy={busy}
                  onToggleRole={handleToggleRole}
                  onToggleActive={handleToggleActive}
                />
              ))}
            </tbody>
          </table>
          {usersQuery.data.total > users.length ? (
            <p style={{ color: "#8c8c8c", marginTop: 12 }}>
              仅显示前 {users.length} 个用户（共 {usersQuery.data.total} 个）。
            </p>
          ) : null}
        </>
      )}
    </div>
  );
};

OrganizationAdminPage.title = "Organization Admin";
OrganizationAdminPage.path = "/organization-admin";
