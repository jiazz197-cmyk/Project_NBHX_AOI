/**
 * 图片面板（契约 §4.1，D5）：人工导入（multipart → Celery 异步任务）+ 任务结果轮询 + 图片列表 + 下载/删除。
 * 导入必须选择数据集（服务端要求 dataset 已有标注项目，见契约 §4.1）；source 固定 manual_real。
 * 删除（D5 实测新增）= `datasets.update`：服务端级联清理 LS 任务、存储字节与版本明细。
 * 样式：语义 token + 共享常量（aoi/uiTokens），暗色自动适配。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Button, InputFile, ToastType, useToast } from "@humansignal/ui";
import { Spinner } from "../../components/Spinner/Spinner";
import { confirm } from "../../components/Modal/Modal";
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

const DATASETS_QUERY_KEY = ["aoi", "datasets"];
const IMAGES_QUERY_KEY = ["aoi", "images"];
const IMPORT_JOB_KEY = ["aoi", "import-job"];

const TERMINAL_STATUSES = new Set(["succeeded", "failed"]);

const ImportResult = ({ job }) => {
  if (!job) return null;
  const failed = job.status === "failed";
  return (
    <div
      className={`mt-4 rounded-lg border p-4 ${
        failed ? "border-negative-border bg-negative-surface" : "border-positive-border bg-positive-surface"
      }`}
    >
      <p className="m-0 mb-1 text-sm font-semibold text-neutral-content">
        导入{failed ? "失败" : "完成"}：共 {job.total} 个文件 · 成功 {job.ok} · 重复 {job.dup} · 坏图 {job.bad}
      </p>
      {failed && job.error_message ? <p className="m-0 text-sm text-negative-content">{job.error_message}</p> : null}
      {job.bad_items?.length ? (
        <ul className="m-0 mt-1 list-disc pl-5 text-xs text-neutral-content-subtle">
          {job.bad_items.map((item, index) => (
            <li key={`${item.filename}-${index}`}>
              {item.filename}：{item.reason}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
};

export const ImagesPanel = () => {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { has } = usePerms();
  const [datasetId, setDatasetId] = useState("");
  const [stationCode, setStationCode] = useState("");
  const [filterSource, setFilterSource] = useState("");
  const [page, setPage] = useState(0);
  const filesRef = useRef(null);
  const [pendingJobId, setPendingJobId] = useState(null);

  const datasetsQuery = useQuery({
    queryKey: DATASETS_QUERY_KEY,
    queryFn: () => aoiFetch("/api/datasets?page_size=200"),
  });

  const imagesQuery = useQuery({
    queryKey: [...IMAGES_QUERY_KEY, filterSource, stationCode, page],
    queryFn: () => {
      const params = new URLSearchParams({ page_size: "50", page: String(page) });
      if (filterSource) params.set("source", filterSource);
      if (stationCode) params.set("station_code", stationCode);
      return aoiFetch(`/api/datasets/images?${params.toString()}`);
    },
  });

  // 轮询导入任务直至终态（契约 §4.1：queued/running → succeeded/failed）
  const jobQuery = useQuery({
    queryKey: [...IMPORT_JOB_KEY, pendingJobId],
    queryFn: () => aoiFetch(`/api/datasets/import/${pendingJobId}`),
    enabled: Boolean(pendingJobId),
    refetchInterval: (data) => (data && TERMINAL_STATUSES.has(data.status) ? false : 1500),
  });
  const job = jobQuery.data;
  useEffect(() => {
    if (job && TERMINAL_STATUSES.has(job.status) && pendingJobId) {
      setPendingJobId(null);
      queryClient.invalidateQueries({ queryKey: IMAGES_QUERY_KEY });
    }
  }, [job, pendingJobId, queryClient]);

  const importImages = useMutation({
    mutationFn: async () => {
      const files = filesRef.current?.files;
      if (!files?.length) throw new Error("请选择要导入的图片文件");
      if (!datasetId) throw new Error("请选择目标数据集");
      const body = new FormData();
      body.append("dataset_id", datasetId);
      body.append("source", "manual_real");
      if (stationCode) body.append("station_code", stationCode);
      Array.from(files).forEach((file) => body.append("files[]", file));
      const result = await aoiFetch("/api/datasets/import", { method: "POST", body });
      return result.job_id;
    },
    onSuccess: (jobId) => {
      if (filesRef.current) filesRef.current.value = "";
      setPendingJobId(jobId);
    },
    onError: (error) => toast.show({ message: error.message, type: ToastType.error }),
  });

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
    },
    onError: (error) => toast.show({ message: error.message, type: ToastType.error }),
  });

  const confirmDeleteImage = (image) =>
    confirm({
      title: "删除图片",
      body: `确认删除图片 ${image.object_key}？其标注任务与存储文件会被一并清理，此操作不可恢复。`,
      okText: "删除",
      onOk: () => deleteImage.mutate(image.id),
    });

  const images = imagesQuery.data?.items ?? [];
  const total = imagesQuery.data?.total ?? 0;
  const canWrite = has("datasets.update");

  return (
    <div>
      <div className={`${CARD} mb-4 p-4`}>
        <h3 className={`${SECTION_TITLE} mb-3`}>导入图片</h3>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-neutral-content-subtle">
            目标数据集
            <select className={INPUT} value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
              <option value="">选择数据集…</option>
              {(datasetsQuery.data?.items ?? []).map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name ?? `dataset-${dataset.id}`}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-neutral-content-subtle">
            工位编号（可选）
            <input
              className={INPUT}
              placeholder="如 ST-01"
              value={stationCode}
              onChange={(event) => setStationCode(event.target.value)}
            />
          </label>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-neutral-content-subtle">图片文件</span>
            <InputFile ref={filesRef} text="选择图片（可多选）" multiple accept="image/jpeg,image/png,image/bmp" />
          </div>
          <Button size="compact" disabled={importImages.isPending} onClick={() => importImages.mutate()}>
            {importImages.isPending ? "导入中…" : "导入"}
          </Button>
        </div>
        <p className={`${HINT} mb-0 mt-3`}>
          导入为异步任务：成功登记的图片会同步出现在对应标注项目的任务队列；重复图片（全局 md5
          去重）与坏图会计入结果明细。
        </p>
      </div>

      {job ? <ImportResult job={job} /> : null}

      <div className="mb-3 mt-5 flex flex-wrap items-center gap-3">
        <select className={INPUT} value={filterSource} onChange={(event) => setFilterSource(event.target.value)}>
          <option value="">全部来源</option>
          <option value="manual_real">manual_real</option>
          <option value="camera">camera</option>
          <option value="reflux_review">reflux_review</option>
        </select>
        <input
          className={INPUT}
          placeholder="按工位筛选"
          value={stationCode}
          onChange={(event) => setStationCode(event.target.value)}
        />
        <span className="text-xs text-neutral-content-subtle">共 {total} 张</span>
      </div>

      {imagesQuery.isLoading ? (
        <div className={LOADING}>
          <Spinner /> 加载中…
        </div>
      ) : imagesQuery.isError ? (
        <div className={ERROR_BOX}>图片列表加载失败：{imagesQuery.error.message}</div>
      ) : (
        <div className={`${CARD} overflow-hidden`}>
          <table className={TABLE}>
            <thead className="bg-neutral-surface-inset">
              <tr>
                <th className={TABLE_HEAD_CELL}>ID</th>
                <th className={TABLE_HEAD_CELL}>对象键</th>
                <th className={TABLE_HEAD_CELL}>来源</th>
                <th className={TABLE_HEAD_CELL}>工位</th>
                <th className={TABLE_HEAD_CELL}>尺寸</th>
                <th className={TABLE_HEAD_CELL}>质检</th>
                <th className={TABLE_HEAD_CELL}>操作</th>
              </tr>
            </thead>
            <tbody>
              {images.map((image) => (
                <tr key={image.id} className={TABLE_ROW}>
                  <td className={`${TABLE_BODY_CELL} font-mono text-xs`}>{image.id}</td>
                  <td
                    className={`${TABLE_BODY_CELL} max-w-[320px] truncate font-mono text-xs`}
                    title={image.object_key}
                  >
                    {image.object_key}
                  </td>
                  <td className={TABLE_BODY_CELL}>{badge("neutral", image.source)}</td>
                  <td className={TABLE_BODY_CELL}>{image.station_code ?? "—"}</td>
                  <td className={TABLE_BODY_CELL}>{image.width != null ? `${image.width}×${image.height}` : "—"}</td>
                  <td className={TABLE_BODY_CELL}>
                    {image.qc_status === "ok"
                      ? badge("positive", "通过")
                      : image.qc_status === "rejected"
                        ? badge("negative", "拒绝")
                        : badge("neutral", image.qc_status)}
                  </td>
                  <td className={TABLE_BODY_CELL}>
                    <div className="flex gap-2">
                      <Button
                        size="compact"
                        look="outlined"
                        disabled={download.isPending}
                        onClick={() => download.mutate(image.id)}
                      >
                        下载
                      </Button>
                      {canWrite ? (
                        <Button
                          size="compact"
                          look="outlined"
                          disabled={deleteImage.isPending}
                          onClick={() => confirmDeleteImage(image)}
                        >
                          删除
                        </Button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
              {!images.length ? (
                <tr>
                  <td className={EMPTY} colSpan={7}>
                    暂无图片。
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
      {total > images.length ? (
        <div className="mt-4 flex items-center gap-2">
          <Button
            size="compact"
            look="outlined"
            disabled={page === 0}
            onClick={() => setPage((current) => Math.max(0, current - 1))}
          >
            上一页
          </Button>
          <Button
            size="compact"
            look="outlined"
            disabled={(page + 1) * 50 >= total}
            onClick={() => setPage((current) => current + 1)}
          >
            下一页
          </Button>
          <span className="text-xs text-neutral-content-subtle">
            第 {page + 1} 页 / 共 {Math.ceil(total / 50) || 1} 页
          </span>
        </div>
      ) : null}
    </div>
  );
};
