/**
 * 图片面板（契约 §4.1；D5 收尾第六轮：按数据集展示 + 统一样式按钮）。
 *
 * 两种视图：
 * 1) **概览（缺省）**：一个数据集一段——标题行（名称/图片数/当前版本）+ 最多 **5 张**小缩略图
 *    （不足 5 张就全展示，多出来的用 "+N" 块点开）+ 操作（查看全部 / 上传到这里 / 去标注）。
 *    图库回答的是"每个数据集里有什么"，而不是把全库图片摊平。
 * 2) **下钻**：单个数据集的完整 contact sheet（分页、QC 角标、悬停下载/删除、点图看原图）。
 *
 * 归属来自服务端（`image.dataset_id`，按导入前缀反查）；B 线复审回流图不属于任何数据集，
 * 单独一段「未归属数据集」。
 *
 * 上传台面（常暗）不变：拖入/点击 → 本地缩略图逐张可移除 → 选数据集与工位 → 导入。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { ToastType, useToast } from "@humansignal/ui";
import { Spinner } from "../../components/Spinner/Spinner";
import { confirm } from "../../components/Modal/Modal";
import { aoiFetch } from "../../aoi/api";
import { usePerms } from "../../aoi/usePerms";
import { AoiButton } from "./AoiButton";
import { IMAGES_QUERY_KEY, useDatasetImport } from "./useDatasetImport";

const DATASETS_QUERY_KEY = ["aoi", "datasets"];
const UNASSIGNED_QUERY_KEY = ["aoi", "images", "unassigned"];
const PAGE_SIZE = 48;
const ACCEPT = "image/jpeg,image/png,image/bmp";

/** 同源缩略图地址：与 `GET /images/{id}/download` 返回的 url 同一约定 */
const thumbSrc = (objectKey) => {
  if (!objectKey) return "";
  if (objectKey.startsWith("http")) return objectKey;
  return objectKey.startsWith("/") ? objectKey : `/data/${objectKey}`;
};

