/**
 * 缺陷字典面板（契约 §4.1；D5 收尾第五轮统一视觉语言）。
 *
 * 结构：摘要行（启用数 / 最新发布）→ 条目账本（色块 + 中文名 + code + 风险 + 别称 + 启停）
 * → 发布历史（时间线，最新常显、其余可展开，快照以"色卡 chips"呈现）。
 * 编辑表单与新建向导同构（作业单三行：code / 名称 / 风险+别称）。
 *
 * 颜色纪律：条目色块取自**最新发布快照**（发布时才按 index 定色）；
 * 未发布或不在快照里的条目留空心占位——不假装有颜色。
 * 权限：新增/编辑/停启用 = `datasets.update`；发布 = `datasets.publish`（admin+）。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ToastType, useToast } from "@humansignal/ui";
import { AoiButton } from "./AoiButton";
import { Spinner } from "../../components/Spinner/Spinner";
import { aoiFetch } from "../../aoi/api";
import { usePerms } from "../../aoi/usePerms";
import { badge } from "../../aoi/uiTokens";

// 风险档＝色块与徽章同一套颜色（低=绿 / 中=橙 / 高=红）：用户看色块就要能读出风险
const RISK_SWATCH = {
  1: "var(--color-positive-surface)",
  2: "var(--color-warning-surface)",
  3: "var(--color-negative-surface)",
};

const DEFECTS_QUERY_KEY = ["aoi", "defects"];
const VERSIONS_QUERY_KEY = ["aoi", "defect-versions"];
const RISK_LABELS = { 1: "低", 2: "中", 3: "高" };
const RISK_BADGE_KIND = { 1: "positive", 2: "warning", 3: "negative" };
const FIELD =
  "w-full rounded-md border border-neutral-border bg-neutral-surface px-3 py-1.5 text-sm text-neutral-content outline-none placeholder:text-neutral-content-subtlest focus:border-primary-border-bold";

const formatTime = (value) => (value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—");

const EMPTY_FORM = { code: "", name_cn: "", risk_level: "1", aliases: "", active: true };

/** 色卡 chips：缺陷类别是页面上唯一允许的彩色 */
const LabelChips = ({ labels }) => (
  <div className="aoi-ds__snapshot-list">
    {labels.map((label) => (
      <span key={label.code} className="aoi-ds__chip">
        {label.color ? <i style={{ background: label.color }} /> : null}
        {label.name_cn ?? label.code}
        <span className="aoi-ds__defect-code">{label.code}</span>
      </span>
    ))}
  </div>
);

