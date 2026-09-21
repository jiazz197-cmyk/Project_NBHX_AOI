/**
 * 数据集面板（契约 §4.1，D5 收尾第四轮重设计）。
 *
 * 两件事：
 * 1) 新建向导 = 一张「作业单」：① 名称 ② 字典来源 ③ 图片（可拖入，本地缩略图逐张可移除），
 *    建完立即发导入；结果用三个大数字（成功/重复/坏图）说话，不用彩色横幅。
 * 2) 数据集账本：一行一个数据集（名称 + 图片数 + 版本 + 标注入口 + 草稿版本/删除）。
 *
 * 颜色纪律（见 Datasets.prefix.css 顶部）：页面 chrome 只用宿主中性 token，
 * 全部彩色来自缺陷字典自身（发布快照带 color；草稿态未定色就不画色块）。
 * 字典来源 `dict_source`：latest_published（缺省）/ active_defects（草稿语义）。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ToastType, useToast } from "@humansignal/ui";
import { AoiButton } from "./AoiButton";
import { Spinner } from "../../components/Spinner/Spinner";
import { confirm } from "../../components/Modal/Modal";
import { aoiFetch } from "../../aoi/api";
import { usePerms } from "../../aoi/usePerms";
import { useDatasetImport } from "./useDatasetImport";

const DATASETS_QUERY_KEY = ["aoi", "datasets"];
const VERSIONS_QUERY_KEY = ["aoi", "defect-versions", "latest"];
const ACTIVE_DEFECTS_QUERY_KEY = ["aoi", "defects", "active"];
const ACCEPT = "image/jpeg,image/png,image/bmp";

/** 字典条目 chips：有 color 才画色块（草稿态未定色就不假装有颜色） */
const DictChips = ({ labels, max = 6 }) => {
  const shown = labels.slice(0, max);
  const rest = labels.length - shown.length;
  return (
    <div className="aoi-ds__chips">
      {shown.map((label) => (
        <span key={label.code} className="aoi-ds__chip">
          {label.color ? <i style={{ background: label.color }} /> : null}
          {label.name_cn ?? label.code}
        </span>
      ))}
      {rest > 0 ? <span className="aoi-ds__chip">+{rest}</span> : null}
    </div>
  );
};

