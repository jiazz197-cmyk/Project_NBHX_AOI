/**
 * 数据集面板（契约 §4.1，D5）：列表（name/cur_version/versions/ls_project_id）+ 新建 + 新建草稿版本 + 删除。
 * 新建 = `datasets.create`：服务端按缺陷字典快照生成标注项目（`ls_project_id` 服务端生成）；
 * 无已发布字典时回退当前启用缺陷（draft 语义），支持先建数据集再发布字典。
 * 新建草稿版本 / 删除 = `datasets.update`（创建成功 toast + 版本列即时可见；删除级联清理标注项目/任务/图片）。
 * 样式：语义 token + 共享常量（aoi/uiTokens），暗色自动适配。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, ToastType, useToast } from "@humansignal/ui";
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
  TABLE,
  TABLE_BODY_CELL,
  TABLE_HEAD_CELL,
  TABLE_ROW,
} from "../../aoi/uiTokens";

const DATASETS_QUERY_KEY = ["aoi", "datasets"];

export const DatasetsPanel = () => {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { has } = usePerms();
  const [newName, setNewName] = useState("");

  const onError = (error) => toast.show({ message: error.message, type: ToastType.error });
  const invalidateDatasets = () => queryClient.invalidateQueries({ queryKey: DATASETS_QUERY_KEY });

  const datasetsQuery = useQuery({
    queryKey: DATASETS_QUERY_KEY,
    queryFn: () => aoiFetch("/api/datasets?page_size=200"),
  });

  const createDataset = useMutation({
    mutationFn: (name) => aoiFetch("/api/datasets", { method: "POST", body: JSON.stringify({ name }) }),
    onSuccess: (dataset) => {
      toast.show({ message: `数据集「${dataset.name}」已创建，标注项目已生成`, type: ToastType.info });
      setNewName("");
      invalidateDatasets();
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
      toast.show({ message: "数据集已删除（标注项目、任务与已导入图片一并清理）", type: ToastType.info });
      invalidateDatasets();
    },
    onError,
  });

  const datasets = datasetsQuery.data?.items ?? [];
  const canCreate = has("datasets.create");
  const canUpdate = has("datasets.update");
  const busy = createDataset.isPending || createVersion.isPending || deleteDataset.isPending;

  const confirmDeleteDataset = (dataset) =>
    confirm({
      title: "删除数据集",
      body: `确认删除数据集「${dataset.name ?? dataset.id}」？其标注项目、任务与已导入图片会被一并清理，此操作不可恢复。`,
      okText: "删除",
      onOk: () => deleteDataset.mutate(dataset.id),
    });

  return (
    <div>
      {canCreate ? (
        <div className={`${CARD} mb-4 p-4`}>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (!newName.trim()) return;
              createDataset.mutate(newName.trim());
            }}
          >
            <label className="flex flex-col gap-1 text-xs text-neutral-content-subtle">
              新数据集名称
              <input
                className={`${INPUT} w-72`}
                placeholder="如 产线A-外观检测-批次01"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
              />
            </label>
            <Button type="submit" size="compact" disabled={busy || !newName.trim()}>
              新建数据集
            </Button>
          </form>
          <p className={`${HINT} mb-0 mt-3`}>
            新建数据集会按最新已发布缺陷字典生成标注项目（一人一图、OK
            图允许空标注）；无已发布字典时请先到「缺陷字典」发布。
          </p>
        </div>
      ) : null}

      {datasetsQuery.isLoading ? (
        <div className={LOADING}>
          <Spinner /> 加载中…
        </div>
      ) : datasetsQuery.isError ? (
        <div className={ERROR_BOX}>数据集列表加载失败：{datasetsQuery.error.message}</div>
      ) : (
        <div className={`${CARD} overflow-hidden`}>
          <table className={TABLE}>
            <thead className="bg-neutral-surface-inset">
              <tr>
                <th className={TABLE_HEAD_CELL}>ID</th>
                <th className={TABLE_HEAD_CELL}>名称</th>
                <th className={TABLE_HEAD_CELL}>当前版本</th>
                <th className={TABLE_HEAD_CELL}>版本</th>
                <th className={TABLE_HEAD_CELL}>标注项目</th>
                {canUpdate ? <th className={TABLE_HEAD_CELL}>操作</th> : null}
              </tr>
            </thead>
            <tbody>
              {datasets.map((dataset) => (
                <tr key={dataset.id} className={TABLE_ROW}>
                  <td className={`${TABLE_BODY_CELL} font-mono text-xs`}>{dataset.id}</td>
                  <td className={`${TABLE_BODY_CELL} font-medium`}>{dataset.name ?? "—"}</td>
                  <td className={TABLE_BODY_CELL}>
                    {dataset.cur_version ? badge("primary", dataset.cur_version) : badge("neutral", "草稿")}
                  </td>
                  <td className={TABLE_BODY_CELL}>
                    {dataset.versions?.length ? (
                      <div
                        className="flex flex-wrap items-center gap-1"
                        title={dataset.versions.map((v) => v.version).join("、")}
                      >
                        {dataset.versions.map((version) => (
                          <span
                            key={version.id}
                            className="rounded border border-neutral-border-subtle bg-neutral-surface-inset px-1.5 py-0.5 font-mono text-xs text-neutral-content-subtle"
                          >
                            {version.version}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-neutral-content-subtler">—</span>
                    )}
                  </td>
                  <td className={TABLE_BODY_CELL}>
                    {dataset.ls_project_id ? (
                      <a
                        className="text-primary-content underline-offset-2 hover:underline"
                        href={`/projects/${dataset.ls_project_id}/data`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        项目 {dataset.ls_project_id}
                      </a>
                    ) : (
                      <span className="text-neutral-content-subtler">—</span>
                    )}
                  </td>
                  {canUpdate ? (
                    <td className={TABLE_BODY_CELL}>
                      <div className="flex gap-2">
                        <Button
                          size="compact"
                          look="outlined"
                          disabled={busy}
                          onClick={() =>
                            confirm({
                              title: "新建草稿版本",
                              body: `为数据集「${dataset.name ?? dataset.id}」创建新的草稿版本？版本号将自动生成，划分与统计随发布流程推进。`,
                              okText: "创建",
                              onOk: () => createVersion.mutate(dataset.id),
                            })
                          }
                        >
                          新建草稿版本
                        </Button>
                        <Button
                          size="compact"
                          look="outlined"
                          disabled={busy}
                          onClick={() => confirmDeleteDataset(dataset)}
                        >
                          删除
                        </Button>
                      </div>
                    </td>
                  ) : null}
                </tr>
              ))}
              {!datasets.length ? (
                <tr>
                  <td className={EMPTY} colSpan={6}>
                    暂无数据集，请先新建。
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