const DefectForm = ({ initial, editing, busy, onSubmit, onCancel }) => {
  const [form, setForm] = useState(initial);
  const set = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));

  return (
    <form
      className="aoi-ds__wizard mb-6"
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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold text-neutral-content">{editing ? "编辑缺陷" : "新增缺陷"}</span>
        <AoiButton type="button" disabled={busy} onClick={onCancel}>
          取消
        </AoiButton>
      </div>

      <div className="aoi-ds__wizard-row">
        <span className="aoi-ds__wizard-key">
          <span>01</span> code
        </span>
        <div className="aoi-ds__wizard-body">
          <input
            className={FIELD}
            placeholder="panel_scratch_01"
            value={form.code}
            onChange={set("code")}
            readOnly={editing}
            required
          />
          <p className="m-0 text-xs text-neutral-content-subtle">
            格式 &lt;对象&gt;_&lt;缺陷类型&gt;_NN，如 panel_scratch_01；编号 01~99。
            {editing ? " 已有条目的 code 不可修改（标注结果按 code 归档）。" : ""}
          </p>
        </div>
      </div>

      <div className="aoi-ds__wizard-row">
        <span className="aoi-ds__wizard-key">
          <span>02</span> 名称
        </span>
        <div className="aoi-ds__wizard-body">
          <input
            className={`${FIELD} max-w-xs`}
            placeholder="划伤"
            value={form.name_cn}
            onChange={set("name_cn")}
            required
          />
          <p className="m-0 text-xs text-neutral-content-subtle">中文名会显示在标注页的标签上（结果值仍是 code）。</p>
        </div>
      </div>

      <div className="aoi-ds__wizard-row">
        <span className="aoi-ds__wizard-key">
          <span>03</span> 风险与别称
        </span>
        <div className="aoi-ds__wizard-body">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-neutral-content-subtle">
              风险档（决定推荐阈值）
              <select className={`${FIELD} w-40`} value={form.risk_level} onChange={set("risk_level")}>
                <option value="1">低风险</option>
                <option value="2">中风险</option>
                <option value="3">高风险</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-neutral-content-subtle">
              别称（逗号分隔，可空）
              <input
                className={`${FIELD} w-64`}
                placeholder="别名1,别名2"
                value={form.aliases}
                onChange={set("aliases")}
              />
            </label>
          </div>
        </div>
      </div>

      <div className="mt-2">
        <AoiButton kind="primary" type="submit">
          {editing ? "保存" : "新增"}
        </AoiButton>
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
  const [expandedVersion, setExpandedVersion] = useState(null);
  const [showAllVersions, setShowAllVersions] = useState(false);

  const onError = (error) => toast.show({ message: error.message, type: ToastType.error });
  const invalidateDefects = () => queryClient.invalidateQueries({ queryKey: DEFECTS_QUERY_KEY });

  const defectsQuery = useQuery({
    queryKey: DEFECTS_QUERY_KEY,
    queryFn: () => aoiFetch("/api/datasets/defects?page_size=200"),
  });
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
  const visibleVersions = showAllVersions ? versions : versions.slice(0, 1);
  const latestVersion = versions[0] ?? null;
  const activeCount = defects.filter((defect) => defect.active).length;
  const canWrite = has("datasets.update");
  const canPublish = has("datasets.publish");
  const busy = saveDefect.isPending || toggleActive.isPending || publish.isPending;

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <p className="m-0 text-xs leading-5 text-neutral-content-subtle">
          字典决定标注页有哪些类别、以及训练时各类别的推荐阈值。
          {latestVersion
            ? ` 最新发布：${latestVersion.version}（${formatTime(latestVersion.published_at)}，${latestVersion.defect_count} 个类别）。`
            : " 还没有发布过：标注项目会用「当前启用缺陷」以草稿语义生成。"}
        </p>
        <div className="flex flex-wrap gap-2">
          {canWrite ? (
            <AoiButton disabled={busy} onClick={() => setFormState({ mode: "create" })}>
              新增缺陷
            </AoiButton>
          ) : null}
          {canPublish ? (
            <AoiButton kind="primary" disabled={busy} onClick={() => publish.mutate()}>
              {publish.isPending ? "发布中…" : "发布字典"}
            </AoiButton>
          ) : null}
        </div>
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

      {published ? (
        <div className="aoi-ds__wizard mb-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-semibold text-neutral-content">
              已发布 {published.version} · 回写 {published.projects_synced ?? 0} 个标注项目
            </span>
            <AoiButton onClick={() => setPublished(null)}>关闭</AoiButton>
          </div>
          <p className="mb-2 mt-3 text-xs text-neutral-content-subtle">
            value 是 code（结果值、导出、model.yaml 都不变），html 是中文展示名：
          </p>
          <pre className="aoi-ds__xml">{published.label_config}</pre>
        </div>
      ) : null}

      {defectsQuery.isLoading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-neutral-content-subtle">
          <Spinner /> 加载中…
        </div>
      ) : defectsQuery.isError ? (
        <div className="rounded-lg border border-negative-border bg-negative-surface px-4 py-3 text-sm text-negative-content">
          缺陷字典加载失败：{defectsQuery.error.message}
        </div>
      ) : defects.length ? (
        <>
          <div className="mb-2 flex flex-wrap items-baseline gap-3">
            <span className="text-xs tabular-nums text-neutral-content-subtle">
              共 {defects.length} 个类别 · 启用 {activeCount} 个
            </span>
            <span className="text-xs tabular-nums text-neutral-content-subtler">
              色块＝风险档（绿=低 / 橙=中 / 红=高）
            </span>
          </div>
          <div className="aoi-ds__ledger">
            {defects.map((defect) => (
              <div key={defect.code} className="aoi-ds__defect">
                <span
                  className="aoi-ds__defect-swatch"
                  style={{ background: RISK_SWATCH[defect.risk_level] ?? "var(--color-neutral-surface-inset)" }}
                  title={`风险 ${RISK_LABELS[defect.risk_level] ?? defect.risk_level}`}
                />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="aoi-ds__defect-name">{defect.name_cn}</span>
                    <span className="aoi-ds__defect-code">{defect.code}</span>
                  </div>
                  <div className="aoi-ds__defect-meta">
                    <span>风险 {RISK_LABELS[defect.risk_level] ?? defect.risk_level}</span>
                    <span>别称 {defect.aliases?.length ? defect.aliases.join("、") : "—"}</span>
                    <span>{defect.active ? "已启用" : "已停用"}</span>
                  </div>
                </div>
                <div className="aoi-ds__defect-actions">
                  {badge(RISK_BADGE_KIND[defect.risk_level] ?? "neutral", RISK_LABELS[defect.risk_level] ?? "—")}
                  {defect.active ? null : badge("neutral", "停用")}
                  {canWrite ? (
                    <>
                      <AoiButton disabled={busy} onClick={() => setFormState({ mode: "edit", code: defect.code })}>
                        编辑
                      </AoiButton>
                      <AoiButton disabled={busy} onClick={() => toggleActive.mutate(defect)}>
                        {defect.active ? "停用" : "启用"}
                      </AoiButton>
                    </>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="aoi-ds__empty">
          <p className="aoi-ds__empty-title m-0">字典还是空的</p>
          <p className="mt-2 mb-4 text-xs">
            先新增几个缺陷类别（code + 中文名 + 风险档），再发布；标注页的标签就是从这里来的。
          </p>
          {canWrite ? <AoiButton onClick={() => setFormState({ mode: "create" })}>新增缺陷</AoiButton> : null}
        </div>
      )}

      {/* 发布历史：最新常显在第一条，其余折叠 */}
      <div className="mt-8">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-semibold text-neutral-content">发布历史</span>
          <div className="flex items-center gap-2">
            <span className="text-xs tabular-nums text-neutral-content-subtle">
              {versionsQuery.isLoading ? "加载中…" : `共 ${versions.length} 版`}
            </span>
            {versions.length > 1 ? (
              <AoiButton onClick={() => setShowAllVersions((prev) => !prev)}>
                {showAllVersions ? "收起历史版本" : `展开其余 ${versions.length - 1} 版`}
              </AoiButton>
            ) : null}
          </div>
        </div>

        {versionsQuery.isError ? (
          <div className="rounded-lg border border-negative-border bg-negative-surface px-4 py-3 text-sm text-negative-content">
            发布历史加载失败：{versionsQuery.error.message}
          </div>
        ) : versions.length ? (
          <div className="aoi-ds__history">
            {visibleVersions.map((version) => (
              <div key={version.id}>
                <div className="aoi-ds__history-item">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="aoi-ds__history-version">{version.version}</span>
                      {version.is_latest ? badge("positive", "最新") : null}
                    </div>
                    <div className="aoi-ds__defect-meta">
                      <span>{formatTime(version.published_at)}</span>
                      <span>{version.published_by_name ?? "—"}</span>
                      <span>{version.defect_count} 个类别</span>
                    </div>
                  </div>
                  <AoiButton onClick={() => setExpandedVersion(expandedVersion === version.id ? null : version.id)}>
                    {expandedVersion === version.id ? "收起快照" : "查看快照"}
                  </AoiButton>
                </div>
                {expandedVersion === version.id ? (
                  <div className="aoi-ds__snapshot">
                    <LabelChips labels={version.labels} />
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="aoi-ds__empty">
            <p className="aoi-ds__empty-title m-0">还没有发布记录</p>
            <p className="mt-2 mb-0 text-xs">点「发布字典」生成第一版；发布后标注项目与模板会同步过去。</p>
          </div>
        )}
      </div>
    </div>
  );
};