const formatBytes = (bytes) => {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const QC_LABEL = { ok: "合格", rejected: "坏图", pending: "待检" };
const SOURCE_LABEL = { manual_real: "人工导入", camera: "产线相机", reflux_review: "复审回流" };
const FIELD =
  "rounded-md border border-neutral-border bg-neutral-surface px-3 py-1.5 text-sm text-neutral-content outline-none placeholder:text-neutral-content-subtlest focus:border-primary-border-bold";

const flagKind = (qcStatus) =>
  qcStatus === "ok" ? " aoi-ds__tile-flag--ok" : qcStatus === "rejected" ? " aoi-ds__tile-flag--bad" : "";

/** 小缩略图（数据集概览用） */
const Mini = ({ image }) => {
  const [broken, setBroken] = useState(false);
  const src = thumbSrc(image.object_key);
  if (broken || !src) {
    return (
      <span className="aoi-ds__mini grid place-items-center" title={image.object_key}>
        <span className="text-xs" style={{ color: "var(--aoi-stage-ink-dim)" }}>
          无法预览
        </span>
      </span>
    );
  }
  return (
    <a
      className="aoi-ds__mini"
      href={src}
      target="_blank"
      rel="noreferrer"
      title={`${image.station_code ?? ""} 查看原图`}
    >
      <img
        className="aoi-ds__mini-img"
        src={src}
        alt={image.object_key}
        loading="lazy"
        onError={() => setBroken(true)}
      />
    </a>
  );
};

/** 大瓦片（下钻用） */
const Tile = ({ image, canWrite, onDownload, onDelete }) => {
  const [broken, setBroken] = useState(false);
  const src = thumbSrc(image.object_key);

  return (
    <figure className="aoi-ds__tile m-0">
      {broken || !src ? (
        <div
          className="aoi-ds__tile-img grid place-items-center text-xs"
          style={{ color: "var(--aoi-stage-ink-dim)" }}
          title={image.object_key}
        >
          无法预览
        </div>
      ) : (
        <a href={src} target="_blank" rel="noreferrer" title="查看原图">
          <img
            className="aoi-ds__tile-img"
            src={src}
            alt={image.object_key}
            loading="lazy"
            onError={() => setBroken(true)}
          />
        </a>
      )}

      <span className={`aoi-ds__tile-flag${flagKind(image.qc_status)}`}>
        {QC_LABEL[image.qc_status] ?? image.qc_status}
      </span>

      <div className="aoi-ds__tile-tools">
        <button type="button" className="aoi-ds__tile-btn" onClick={() => onDownload(image)}>
          下载
        </button>
        {canWrite ? (
          <button type="button" className="aoi-ds__tile-btn" onClick={() => onDelete(image)}>
            删除
          </button>
        ) : null}
      </div>

      <figcaption className="aoi-ds__tile-cap">
        <b>{image.station_code ?? "—"}</b>
        <span>
          {image.width && image.height ? `${image.width}×${image.height} · ` : ""}
          {formatBytes(image.size_bytes)}
        </span>
      </figcaption>
    </figure>
  );
};

export const ImagesPanel = ({ initialDatasetId = "", onNeedDataset }) => {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { has } = usePerms();

  const [datasetId, setDatasetId] = useState(initialDatasetId ? String(initialDatasetId) : "");
  const [stationCode, setStationCode] = useState("");
  const [filterSource, setFilterSource] = useState("");
  const [filterStation, setFilterStation] = useState("");
  const [page, setPage] = useState(0);
  const [drillDatasetId, setDrillDatasetId] = useState("");
  const [files, setFiles] = useState([]);
  const [previews, setPreviews] = useState([]);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  const { startImport, isImporting, isPolling, job, reset: resetImport } = useDatasetImport();

  const canImport = has("datasets.create");
  const canWrite = has("datasets.update");

  const datasetsQuery = useQuery({
    queryKey: DATASETS_QUERY_KEY,
    queryFn: () => aoiFetch("/api/datasets?page_size=200"),
  });

  // 下钻：单数据集全量（概览直接用 dataset.preview_images，不再单独请求）
  const imagesQuery = useQuery({
    queryKey: [...IMAGES_QUERY_KEY, drillDatasetId, filterSource, filterStation, page],
    queryFn: () => {
      const params = new URLSearchParams({ page_size: String(PAGE_SIZE), page: String(page) });
      if (drillDatasetId) params.set("dataset_id", drillDatasetId);
      if (filterSource) params.set("source", filterSource);
      if (filterStation) params.set("station_code", filterStation);
      return aoiFetch(`/api/datasets/images?${params.toString()}`);
    },
    enabled: Boolean(drillDatasetId),
  });

  // 未归属数据集的图（B 线复审回流等）——概览里单独一段
  const unassignedQuery = useQuery({
    queryKey: UNASSIGNED_QUERY_KEY,
    queryFn: () => aoiFetch("/api/datasets/images?unassigned=true&page_size=6"),
    enabled: !drillDatasetId,
  });

  useEffect(() => {
    if (initialDatasetId) setDatasetId(String(initialDatasetId));
  }, [initialDatasetId]);

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

  const startUpload = () => {
    startImport(
      { datasetId, stationCode, files },
      {
        onSuccess: () => {
          setFiles([]);
          setPage(0);
        },
      },
    );
  };

  const download = useMutation({
    mutationFn: (id) => aoiFetch(`/api/datasets/images/${id}/download`),
    onSuccess: (data) => window.open(data.url, "_blank"),
    onError: (error) => toast.show({ message: error.message, type: ToastType.error }),
  });

  const deleteImage = useMutation({
    mutationFn: (id) => aoiFetch(`/api/datasets/images/${id}`, { method: "DELETE" }),
    onSuccess: (data) => {
      toast.show({ message: `图片已删除（含 ${data.tasks_deleted ?? 0} 条标注任务）`, type: ToastType.info });
      queryClient.invalidateQueries({ queryKey: IMAGES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: UNASSIGNED_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: DATASETS_QUERY_KEY });
    },
    onError: (error) => toast.show({ message: error.message, type: ToastType.error }),
  });

  const confirmDeleteImage = (image) =>
    confirm({
      title: "删除图片",
      body: `确认删除 ${image.object_key}？其标注任务与存储文件会被一并清理，此操作不可恢复。`,
      okText: "删除",
      onOk: () => deleteImage.mutate(image.id),
    });

  const datasets = datasetsQuery.data?.items ?? [];
  const drilledDataset = datasets.find((item) => String(item.id) === String(drillDatasetId)) ?? null;
  const drillImages = imagesQuery.data?.items ?? [];
  const drillTotal = imagesQuery.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(drillTotal / PAGE_SIZE));
  const unassignedImages = unassignedQuery.data?.items ?? [];
  const unassignedTotal = unassignedQuery.data?.total ?? 0;
  const busyImporting = isImporting || isPolling;
  const targetName = useMemo(
    () => datasets.find((item) => String(item.id) === String(datasetId))?.name ?? "",
    [datasets, datasetId],
  );

  const openDrill = (id) => {
    setDrillDatasetId(String(id));
    setPage(0);
    setFilterSource("");
    setFilterStation("");
  };

  return (
    <div>
      {canImport ? (
        <div className="aoi-ds__stage">
          <div className="aoi-ds__stage-inner">
            <div className="aoi-ds__stage-head">
              <span className="aoi-ds__stage-label">
                上传图片{targetName ? ` → ${targetName}` : " → 先选目标数据集"}
              </span>
              <span className="aoi-ds__stage-note">
                {busyImporting
                  ? "导入中"
                  : files.length
                    ? `${files.length} 个文件待导入`
                    : "支持 jpg / png / bmp，可整批拖入"}
              </span>
            </div>

            {!datasets.length && !datasetsQuery.isLoading ? (
              <div className="mt-4">
                <p className="mb-3 text-sm" style={{ color: "var(--aoi-stage-ink)" }}>
                  图片要挂在一个数据集下面（数据集同时也是标注项目）。先建一个，回来再传图。
                </p>
                {onNeedDataset ? (
                  <AoiButton kind="onStage" onClick={onNeedDataset}>
                    新建数据集
                  </AoiButton>
                ) : null}
              </div>
            ) : busyImporting ? (
              <div className="aoi-ds__scan" role="progressbar" aria-label="图片导入中" />
            ) : (
              <div
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
                <button
                  type="button"
                  className={`aoi-ds__drop${dragOver ? " aoi-ds__drop--over" : ""}`}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <span className="aoi-ds__drop-title">把这一批图片拖到这里</span>
                  <span className="aoi-ds__drop-hint">或点击选择文件 · 重复图片会自动去重，坏图单独列出</span>
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
                    目标数据集
                    <select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
                      <option value="">选择数据集…</option>
                      {datasets.map((dataset) => (
                        <option key={dataset.id} value={dataset.id}>
                          {dataset.name ?? `dataset-${dataset.id}`}
                          {dataset.image_count ? `（已有 ${dataset.image_count} 张）` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="aoi-ds__field">
                    工位编号（可选）
                    <input
                      placeholder="如 ST-01"
                      value={stationCode}
                      onChange={(event) => setStationCode(event.target.value)}
                    />
                  </label>
                  <AoiButton kind="onStage" disabled={!datasetId || !files.length || isImporting} onClick={startUpload}>
                    {files.length ? `导入 ${files.length} 张` : "导入"}
                  </AoiButton>
                </div>
              </div>
            )}

            {job && !busyImporting ? (
              <>
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
                </div>
                {job.bad_items?.length ? (
                  <ul className="mb-0 mt-3 list-disc pl-5 text-xs" style={{ color: "var(--aoi-stage-ink-dim)" }}>
                    {job.bad_items.map((item, index) => (
                      <li key={`${item.filename}-${index}`}>
                        {item.filename}：{item.reason}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {job.error_message ? (
                  <p className="mb-0 mt-3 text-xs" style={{ color: "#ffb4a8" }}>
                    {job.error_message}
                  </p>
                ) : null}
                <div className="mt-4">
                  <AoiButton kind="onStage" onClick={resetImport}>
                    继续导入
                  </AoiButton>
                </div>
              </>
            ) : null}
          </div>
        </div>
      ) : null}

      {drillDatasetId ? (
        /* ── 下钻：单个数据集的全量图库 ───────────────────── */
        <div className="mt-8">
          <div className="aoi-ds__backrow">
            <AoiButton kind="quiet" onClick={() => setDrillDatasetId("")}>
              ← 返回按数据集
            </AoiButton>
            <span className="aoi-ds__group-title">{drilledDataset?.name ?? `数据集 ${drillDatasetId}`}</span>
            <span className="text-xs tabular-nums text-neutral-content-subtle">共 {drillTotal} 张</span>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-xs text-neutral-content-subtle">
                工位
                <input
                  className={`${FIELD} w-28`}
                  placeholder="全部"
                  value={filterStation}
                  onChange={(event) => {
                    setFilterStation(event.target.value);
                    setPage(0);
                  }}
                />
              </label>
              <label className="flex items-center gap-2 text-xs text-neutral-content-subtle">
                来源
                <select
                  className={FIELD}
                  value={filterSource}
                  onChange={(event) => {
                    setFilterSource(event.target.value);
                    setPage(0);
                  }}
                >
                  <option value="">全部</option>
                  {Object.entries(SOURCE_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <AoiButton
                onClick={() => {
                  setDatasetId(drillDatasetId);
                  setDrillDatasetId("");
                }}
              >
                传到这个数据集
              </AoiButton>
            </div>
          </div>

          {imagesQuery.isLoading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-neutral-content-subtle">
              <Spinner /> 加载中…
            </div>
          ) : imagesQuery.isError ? (
            <div className="rounded-lg border border-negative-border bg-negative-surface px-4 py-3 text-sm text-negative-content">
              图片加载失败：{imagesQuery.error.message}
            </div>
          ) : drillImages.length ? (
            <>
              <div className="aoi-ds__sheet">
                {drillImages.map((image) => (
                  <Tile
                    key={image.id}
                    image={image}
                    canWrite={canWrite}
                    onDownload={(item) => download.mutate(item.id)}
                    onDelete={confirmDeleteImage}
                  />
                ))}
              </div>
              {pageCount > 1 ? (
                <div className="mt-6 flex items-center gap-3">
                  <AoiButton disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                    上一页
                  </AoiButton>
                  <span className="text-xs tabular-nums text-neutral-content-subtle">
                    {page + 1} / {pageCount}
                  </span>
                  <AoiButton disabled={page + 1 >= pageCount} onClick={() => setPage((p) => p + 1)}>
                    下一页
                  </AoiButton>
                </div>
              ) : null}
            </>
          ) : (
            <div className="aoi-ds__empty">
              <p className="aoi-ds__empty-title m-0">这个数据集还没有图片</p>
              <p className="mt-2 mb-0 text-xs">把第一批产线图片拖进上面的台面，导入后就会出现在这里。</p>
            </div>
          )}
        </div>
      ) : (
        /* ── 概览：一个数据集一段，最多 5 张缩略图 ─────────── */
        <div className="mt-8">
          {datasetsQuery.isLoading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-neutral-content-subtle">
              <Spinner /> 加载中…
            </div>
          ) : datasets.length ? (
            datasets.map((dataset) => {
              const previewOfDataset = dataset.preview_images ?? [];
              const rest = Math.max(0, (dataset.image_count ?? 0) - previewOfDataset.length);
              return (
                <section key={dataset.id} className="aoi-ds__group">
                  <div className="aoi-ds__group-head">
                    <div className="min-w-0">
                      <div className="aoi-ds__group-title">{dataset.name ?? `dataset-${dataset.id}`}</div>
                      <div className="aoi-ds__group-meta">
                        <span>#{dataset.id}</span>
                        <span>{dataset.image_count ?? 0} 张图片</span>
                        <span>{dataset.cur_version ? `当前版本 ${dataset.cur_version}` : "当前为草稿"}</span>
                      </div>
                    </div>
                    <div className="aoi-ds__group-actions">
                      {dataset.image_count ? (
                        <AoiButton onClick={() => openDrill(dataset.id)}>查看全部 {dataset.image_count} 张</AoiButton>
                      ) : null}
                      <AoiButton
                        onClick={() => {
                          setDatasetId(String(dataset.id));
                          fileInputRef.current?.click();
                        }}
                      >
                        上传到这里
                      </AoiButton>
                      {dataset.ls_project_id ? (
                        <AoiButton
                          kind="quiet"
                          onClick={() => window.open(`/projects/${dataset.ls_project_id}/data`, "_blank")}
                        >
                          去标注 →
                        </AoiButton>
                      ) : null}
                    </div>
                  </div>

                  {previewOfDataset.length ? (
                    <div className="aoi-ds__strip-grid">
                      {previewOfDataset.map((image) => (
                        <Mini key={image.id} image={image} />
                      ))}
                      {rest > 0 ? (
                        <button type="button" className="aoi-ds__mini-more" onClick={() => openDrill(dataset.id)}>
                          +{rest}
                        </button>
                      ) : null}
                    </div>
                  ) : (
                    <p className="m-0 text-xs text-neutral-content-subtler">还没有图片，点「上传到这里」导入第一批。</p>
                  )}
                </section>
              );
            })
          ) : (
            <div className="aoi-ds__empty">
              <p className="aoi-ds__empty-title m-0">还没有数据集</p>
              <p className="mt-2 mb-4 text-xs">图片挂在数据集下面；先建一个数据集，再回来传图。</p>
              {onNeedDataset ? (
                <AoiButton kind="primary" onClick={onNeedDataset}>
                  新建数据集
                </AoiButton>
              ) : null}
            </div>
          )}

          {unassignedTotal ? (
            <section className="aoi-ds__group">
              <div className="aoi-ds__group-head">
                <div>
                  <div className="aoi-ds__group-title">未归属数据集</div>
                  <div className="aoi-ds__group-meta">
                    <span>{unassignedTotal} 张</span>
                    <span>复审回流或早期导入，未挂到具体数据集</span>
                  </div>
                </div>
              </div>
              <div className="aoi-ds__strip-grid">
                {unassignedImages.map((image) => (
                  <Mini key={image.id} image={image} />
                ))}
              </div>
            </section>
          ) : null}
        </div>
      )}
    </div>
  );
};