export const DatasetsPanel = ({ onDatasetReady, openSignal = 0 }) => {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { has } = usePerms();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [dictSource, setDictSource] = useState("latest_published");
  const [stationCode, setStationCode] = useState("");
  const [files, setFiles] = useState([]);
  const [previews, setPreviews] = useState([]);
  const [dragOver, setDragOver] = useState(false);
  const [created, setCreated] = useState(null);
  const fileInputRef = useRef(null);

  const onError = (error) => toast.show({ message: error.message, type: ToastType.error });
  const invalidateDatasets = () => queryClient.invalidateQueries({ queryKey: DATASETS_QUERY_KEY });

  const datasetsQuery = useQuery({
    queryKey: DATASETS_QUERY_KEY,
    queryFn: () => aoiFetch("/api/datasets?page_size=200"),
  });
  // 向导第②步：最新已发布版本 + 当前启用缺陷（判断两种来源是否可用）
  const versionsQuery = useQuery({
    queryKey: VERSIONS_QUERY_KEY,
    queryFn: () => aoiFetch("/api/datasets/defects/versions?page_size=1"),
    enabled: wizardOpen,
  });
  const activeDefectsQuery = useQuery({
    queryKey: ACTIVE_DEFECTS_QUERY_KEY,
    queryFn: () => aoiFetch("/api/datasets/defects?active=true&page_size=200"),
    enabled: wizardOpen,
  });
  const latestVersion = versionsQuery.data?.items?.[0] ?? null;
  const activeDefects = activeDefectsQuery.data?.items ?? [];

  const { startImport, isImporting, isPolling, job, reset: resetImport } = useDatasetImport();

  // 页头「新建数据集」按钮 → 直接展开向导
  useEffect(() => {
    if (openSignal > 0) {
      setWizardOpen(true);
      setCreated(null);
    }
  }, [openSignal]);

  // 本地预览：objectURL 生命周期跟随 files（替换/卸载时释放，避免泄漏）
  useEffect(() => {
    const urls = files.map((file) => ({ file, url: URL.createObjectURL(file) }));
    setPreviews(urls);
    return () => urls.forEach((item) => URL.revokeObjectURL(item.url));
  }, [files]);

  const addFiles = (incoming) => {
    const list = Array.from(incoming ?? []).filter((file) => ACCEPT.split(",").includes(file.type));
    if (!list.length) return;
    setFiles((prev) => [...prev, ...list]);
  };

  const createDataset = useMutation({
    mutationFn: ({ name, source }) =>
      aoiFetch("/api/datasets", { method: "POST", body: JSON.stringify({ name, dict_source: source }) }),
    onSuccess: (dataset) => {
      toast.show({
        message: `数据集「${dataset.name}」已创建（字典 ${dataset.dict_version}）`,
        type: ToastType.info,
      });
      invalidateDatasets();
      setCreated(dataset);
      if (files.length) startImport({ datasetId: dataset.id, stationCode, files });
    },
    onError,
  });

  const createVersion = useMutation({
    mutationFn: (datasetId) =>
      aoiFetch(`/api/datasets/${datasetId}/versions`, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: (version) => {
      toast.show({ message: `草稿版本 ${version.version} 已创建`, type: ToastType.info });
      invalidateDatasets();
    },
    onError,
  });
  const deleteDataset = useMutation({
    mutationFn: (datasetId) => aoiFetch(`/api/datasets/${datasetId}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.show({ message: "数据集已删除（标注项目、任务与图片一并清理）", type: ToastType.info });
      invalidateDatasets();
    },
    onError,
  });

  const datasets = datasetsQuery.data?.items ?? [];
  const canCreate = has("datasets.create");
  const canUpdate = has("datasets.update");
  const busy = createDataset.isPending || createVersion.isPending || deleteDataset.isPending;

  const closeWizard = () => {
    setWizardOpen(false);
    setNewName("");
    setDictSource("latest_published");
    setStationCode("");
    setFiles([]);
    setCreated(null);
    resetImport();
  };

  const dictOptions = [
    {
      key: "latest_published",
      available: Boolean(latestVersion),
      title: latestVersion ? `最新已发布版本 ${latestVersion.version}` : "暂无已发布版本",
      meta: latestVersion
        ? `${latestVersion.defect_count} 个缺陷 · 发布人 ${latestVersion.published_by_name ?? "—"}`
        : "先去「发布缺陷字典」发一版，或选右边的草稿",
      chips: latestVersion?.labels ?? [],
    },
    {
      key: "active_defects",
      available: Boolean(activeDefects.length),
      title: "当前启用缺陷（草稿）",
      meta: activeDefects.length
        ? `${activeDefects.length} 个启用缺陷 · 字典还没定版时用`
        : "当前没有启用缺陷，先去「发布缺陷字典」新增",
      chips: activeDefects.map((item) => ({ code: item.code, name_cn: item.name_cn })),
    },
  ];

  return (
    <div>
      {canCreate && !wizardOpen ? (
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <p className="m-0 max-w-2xl text-xs leading-5 text-neutral-content-subtle">
            还没有目标数据集就先建一个：命名 → 选字典 →（可选）直接拖入图片，创建时自动生成标注项目。
          </p>
          <AoiButton onClick={() => setWizardOpen(true)}>新建数据集</AoiButton>
        </div>
      ) : null}

      {canCreate && wizardOpen ? (
        <div className="aoi-ds__wizard mb-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-semibold text-neutral-content">新建数据集</span>
            <AoiButton onClick={closeWizard}>{created ? "关闭" : "取消"}</AoiButton>
          </div>

          <div className="aoi-ds__wizard-row">
            <span className="aoi-ds__wizard-key">
              <span>01</span> 名称
            </span>
            <div className="aoi-ds__wizard-body">
              <input
                className="w-full max-w-md rounded-md border border-neutral-border bg-neutral-surface px-3 py-1.5 text-sm text-neutral-content outline-none placeholder:text-neutral-content-subtlest focus:border-primary-border-bold"
                placeholder="如 产线A-外观检测-批次01"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                disabled={Boolean(created)}
              />
            </div>
          </div>

          <div className="aoi-ds__wizard-row">
            <span className="aoi-ds__wizard-key">
              <span>02</span> 字典
            </span>
            <div className="aoi-ds__wizard-body">
              <div className="aoi-ds__dicts" role="radiogroup" aria-label="缺陷字典来源">
                {dictOptions.map((option) => {
                  const on = dictSource === option.key;
                  return (
                    <div
                      key={option.key}
                      role="radio"
                      aria-checked={on}
                      aria-disabled={!option.available}
                      tabIndex={option.available && !created ? 0 : -1}
                      className={`aoi-ds__dict${on ? " aoi-ds__dict--on" : ""}${
                        option.available ? "" : " aoi-ds__dict--off"
                      }`}
                      onClick={() => !created && option.available && setDictSource(option.key)}
                      onKeyDown={(event) => {
                        if (!created && option.available && (event.key === "Enter" || event.key === " ")) {
                          event.preventDefault();
                          setDictSource(option.key);
                        }
                      }}
                    >
                      <div className="min-w-0">
                        <div className="aoi-ds__dict-title">{option.title}</div>
                        <div className="aoi-ds__dict-meta">{option.meta}</div>
                        {option.chips.length ? <DictChips labels={option.chips} /> : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="aoi-ds__wizard-row">
            <span className="aoi-ds__wizard-key">
              <span>03</span> 图片
            </span>
            <div className="aoi-ds__wizard-body">
              {created ? (
                <div className="aoi-ds__stage">
                  <div className="aoi-ds__stage-inner">
                    <div className="aoi-ds__stage-head">
                      <span className="aoi-ds__stage-label">
                        数据集「{created.name}」已创建 · 字典 {created.dict_version} · 标注项目 {created.ls_project_id}
                      </span>
                      <span className="aoi-ds__stage-note">
                        {isImporting || isPolling ? "导入中" : job ? "导入结束" : "未选图片"}
                      </span>
                    </div>

                    {isImporting || isPolling ? (
                      <div className="aoi-ds__scan" role="progressbar" aria-label="图片导入中" />
                    ) : job ? (
                      <div className="aoi-ds__score">
                        <div className="aoi-ds__score-item">
                          <span className="aoi-ds__score-num">{job.ok}</span>
                          <span className="aoi-ds__score-key">成功登记</span>
                        </div>
                        <div className="aoi-ds__score-item">
                          <span className="aoi-ds__score-num aoi-ds__score-num--muted">{job.dup}</span>
                          <span className="aoi-ds__score-key">重复跳过</span>
                        </div>
                        <div className="aoi-ds__score-item">
                          <span className="aoi-ds__score-num aoi-ds__score-num--muted">{job.bad}</span>
                          <span className="aoi-ds__score-key">坏图</span>
                        </div>
                        <div className="aoi-ds__score-item">
                          <span className="aoi-ds__score-num aoi-ds__score-num--muted">{job.total}</span>
                          <span className="aoi-ds__score-key">合计文件</span>
                        </div>
                      </div>
                    ) : (
                      <p className="mt-3 mb-0 text-xs text-neutral-content-subtle">
                        没有选图片也可以先建好数据集，稍后到「传图片」批量导入。
                      </p>
                    )}

                    <div className="mt-4">
                      <AoiButton
                        kind="primary"
                        disabled={isImporting || isPolling}
                        onClick={() => {
                          const datasetId = created.id;
                          closeWizard();
                          onDatasetReady?.(datasetId);
                        }}
                      >
                        去看图库
                      </AoiButton>
                    </div>
                  </div>
                </div>
              ) : (
                <>
                  {/* 台面：拖入或点击选择；本地缩略图逐张可移除 */}
                  <div
                    className={`aoi-ds__stage${dragOver ? " aoi-ds__stage--over" : ""}`}
                    onDragOver={(event) => {
                      event.preventDefault();
                      setDragOver(true);
                    }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={(event) => {
                      event.preventDefault();
                      setDragOver(false);
                      addFiles(event.dataTransfer.files);
                    }}
                  >
                    <div className="aoi-ds__stage-inner">
                      <div className="aoi-ds__stage-head">
                        <span className="aoi-ds__stage-label">待导入</span>
                        <span className="aoi-ds__stage-note">
                          {files.length ? `${files.length} 个文件` : "支持 jpg / png / bmp"}
                        </span>
                      </div>

                      <button type="button" className="aoi-ds__drop" onClick={() => fileInputRef.current?.click()}>
                        <span className="aoi-ds__drop-title">把图片拖到这里</span>
                        <span className="aoi-ds__drop-hint">或点击选择文件 · 可多选，也支持整批拖入</span>
                      </button>
                      <input
                        ref={fileInputRef}
                        type="file"
                        multiple
                        accept={ACCEPT}
                        className="hidden"
                        onChange={(event) => {
                          addFiles(event.target.files);
                          event.target.value = "";
                        }}
                      />

                      {previews.length ? (
                        <div className="aoi-ds__strip">
                          {previews.map((item, index) => (
                            <figure key={`${item.file.name}-${index}`} className="aoi-ds__frame m-0">
                              <img src={item.url} alt={item.file.name} />
                              <button
                                type="button"
                                className="aoi-ds__frame-remove"
                                aria-label={`移除 ${item.file.name}`}
                                onClick={() => setFiles((prev) => prev.filter((_, i) => i !== index))}
                              >
                                ×
                              </button>
                              <figcaption className="aoi-ds__frame-name" title={item.file.name}>
                                {item.file.name}
                              </figcaption>
                            </figure>
                          ))}
                        </div>
                      ) : null}

                      <div className="aoi-ds__controls">
                        <label className="aoi-ds__field">
                          工位编号（可选）
                          <input
                            placeholder="如 ST-01"
                            value={stationCode}
                            onChange={(event) => setStationCode(event.target.value)}
                          />
                        </label>
                      </div>
                    </div>
                  </div>

                  <div className="mt-3">
                    <AoiButton
                      kind="primary"
                      disabled={busy || !newName.trim()}
                      onClick={() => createDataset.mutate({ name: newName.trim(), source: dictSource })}
                    >
                      {createDataset.isPending
                        ? "创建中…"
                        : files.length
                          ? `创建并导入 ${files.length} 张`
                          : "创建数据集"}
                    </AoiButton>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {datasetsQuery.isLoading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-neutral-content-subtle">
          <Spinner /> 加载中…
        </div>
      ) : datasetsQuery.isError ? (
        <div className="rounded-lg border border-negative-border bg-negative-surface px-4 py-3 text-sm text-negative-content">
          数据集列表加载失败：{datasetsQuery.error.message}
        </div>
      ) : datasets.length ? (
        <div className="aoi-ds__ledger">
          {datasets.map((dataset) => (
            <div key={dataset.id} className="aoi-ds__row">
              <div className="min-w-0">
                <div className="aoi-ds__row-name">{dataset.name ?? `dataset-${dataset.id}`}</div>
                <div className="aoi-ds__row-meta">
                  <span>#{dataset.id}</span>
                  <span>{dataset.image_count ?? 0} 张图片</span>
                  <span>{dataset.cur_version ? `当前版本 ${dataset.cur_version}` : "当前为草稿"}</span>
                  <span>
                    {dataset.versions?.length
                      ? `${dataset.versions.length} 个版本 · 最新 ${
                          dataset.versions[dataset.versions.length - 1].version
                        }`
                      : "暂无版本"}
                  </span>
                </div>
              </div>
              <div className="aoi-ds__row-actions">
                {dataset.ls_project_id ? (
                  <a
                    className="inline-flex items-center rounded-md border border-neutral-border-subtle px-3 py-1.5 text-xs text-neutral-content no-underline hover:bg-neutral-surface-hover"
                    href={`/projects/${dataset.ls_project_id}/data`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    去标注
                  </a>
                ) : null}
                {canUpdate ? (
                  <>
                    <AoiButton
                      disabled={busy}
                      onClick={() =>
                        confirm({
                          title: "新建草稿版本",
                          body: `为数据集「${dataset.name ?? dataset.id}」创建新的草稿版本？版本号自动生成，划分与统计随发布流程推进。`,
                          okText: "创建",
                          onOk: () => createVersion.mutate(dataset.id),
                        })
                      }
                    >
                      新建草稿版本
                    </AoiButton>
                    <AoiButton
                      kind="danger"
                      disabled={busy}
                      onClick={() =>
                        confirm({
                          title: "删除数据集",
                          body: `确认删除数据集「${dataset.name ?? dataset.id}」？其标注项目、任务与已导入图片会被一并清理，此操作不可恢复。`,
                          okText: "删除",
                          onOk: () => deleteDataset.mutate(dataset.id),
                        })
                      }
                    >
                      删除
                    </AoiButton>
                  </>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="aoi-ds__empty">
          <p className="aoi-ds__empty-title m-0">还没有数据集</p>
          <p className="mt-2 mb-4 text-xs">数据集是图片、标注和版本的家；建好之后就能往里面导图片了。</p>
          {canCreate ? (
            <AoiButton kind="primary" onClick={() => setWizardOpen(true)}>
              新建数据集
            </AoiButton>
          ) : null}
        </div>
      )}
    </div>
  );
};
