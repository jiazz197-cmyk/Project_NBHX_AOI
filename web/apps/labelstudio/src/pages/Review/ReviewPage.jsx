/**
 * AOI「复审」页（D7 骨架 · 注入点注册，契约 §4.4）。
 *
 * 页面结构：页头一句话 → 桶过滤 tab（绿/黄/红＝桶含义本身，带计数）→ 工作项账本
 * （缩略图 + 检测事实摘要）→ 点行开**暗房灯箱**（claim / 终裁内联表单）→ 坏图账本。
 * 共享 chrome 用 `aoi-ds__*`（src/aoi/page.css），本页特有样式 `aoi-rv__*`（Review.css）。
 *
 * 数据全部来自真实接口（不伪造）：GET /api/review/workitems（D7 起内嵌 fact/image）、
 * GET /api/review/bad-images、claim/finalize/handle 三个动作。队列是空的就直说，
 * 并给出数据从哪来（B 侧 /api/ingest/findings 回传）。
 *
 * 门控：`review.view`（Menubar 入口同码）；claim/handle 需 `review.update`，
 * finalize 需 `review.finalize`（后端校验为准，前端只做显隐）。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Spinner } from "../../components/Spinner/Spinner";
import { aoiFetch } from "../../aoi/api";
import { usePerms } from "../../aoi/usePerms";
import { AoiButton } from "../Datasets/AoiButton";
import "./Review.css";

const BUCKETS = [
  { key: "high", label: "高桶", color: "#52C41A", hint: "模型确信无缺陷" },
  { key: "medium", label: "中桶", color: "#FAAD14", hint: "复检" },
  { key: "low", label: "低桶", color: "#FF4D4F", hint: "必须人工" },
];

const STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "pending", label: "待处理" },
  { value: "processing", label: "处理中" },
  { value: "finalized", label: "已终裁" },
];

const FINAL_REASONS = [
  { value: "misdetection", label: "误检" },
  { value: "missed_detection", label: "漏检" },
  { value: "new_defect", label: "新缺陷" },
  { value: "annotation_issue", label: "标注问题" },
  { value: "lighting_anomaly", label: "光照异常" },
];

const FINAL_VERDICTS = [
  { value: "defect_confirmed", label: "缺陷确认" },
  { value: "false_alarm", label: "误报排除" },
  { value: "uncertain", label: "存疑" },
];

const REVIEW_ACTIONS = [
  { value: "accepted_prediction", label: "接受预测" },
  { value: "relabeled", label: "已重标" },
  { value: "no_defect", label: "无缺陷" },
  { value: "unlabelable", label: "不可标注" },
  { value: "edited", label: "已编辑标注" },
];

const SOURCE_LABEL = { ingest: "B 侧回传", prelabel: "预标", manual: "人工" };

const bucketOf = (item) => item.bucket ?? "";
const bucketMeta = (bucket) => BUCKETS.find((b) => b.key === bucket) ?? null;

const WorkitemRow = ({ item, onOpen }) => {
  const bucket = bucketMeta(bucketOf(item));
  const fact = item.fact;
  const facts = [
    fact ? `工位 ${fact.station_code}` : null,
    fact ? `序号 ${fact.seq}` : null,
    fact?.captured_at ? `拍摄 ${fact.captured_at.slice(0, 16).replace("T", " ")}` : null,
    item.source ? (SOURCE_LABEL[item.source] ?? item.source) : null,
    item.model_ref ? `模型 ${item.model_ref}` : null,
  ].filter(Boolean);

  return (
    <div className="aoi-ds__row aoi-rv__row">
      {item.image ? (
        <img className="aoi-rv__thumb" src={item.image.url} alt="" loading="lazy" />
      ) : (
        <span className="aoi-rv__thumb" aria-hidden />
      )}
      <div>
        <div className="aoi-ds__row-name">
          {bucket ? (
            <span className="aoi-rv__bucket-flag" style={{ color: bucket.color }}>
              <i style={{ background: bucket.color }} />
              {bucket.label}
            </span>
          ) : null}
          <span style={{ marginLeft: bucket ? 10 : 0 }}>
            {fact ? `${fact.station_code} · ${fact.seq}` : `工作项 #${item.id}`}
          </span>
        </div>
        <div className="aoi-ds__row-meta">
          {facts.map((text) => (
            <span key={text}>{text}</span>
          ))}
          {item.verdict ? <span>判定 {item.verdict}</span> : null}
          <span>{item.status === "finalized" ? "已终裁" : item.status === "processing" ? "处理中" : "待处理"}</span>
        </div>
      </div>
      <div className="aoi-ds__row-actions">
        <AoiButton kind="quiet" onClick={() => onOpen(item)}>
          查看
        </AoiButton>
      </div>
    </div>
  );
};

const Lightbox = ({ item, canUpdate, canFinalize, onClose }) => {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [verdict, setVerdict] = useState("");
  const [action, setAction] = useState("");
  const [error, setError] = useState("");

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["aoi", "review"] });
  };

  const claim = useMutation({
    mutationFn: () => aoiFetch(`/api/review/workitems/${item.id}/claim`, { method: "POST" }),
    onSuccess: invalidate,
    onError: (err) => setError(err.message),
  });
  const finalize = useMutation({
    mutationFn: (payload) =>
      aoiFetch(`/api/review/workitems/${item.id}/finalize`, { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (err) => setError(err.message),
  });

  // Esc 关灯箱（暗房常识：手不用离开键盘）
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const forced = Boolean(item.forced) || bucketOf(item) === "low";
  const fact = item.fact;
  const submitFinalize = () => {
    setError("");
    if (!reason) {
      setError("请选择终裁理由");
      return;
    }
    if (forced && !action) {
      setError("低桶 / 强制复核的工作项必须选择处理动作（或回标注）");
      return;
    }
    const payload = { final_reason: reason };
    if (verdict) payload.verdict = verdict;
    if (action) payload.action = action;
    finalize.mutate(payload);
  };

  return (
    <div
      className="aoi-rv__overlay"
      role="dialog"
      aria-modal="true"
      aria-label={`工作项 #${item.id}`}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="aoi-rv__dialog">
        <div className="aoi-ds__stage aoi-ds__stage-inner" style={{ position: "relative" }}>
          <div className="aoi-ds__stage-head">
            <span className="aoi-ds__stage-label">工作项 #{item.id}</span>
            <span className="aoi-ds__stage-note">
              {fact ? `${fact.station_name ?? fact.station_code} · 序号 ${fact.seq}` : ""}
            </span>
          </div>
          <div className="aoi-rv__media">
            {item.image ? (
              <img src={item.image.url} alt={`工作项 ${item.id} 图像`} />
            ) : (
              <p className="aoi-rv__form-note">这条工作项没有登记图片。</p>
            )}
          </div>
          <div className="aoi-rv__facts">
            {fact ? (
              <>
                <span>
                  工位 <b>{fact.station_code}</b>
                </span>
                <span>
                  序号 <b>{fact.seq}</b>
                </span>
                {fact.captured_at ? (
                  <span>
                    拍摄 <b>{fact.captured_at.slice(0, 16).replace("T", " ")}</b>
                  </span>
                ) : null}
                {fact.latency_ms != null ? (
                  <span>
                    推理耗时 <b>{fact.latency_ms} ms</b>
                  </span>
                ) : null}
              </>
            ) : null}
            {item.model_ref ? (
              <span>
                模型 <b>{item.model_ref}</b>
              </span>
            ) : null}
            <span>
              状态 <b>{item.status}</b>
            </span>
          </div>

          {item.status === "finalized" ? (
            <p className="aoi-rv__form-note">
              已终裁：{item.final_reason ?? ""} {item.final_verdict ?? ""}
            </p>
          ) : (
            <>
              <div className="aoi-rv__form">
                <label className="aoi-rv__field">
                  终裁理由
                  <select value={reason} onChange={(event) => setReason(event.target.value)}>
                    <option value="">选择…</option>
                    {FINAL_REASONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="aoi-rv__field">
                  处理动作
                  <select value={action} onChange={(event) => setAction(event.target.value)}>
                    <option value="">（可选）</option>
                    {REVIEW_ACTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="aoi-rv__field">
                  终裁结论
                  <select value={verdict} onChange={(event) => setVerdict(event.target.value)}>
                    <option value="">（可选）</option>
                    {FINAL_VERDICTS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <AoiButton kind="onStage" disabled={!canFinalize || finalize.isPending} onClick={submitFinalize}>
                  提交终裁
                </AoiButton>
                {canUpdate && item.status === "pending" ? (
                  <AoiButton kind="ghost" disabled={claim.isPending} onClick={() => claim.mutate()}>
                    认领
                  </AoiButton>
                ) : null}
              </div>
              {forced ? (
                <p className="aoi-rv__form-note">
                  低桶 / 强制复核：必须选择处理动作（已重标 / 无缺陷 / 不可标注）或提交标注。
                </p>
              ) : null}
              {error ? <p className="aoi-rv__form-error">{error}</p> : null}
            </>
          )}
          <AoiButton kind="quiet aoi-rv__close" onClick={onClose} aria-label="关闭">
            ✕
          </AoiButton>
        </div>
      </div>
    </div>
  );
};

export const ReviewPage = () => {
  const { has, isLoading: permsLoading } = usePerms();
  const [bucketFilter, setBucketFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [openId, setOpenId] = useState(null);

  const queueQuery = useQuery({
    queryKey: ["aoi", "review", "workitems"],
    queryFn: () => aoiFetch("/api/review/workitems?page_size=200"),
  });
  const badImagesQuery = useQuery({
    queryKey: ["aoi", "review", "bad-images"],
    queryFn: () => aoiFetch("/api/review/bad-images?page_size=100"),
  });
  const queryClient = useQueryClient();
  const handleBad = useMutation({
    mutationFn: (id) => aoiFetch(`/api/review/bad-images/${id}/handle`, { method: "POST", body: "{}" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["aoi", "review"] }),
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

  if (!has("review.view")) {
    return (
      <div className="aoi-ds">
        <div className="aoi-ds__wrap">
          <div className="aoi-ds__empty">无权访问此页面（需要复审查看权限）。</div>
        </div>
      </div>
    );
  }

  const items = queueQuery.data?.items ?? [];
  const counts = { "": items.length };
  for (const bucket of BUCKETS) counts[bucket.key] = 0;
  for (const item of items) {
    const key = bucketOf(item);
    if (key in counts) counts[key] += 1;
  }
  const visible = items.filter(
    (item) => (!bucketFilter || bucketOf(item) === bucketFilter) && (!statusFilter || item.status === statusFilter),
  );
  const openItem = items.find((item) => item.id === openId) ?? null;
  const badImages = badImagesQuery.data?.items ?? [];

  return (
    <div className="aoi-ds">
      <div className="aoi-ds__wrap">
        <header className="aoi-ds__head">
          <div>
            <h1 className="aoi-ds__title">复审</h1>
            <p className="aoi-ds__lede">
              B 侧推理回传的可疑帧按置信度分成三桶：绿桶模型确信无缺陷、黄桶复检、红桶必须人工。
              终裁结论会写回复审台账，作为下一轮训练的金标准来源。
            </p>
          </div>
        </header>

        <div className="aoi-ds__body">
          <div className="aoi-rv__filters" role="tablist" aria-label="按桶过滤">
            <button
              type="button"
              className={`aoi-rv__tab${bucketFilter === "" ? " aoi-rv__tab--active" : ""}`}
              onClick={() => setBucketFilter("")}
            >
              全部 <span className="aoi-rv__tab-count">{counts[""]}</span>
            </button>
            {BUCKETS.map((bucket) => (
              <button
                key={bucket.key}
                type="button"
                title={bucket.hint}
                className={`aoi-rv__tab${bucketFilter === bucket.key ? " aoi-rv__tab--active" : ""}`}
                onClick={() => setBucketFilter(bucket.key)}
              >
                <i className="aoi-rv__tab-dot" style={{ background: bucket.color }} />
                {bucket.label} <span className="aoi-rv__tab-count">{counts[bucket.key]}</span>
              </button>
            ))}
            <label className="aoi-rv__status">
              状态
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                {STATUS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {queueQuery.isLoading ? (
            <div className="aoi-ds__empty">
              <Spinner /> 加载队列…
            </div>
          ) : visible.length === 0 ? (
            <div className="aoi-ds__empty">
              <p className="aoi-ds__empty-title">队列是空的</p>
              <p>B 侧回传可疑帧（/api/ingest/findings）后，工作项会出现在这里；也可以先去「数据集」页跑预标。</p>
            </div>
          ) : (
            <div className="aoi-ds__ledger">
              {visible.map((item) => (
                <WorkitemRow key={item.id} item={item} onOpen={(row) => setOpenId(row.id)} />
              ))}
            </div>
          )}

          <section className="aoi-rv__section">
            <h2 className="aoi-rv__section-title">坏图</h2>
            {badImagesQuery.isLoading ? (
              <div className="aoi-ds__empty">
                <Spinner /> 加载…
              </div>
            ) : badImages.length === 0 ? (
              <div className="aoi-ds__empty">
                没有坏图登记：B 侧采集失败（/api/ingest/findings kind=bad）会出现在这里。
              </div>
            ) : (
              <div className="aoi-ds__ledger">
                {badImages.map((row) => (
                  <div key={row.id} className="aoi-ds__row">
                    <div>
                      <div className="aoi-ds__row-name">
                        {row.station_code} · 序号 {row.seq}
                      </div>
                      <div className="aoi-ds__row-meta">
                        {row.error_code ? <span>错误 {row.error_code}</span> : null}
                        {row.instance_code ? <span>实例 {row.instance_code}</span> : null}
                        {row.captured_at ? <span>拍摄 {row.captured_at.slice(0, 16).replace("T", " ")}</span> : null}
                      </div>
                    </div>
                    <div className="aoi-ds__row-actions">
                      {row.handled ? (
                        <span className="aoi-rv__handled">已核（#{row.handled_by ?? "—"}）</span>
                      ) : (
                        <AoiButton
                          kind="ghost"
                          disabled={!has("review.update") || handleBad.isPending}
                          onClick={() => handleBad.mutate(row.id)}
                        >
                          核过
                        </AoiButton>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>

      {openItem ? (
        <Lightbox
          item={openItem}
          canUpdate={has("review.update")}
          canFinalize={has("review.finalize")}
          onClose={() => setOpenId(null)}
        />
      ) : null}
    </div>
  );
};

ReviewPage.title = "Review";
ReviewPage.path = "/review";
