/**
 * 缺陷字典面板（契约 §4.1，D5）。
 * 列表（code/中文名/风险档/别称/启停）+ 新增与编辑 + 停用/启用 + 发布字典（预览 label config XML）
 * + 发布历史（D5 收尾 #1：版本/时间/发布人/条目快照）。
 * 权限：新增/编辑/停启用 = `datasets.update`（operator 起可写，前端按码显隐）；
 * 发布 = `datasets.publish`（admin+）。
 * 样式：语义 token + 共享常量（aoi/uiTokens），暗色自动适配。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Button, ToastType, useToast } from "@humansignal/ui";
import { Spinner } from "../../components/Spinner/Spinner";
import { aoiFetch } from "../../aoi/api";
import { usePerms } from "../../aoi/usePerms";
import {
  badge,
  CARD,
  EMPTY,
  ERROR_BOX,
  HINT,
  INPUT,
  LOADING,
  SECTION_TITLE,
  TABLE,
  TABLE_BODY_CELL,
  TABLE_HEAD_CELL,
  TABLE_ROW,
} from "../../aoi/uiTokens";

const DEFECTS_QUERY_KEY = ["aoi", "defects"];
const VERSIONS_QUERY_KEY = ["aoi", "defect-versions"];
const RISK_LABELS = { 1: "低", 2: "中", 3: "高" };
const RISK_BADGE_KIND = { 1: "positive", 2: "primary", 3: "negative" };

const formatTime = (value) => (value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—");

const EMPTY_FORM = { code: "", name_cn: "", risk_level: "1", aliases: "", active: true };

const DefectForm = ({ initial, editing, busy, onSubmit, onCancel }) => {
  const [form, setForm] = useState(initial);
  const set = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));

  return (
    <form
      className={`${CARD} mb-4 flex flex-wrap items-end gap-3 p-4`}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          code: form.code.trim(),
          name_cn: form.name_cn.trim(),
          risk_level: Number(form.risk_level),
          aliases: form.aliases
            .split(/[,，;；]/)
            .map((alias) => alias.trim())
            .filter(Boolean),
          active: form.active,
        });
      }}
    >
      <label className="flex flex-col gap-1 text-xs text-neutral-content-subtle">
        code（&lt;对象&gt;_&lt;缺陷类型&gt;_NN，如 panel_scratch_01）
        <input
          className={`${INPUT} w-56`}
          placeholder="panel_scratch_01"
          value={form.code}
          onChange={set("code")}
          readOnly={editing}
          required
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-neutral-content-subtle">
        中文名称
        <input className={`${INPUT} w-40`} placeholder="划伤" value={form.name_cn} onChange={set("name_cn")} required />
      </label>
      <label className="flex flex-col gap-1 text-xs text-neutral-content-subtle">
        风险档
        <select className={INPUT} value={form.risk_level} onChange={set("risk_level")}>
          <option value="1">低风险</option>
          <option value="2">中风险</option>
          <option value="3">高风险</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-neutral-content-subtle">
        别称（逗号分隔，可空）
        <input className={`${INPUT} w-56`} placeholder="别名1,别名2" value={form.aliases} onChange={set("aliases")} />
      </label>
      <div className="flex gap-2">
        <Button type="submit" size="compact" disabled={busy}>
          {editing ? "保存" : "新增"}
        </Button>
        <Button type="button" size="compact" look="outlined" disabled={busy} onClick={onCancel}>
          取消
        </Button>
      </div>
    </form>
  );
};

export const DefectsPanel = () => {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { has } = usePerms();
  const [formState, setFormState] = useState(null); // null | {mode: 'create'} | {mode: 'edit', code}
  const [published, setPublished] = useState(null); // {version, label_config, projects_synced}
  const [expandedVersion, setExpandedVersion] = useState(null); // 展开快照的版本 id
  const [showAllVersions, setShowAllVersions] = useState(false); // 发布历史：默认只显示最新一条

  const onError = (error) => toast.show({ message: error.message, type: ToastType.error });
  const invalidateDefects = () => queryClient.invalidateQueries({ queryKey: DEFECTS_QUERY_KEY });

  const defectsQuery = useQuery({
    queryKey: DEFECTS_QUERY_KEY,
    queryFn: () => aoiFetch("/api/datasets/defects?page_size=200"),
  });
  // D5 收尾 #1：发布历史（此前只写库不可见）
  const versionsQuery = useQuery({
    queryKey: VERSIONS_QUERY_KEY,
    queryFn: () => aoiFetch("/api/datasets/defects/versions?page_size=50"),
  });

  const saveDefect = useMutation({
    mutationFn: (payload) =>
      formState?.mode === "edit"
        ? aoiFetch("/api/datasets/defects", { method: "PUT", body: JSON.stringify(payload) })
        : aoiFetch("/api/datasets/defects", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => {
      invalidateDefects();
      setFormState(null);
    },
    onError,
  });
  const toggleActive = useMutation({
    mutationFn: (defect) =>
      aoiFetch("/api/datasets/defects", {
        method: "PUT",
        body: JSON.stringify({ code: defect.code, active: !defect.active }),
      }),
    onSuccess: invalidateDefects,
    onError,
  });
  const publish = useMutation({
    mutationFn: () => aoiFetch("/api/datasets/defects/publish", { method: "POST", body: JSON.stringify({}) }),
    onSuccess: (data) => {
      setPublished(data);
      queryClient.invalidateQueries({ queryKey: VERSIONS_QUERY_KEY });
      toast.show({ message: `字典 ${data.version} 已发布`, type: ToastType.success });
    },
    onError,
  });

  const defects = defectsQuery.data?.items ?? [];
  const versions = versionsQuery.data?.items ?? [];
  // 最新一条常显（且在第一条），其余默认折叠 —— 发布次数多了列表不会淹没页面
  const visibleVersions = showAllVersions ? versions : versions.slice(0, 1);
  const canWrite = has("datasets.update");
  const canPublish = has("datasets.publish");
  const busy = saveDefect.isPending || toggleActive.isPending || publish.isPending;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {canWrite ? (
          <Button size="compact" disabled={busy} onClick={() => setFormState({ mode: "create" })}>
            新增缺陷
          </Button>
        ) : null}
        {canPublish ? (
          <Button size="compact" look="outlined" disabled={busy} onClick={() => publish.mutate()}>
            发布字典
          </Button>
        ) : null}
      </div>

      {formState ? (
        <DefectForm
          editing={formState.mode === "edit"}
          initial={
            formState.mode === "edit"
              ? {
                  ...EMPTY_FORM,
                  ...defects.find((defect) => defect.code === formState.code),
                  aliases: (defects.find((defect) => defect.code === formState.code)?.aliases ?? []).join(","),
                  risk_level: String(defects.find((defect) => defect.code === formState.code)?.risk_level ?? 1),
                }
              : EMPTY_FORM
          }
          busy={busy}
          onSubmit={(payload) => saveDefect.mutate(payload)}
          onCancel={() => setFormState(null)}
        />
      ) : null}

      {defectsQuery.isLoading ? (
        <div className={LOADING}>
          <Spinner /> 加载中…
        </div>
      ) : defectsQuery.isError ? (
        <div className={ERROR_BOX}>缺陷字典加载失败：{defectsQuery.error.message}</div>
      ) : (
        <div className={`${CARD} overflow-hidden`}>
          <table className={TABLE}>
            <thead className="bg-neutral-surface-inset">
              <tr>
                <th className={TABLE_HEAD_CELL}>code</th>
                <th className={TABLE_HEAD_CELL}>中文名称</th>
                <th className={TABLE_HEAD_CELL}>风险档</th>
                <th className={TABLE_HEAD_CELL}>别称</th>
                <th className={TABLE_HEAD_CELL}>状态</th>
                {canWrite ? <th className={TABLE_HEAD_CELL}>操作</th> : null}
              </tr>
            </thead>
            <tbody>
              {defects.map((defect) => (
                <tr key={defect.code} className={TABLE_ROW}>
                  <td className={`${TABLE_BODY_CELL} font-mono text-xs`}>{defect.code}</td>
                  <td className={TABLE_BODY_CELL}>{defect.name_cn}</td>
                  <td className={TABLE_BODY_CELL}>
                    {badge(
                      RISK_BADGE_KIND[defect.risk_level] ?? "neutral",
                      RISK_LABELS[defect.risk_level] ?? defect.risk_level,
                    )}
                  </td>
                  <td className={`${TABLE_BODY_CELL} text-neutral-content-subtle`}>
                    {defect.aliases.join("、") || "—"}
                  </td>
                  <td className={TABLE_BODY_CELL}>
                    {defect.active ? badge("positive", "启用") : badge("neutral", "停用")}
                  </td>
                  {canWrite ? (
                    <td className={TABLE_BODY_CELL}>
                      <div className="flex gap-2">
                        <Button
                          size="compact"
                          look="outlined"
                          disabled={busy}
                          onClick={() => setFormState({ mode: "edit", code: defect.code })}
                        >
                          编辑
                        </Button>
                        <Button
                          size="compact"
                          look="outlined"
                          disabled={busy}
                          onClick={() => toggleActive.mutate(defect)}
                        >
                          {defect.active ? "停用" : "启用"}
                        </Button>
                      </div>
                    </td>
                  ) : null}
                </tr>
              ))}
              {!defects.length ? (
                <tr>
                  <td className={EMPTY} colSpan={6}>
                    暂无缺陷条目，请先新增。
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}

      {published ? (
        <div className={`${CARD} mt-5 p-5`}>
          <div className="mb-2 flex items-center gap-2">
            <h3 className={SECTION_TITLE}>已发布字典版本：{published.version}</h3>
            {badge("positive", `已同步 ${published.projects_synced ?? 0} 个标注项目`)}
          </div>
          <p className={`${HINT} mb-2`}>
            生成的 label config（value=code 不变，html=中文展示名，已回写到已建标注项目）：
          </p>
          <pre className="overflow-x-auto rounded-lg bg-neutral-surface-inset p-4 font-mono text-xs leading-5 text-neutral-content-subtle">
            {published.label_config}
          </pre>
          <div className="mt-3">
            <Button size="compact" look="outlined" onClick={() => setPublished(null)}>
              关闭
            </Button>
          </div>
        </div>
      ) : null}

      <div className={`${CARD} mt-5 overflow-hidden`}>
        <div className="flex flex-wrap items-center justify-between gap-2 p-4">
          <h3 className={SECTION_TITLE}>发布历史</h3>
          <div className="flex items-center gap-2">
            <span className={HINT}>{versionsQuery.isLoading ? "加载中…" : `共 ${versions.length} 版（最新在前）`}</span>
            {versions.length > 1 ? (
              <Button size="compact" look="outlined" onClick={() => setShowAllVersions((prev) => !prev)}>
                {showAllVersions ? "收起历史版本" : `展开其余 ${versions.length - 1} 版`}
              </Button>
            ) : null}
          </div>
        </div>
        {versionsQuery.isError ? (
          <div className={`${ERROR_BOX} m-4`}>发布历史加载失败：{versionsQuery.error.message}</div>
        ) : (
          <table className={TABLE}>
            <thead className="bg-neutral-surface-inset">
              <tr>
                <th className={TABLE_HEAD_CELL}>版本</th>
                <th className={TABLE_HEAD_CELL}>发布时间</th>
                <th className={TABLE_HEAD_CELL}>发布人</th>
                <th className={TABLE_HEAD_CELL}>缺陷数</th>
                <th className={TABLE_HEAD_CELL}>操作</th>
              </tr>
            </thead>
            <tbody>
              {visibleVersions.map((version) => (
                <Fragment key={version.id}>
                  <tr className={TABLE_ROW}>
                    <td className={`${TABLE_BODY_CELL} font-mono text-xs`}>
                      {version.version} {version.is_latest ? badge("positive", "最新") : null}
                    </td>
                    <td className={TABLE_BODY_CELL}>{formatTime(version.published_at)}</td>
                    <td className={TABLE_BODY_CELL}>{version.published_by_name ?? "—"}</td>
                    <td className={TABLE_BODY_CELL}>{version.defect_count}</td>
                    <td className={TABLE_BODY_CELL}>
                      <Button
                        size="compact"
                        look="outlined"
                        onClick={() => setExpandedVersion(expandedVersion === version.id ? null : version.id)}
                      >
                        {expandedVersion === version.id ? "收起快照" : "查看快照"}
                      </Button>
                    </td>
                  </tr>
                  {expandedVersion === version.id ? (
                    <tr>
                      <td colSpan={5} className="bg-neutral-surface-inset p-4">
                        <table className={TABLE}>
                          <thead>
                            <tr>
                              <th className={TABLE_HEAD_CELL}>索引</th>
                              <th className={TABLE_HEAD_CELL}>code</th>
                              <th className={TABLE_HEAD_CELL}>中文名</th>
                              <th className={TABLE_HEAD_CELL}>颜色</th>
                            </tr>
                          </thead>
                          <tbody>
                            {version.labels.map((label) => (
                              <tr key={label.code} className={TABLE_ROW}>
                                <td className={TABLE_BODY_CELL}>{label.index}</td>
                                <td className={`${TABLE_BODY_CELL} font-mono text-xs`}>{label.code}</td>
                                <td className={TABLE_BODY_CELL}>{label.name_cn ?? "—"}</td>
                                <td className={TABLE_BODY_CELL}>
                                  <span
                                    className="inline-block h-3 w-6 rounded-sm align-middle"
                                    style={{ background: label.color ?? "#cccccc" }}
                                  />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
              {!versions.length && !versionsQuery.isLoading ? (
                <tr>
                  <td className={EMPTY} colSpan={5}>
                    暂无发布记录，点击「发布字典」生成第一版。
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
