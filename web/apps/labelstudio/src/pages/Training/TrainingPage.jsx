/**
 * AOI「训练」页（D7 骨架 · 注入点注册，契约 §4.2 / 跨平台契约 §2.4）。
 *
 * 工序轨道：① 模型库（勾选 approved 模型）→ ② 发布仓库（逐条独立执行 + 结果/重试）
 * → ③ 已上传（下线 / 软删 / 恢复）。编号是真序列：发布必然发生在勾选之后、管理之前。
 * 共享 chrome 用 `aoi-ds__*`（src/aoi/page.css），本页特有样式 `aoi-tr__*`（Training.css）。
 *
 * 数据全部来自真实接口（不伪造）：GET /api/train/models、POST /api/train/models/publish
 * （批量、逐条独立、失败可单条重试）、GET /api/train/publishes?include_deleted=1、
 * retire / delete / restore。训练任务列表 D9 才接入——空态直说，不摆假数据。
 *
 * 软删文案如实：「仅移除 A 侧记录，仓库镜像保留，B 仍可拉取」（跨平台契约 §2.4）。
 * 门控：`training.view`；发布/下线/删除/恢复需 `training.publish`（后端校验为准）。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ToastType, useToast } from "@humansignal/ui";
import { Spinner } from "../../components/Spinner/Spinner";
import { confirm } from "../../components/Modal/Modal";
import { aoiFetch } from "../../aoi/api";
import { usePerms } from "../../aoi/usePerms";
import { AoiButton } from "../Datasets/AoiButton";
import "./Training.css";

const STEP_KEYS = ["models", "publish", "uploads"];

const LIFECYCLE_LABEL = {
  candidate: "候选",
  approved: "已评审",
  published: "已发布",
  retired: "已下线",
  rejected: "已否决",
};

const shortDigest = (digest) => (digest ? `${digest.slice(0, 14)}…${digest.slice(-8)}` : "—");

const ModelRow = ({ model, checked, toggleable, onToggle, canPublish }) => (
  <div className="aoi-ds__row aoi-tr__row">
    <input
      type="checkbox"
      className="aoi-tr__check"
      checked={checked}
      disabled={!toggleable || !canPublish}
      onChange={() => onToggle(model.id)}
      aria-label={`选择模型 ${model.version}`}
    />
    <div>
      <div className="aoi-ds__row-name">
        {model.version}
        {model.stub ? <span className="aoi-ds__step-meta">（契约样例，未落库）</span> : null}
      </div>
      <div className="aoi-ds__row-meta">
        <span>{model.framework}</span>
        <span>数据集 {model.dataset_version}</span>
        <span>{model.precision}</span>
        <span>
          门禁 {model.gate_status === "passed" ? "通过" : model.gate_status === "pending" ? "未跑" : model.gate_status}
        </span>
      </div>
    </div>
    <div className="aoi-ds__row-actions">
      <span className={`aoi-tr__lifecycle aoi-tr__lifecycle--${model.lifecycle}`}>
        {LIFECYCLE_LABEL[model.lifecycle] ?? model.lifecycle}
      </span>
    </div>
  </div>
);

export const TrainingPage = () => {
  const { has, isLoading: permsLoading } = usePerms();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("models");
  const [selected, setSelected] = useState([]);
  const [precision, setPrecision] = useState("fp32");
  const [lastBatch, setLastBatch] = useState(null);

  const modelsQuery = useQuery({
    queryKey: ["aoi", "train", "models"],
    queryFn: () => aoiFetch("/api/train/models?page_size=200"),
  });
  const publishesQuery = useQuery({
    queryKey: ["aoi", "train", "publishes"],
    queryFn: () => aoiFetch("/api/train/publishes?include_deleted=1&page_size=200"),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["aoi", "train"] });
  };
  const onError = (error) => toast.show({ message: error.message, type: ToastType.error });

  const batchPublish = useMutation({
    mutationFn: (modelIds) =>
      aoiFetch("/api/train/models/publish", {
        method: "POST",
        body: JSON.stringify({ model_ids: modelIds, precision }),
      }),
    onSuccess: (data) => {
      setLastBatch(data);
      invalidate();
      setActiveTab("publish");
      if (data.failed > 0)
        toast.show({ message: `${data.failed} 条发布失败，可在下方逐条重试`, type: ToastType.error });
    },
    onError,
  });

  const retire = useMutation({
    mutationFn: (modelId) => aoiFetch(`/api/train/models/${modelId}/retire`, { method: "POST", body: "{}" }),
    onSuccess: () => {
      invalidate();
      toast.show({ message: "模型已下线", type: ToastType.info });
    },
    onError,
  });

  const deletePublish = useMutation({
    mutationFn: (publishId) => aoiFetch(`/api/train/publishes/${publishId}/delete`, { method: "POST", body: "{}" }),
    onSuccess: () => {
      invalidate();
      toast.show({ message: "已移除 A 侧记录（仓库镜像保留）", type: ToastType.info });
    },
    onError,
  });

  const restorePublish = useMutation({
    mutationFn: (publishId) => aoiFetch(`/api/train/publishes/${publishId}/restore`, { method: "POST", body: "{}" }),
    onSuccess: () => {
      invalidate();
      toast.show({ message: "记录已恢复", type: ToastType.info });
    },
    onError,
  });

  if (permsLoading) {
    return (
      <div className="aoi-ds flex items-center justify-center">
        <div className="flex items-center gap-2 py-24 text-sm text-neutral-content-subtle">
          <Spinner /> 加载中…
        </div>
      </div>
    );
  }

  if (!has("training.view")) {
    return (
      <div className="aoi-ds">
        <div className="aoi-ds__wrap">
          <div className="aoi-ds__empty">无权访问此页面（需要训练查看权限）。</div>
        </div>
      </div>
    );
  }

  const models = modelsQuery.data?.items ?? [];
  const canPublish = has("training.publish");
  const toggleable = (model) => canPublish && !model.stub && model.lifecycle === "approved";
  const toggle = (id) =>
    setSelected((current) => (current.includes(id) ? current.filter((value) => value !== id) : [...current, id]));
  const retryOne = (modelId) => batchPublish.mutate([modelId]);

  const stepMeta = {
    models: models.length ? `${models.length} 个` : "还没有",
    publish: lastBatch ? `上次 ${lastBatch.succeeded}/${lastBatch.results.length} 成功` : "未发布",
    uploads: publishesQuery.data ? `${publishesQuery.data.total} 条` : "—",
  };

  const publishes = publishesQuery.data?.items ?? [];

  const confirmRetire = (item) =>
    confirm({
      title: "下线模型",
      body: `确认下线 ${item.model_ref}？下线后 B 侧不再把它当作可拉取的当前版本（镜像仍在仓库）。`,
      okText: "下线",
      onOk: () => retire.mutate(item.model_id),
    });

  const confirmDelete = (item) =>
    confirm({
      title: "删除上传记录",
      body: `确认删除 ${item.model_ref}（tag ${item.tag}）的上传记录？仅移除 A 侧记录，仓库镜像保留，B 仍可拉取；之后可从本页恢复。`,
      okText: "删除记录",
      onOk: () => deletePublish.mutate(item.publish_id),
    });

  return (
    <div className="aoi-ds">
      <div className="aoi-ds__wrap">
        <header className="aoi-ds__head">
          <div>
            <h1 className="aoi-ds__title">训练</h1>
            <p className="aoi-ds__lede">
              把评审通过的模型打镜像推到仓库（model.onnx + sha256 + model.yaml，单层 FROM scratch 镜像），
              再管理已上传记录。digest 以仓库回执为准，同内容重发不会变。
            </p>
          </div>
        </header>

        <nav className="aoi-ds__rail" aria-label="训练工序">
          {STEP_KEYS.map((key, index) => {
            const active = key === activeTab;
            const label = { models: "模型库", publish: "发布仓库", uploads: "已上传" }[key];
            return (
              <button
                key={key}
                type="button"
                aria-current={active ? "step" : undefined}
                className={`aoi-ds__step${active ? " aoi-ds__step--active" : ""}`}
                onClick={() => setActiveTab(key)}
              >
                <span className="aoi-ds__step-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="aoi-ds__step-label">{label}</span>
                <span className="aoi-ds__step-meta">{stepMeta[key]}</span>
              </button>
            );
          })}
        </nav>

        <div className="aoi-ds__body">
          {activeTab === "models" ? (
            <>
              <div className="aoi-ds__head" style={{ marginBottom: 14 }}>
                <span className="aoi-ds__step-label">
                  {selected.length ? `已勾选 ${selected.length} 个模型` : "勾选要上传的模型（仅已评审）"}
                </span>
                <div className="aoi-ds__row-actions">
                  <label className="aoi-tr__precision">
                    精度
                    <select value={precision} onChange={(event) => setPrecision(event.target.value)}>
                      <option value="fp32">fp32</option>
                      <option value="fp16">fp16</option>
                    </select>
                  </label>
                  <AoiButton
                    kind="primary"
                    disabled={!canPublish || selected.length === 0 || batchPublish.isPending}
                    onClick={() => batchPublish.mutate(selected)}
                  >
                    {batchPublish.isPending ? "上传中…" : `批量上传（${selected.length}）`}
                  </AoiButton>
                </div>
              </div>
              {modelsQuery.isLoading ? (
                <div className="aoi-ds__empty">
                  <Spinner /> 加载模型…
                </div>
              ) : models.length === 0 ? (
                <div className="aoi-ds__empty">
                  <p className="aoi-ds__empty-title">模型库是空的</p>
                  <p>训练流水线在 D9 接入；接入后评审通过的模型会出现在这里。</p>
                </div>
              ) : (
                <div className="aoi-ds__ledger">
                  {models.map((model) => (
                    <ModelRow
                      key={model.id}
                      model={model}
                      checked={selected.includes(model.id)}
                      toggleable={toggleable(model)}
                      onToggle={toggle}
                      canPublish={canPublish}
                    />
                  ))}
                </div>
              )}

              <section className="aoi-tr__section">
                <h2 className="aoi-tr__section-title">训练任务</h2>
                <div className="aoi-ds__empty">训练 / 评测任务列表在 D9 接入（当前里程碑只做模型发布与管理）。</div>
              </section>
            </>
          ) : activeTab === "publish" ? (
            <>
              <p className="aoi-tr__pipeline">
                发布 = 逐条独立执行：模型权重 + <code>model.yaml</code> 打成单层 <code>FROM scratch</code> 镜像， 直推
                Registry v2；digest 取仓库 <code>Docker-Content-Digest</code> 回执，拿不到回执就按失败处理，
                绝不落本地自算值。某条失败不影响其余，可单条重试。
              </p>
              {!lastBatch ? (
                <div className="aoi-ds__empty">
                  <p className="aoi-ds__empty-title">还没有批量上传记录</p>
                  <p>回「模型库」勾选已评审的模型后点「批量上传」，逐条结果会出现在这里。</p>
                </div>
              ) : (
                <>
                  <div className="aoi-ds__head" style={{ marginBottom: 10 }}>
                    <span className="aoi-ds__step-label">
                      上次结果：{lastBatch.succeeded} 成功 / {lastBatch.failed} 失败
                    </span>
                  </div>
                  <div>
                    {lastBatch.results.map((result) => (
                      <div key={result.model_id} className="aoi-tr__result">
                        <div className="aoi-tr__result-main">
                          <b>#{result.model_id}</b>
                          <div className="aoi-tr__result-line">
                            {result.tag ? <code>tag {result.tag}</code> : null}
                            {result.digest ? (
                              <span className="aoi-tr__digest">{shortDigest(result.digest)}</span>
                            ) : null}
                            {result.error ? <span className="aoi-tr__status-failed">{result.error}</span> : null}
                          </div>
                        </div>
                        <div className="aoi-ds__row-actions">
                          {result.status === "published" ? (
                            <span className="aoi-tr__status-ok">已上传</span>
                          ) : (
                            <AoiButton
                              kind="ghost"
                              disabled={!canPublish || batchPublish.isPending}
                              onClick={() => retryOne(result.model_id)}
                            >
                              重试
                            </AoiButton>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          ) : (
            <>
              {publishesQuery.isLoading ? (
                <div className="aoi-ds__empty">
                  <Spinner /> 加载…
                </div>
              ) : publishes.length === 0 ? (
                <div className="aoi-ds__empty">
                  <p className="aoi-ds__empty-title">还没有已上传记录</p>
                  <p>发布成功后会在这里登记；可下线、软删（仅移除 A 侧记录）与恢复。</p>
                </div>
              ) : (
                <div className="aoi-ds__ledger">
                  {publishes.map((item) => (
                    <div key={item.publish_id} className="aoi-ds__row" style={{ opacity: item.deleted_at ? 0.55 : 1 }}>
                      <div>
                        <div className="aoi-ds__row-name">
                          {item.model_ref}
                          {item.deleted_at ? <span className="aoi-ds__step-meta">（记录已删，可恢复）</span> : null}
                        </div>
                        <div className="aoi-ds__row-meta">
                          <code className="aoi-tr__digest">tag {item.tag}</code>
                          <span className="aoi-tr__digest" title={item.digest ?? ""}>
                            digest {shortDigest(item.digest)}
                          </span>
                          <span>模型状态 {LIFECYCLE_LABEL[item.model_lifecycle] ?? item.model_lifecycle ?? "—"}</span>
                          {item.published_at ? (
                            <span>发布于 {item.published_at.slice(0, 16).replace("T", " ")}</span>
                          ) : null}
                        </div>
                      </div>
                      <div className="aoi-ds__row-actions">
                        {item.deleted_at ? (
                          <AoiButton
                            kind="ghost"
                            disabled={!canPublish || restorePublish.isPending}
                            onClick={() => restorePublish.mutate(item.publish_id)}
                          >
                            恢复
                          </AoiButton>
                        ) : (
                          <>
                            <AoiButton
                              kind="ghost"
                              disabled={!canPublish || item.model_lifecycle !== "published" || retire.isPending}
                              onClick={() => confirmRetire(item)}
                            >
                              下线
                            </AoiButton>
                            <AoiButton
                              kind="danger"
                              disabled={!canPublish || item.model_lifecycle !== "retired" || deletePublish.isPending}
                              title={item.model_lifecycle === "retired" ? undefined : "先下线模型，才能删除上传记录"}
                              onClick={() => confirmDelete(item)}
                            >
                              删除
                            </AoiButton>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

TrainingPage.title = "Training";
TrainingPage.path = "/training";
