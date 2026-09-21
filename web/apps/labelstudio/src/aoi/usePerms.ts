/**
 * 当前用户的 aoi 角色/权限点（`GET /api/core/permissions`，契约 §3.1）。
 * 供 Menubar 与页面按 `perms` 显隐（H23）；请求失败视为无权限（fail-closed）。
 */
import { useQuery } from "@tanstack/react-query";
import { aoiFetch } from "./api";

export type AoiPerms = {
  user_id: number;
  roles: string[];
  perms: string[];
};

export const aoiPermsQueryKey = ["aoi", "perms"];

export const usePerms = () => {
  const query = useQuery({
    queryKey: aoiPermsQueryKey,
    queryFn: () => aoiFetch<AoiPerms>("/api/core/permissions"),
    staleTime: 30_000,
    retry: 1,
  });

  const perms = query.data?.perms ?? [];
  const roles = query.data?.roles ?? [];

  return {
    ...query,
    perms,
    roles,
    has: (code: string) => perms.includes(code),
  };
};
