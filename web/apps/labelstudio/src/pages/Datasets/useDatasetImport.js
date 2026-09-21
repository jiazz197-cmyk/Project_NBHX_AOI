/**
 * 数据集图片导入（契约 §4.1，D5 收尾第三轮抽公共 hook）。
 *
 * 为什么抽出来：图片面板与「新建数据集向导」都要走同一条异步导入链路
 * （multipart → Celery 任务 → 轮询终态），逻辑只能有一份，否则两处行为会漂移。
 *
 * 用法：
 *   const { startImport, job, isImporting, isPolling } = useDatasetImport();
 *   startImport({ datasetId, stationCode, files });
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useToast, ToastType } from "@humansignal/ui";
import { aoiFetch } from "../../aoi/api";

export const IMAGES_QUERY_KEY = ["aoi", "images"];
const IMPORT_JOB_KEY = ["aoi", "import-job"];
const TERMINAL_STATUSES = new Set(["succeeded", "failed"]);

export const useDatasetImport = () => {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [pendingJobId, setPendingJobId] = useState(null);

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
    mutationFn: async ({ datasetId, stationCode, files }) => {
      if (!files?.length) throw new Error("请选择要导入的图片文件");
      if (!datasetId) throw new Error("请选择目标数据集");
      const body = new FormData();
      body.append("dataset_id", String(datasetId));
      body.append("source", "manual_real");
      if (stationCode) body.append("station_code", stationCode);
      Array.from(files).forEach((file) => body.append("files[]", file));
      const result = await aoiFetch("/api/datasets/import", { method: "POST", body });
      return result.job_id;
    },
    onSuccess: (jobId) => setPendingJobId(jobId),
    onError: (error) => toast.show({ message: error.message, type: ToastType.error }),
  });

  return {
    startImport: importImages.mutate,
    isImporting: importImages.isPending,
    isPolling: Boolean(pendingJobId),
    job,
    reset: () => setPendingJobId(null),
  };
};
