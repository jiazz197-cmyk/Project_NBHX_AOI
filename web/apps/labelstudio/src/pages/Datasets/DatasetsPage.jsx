/**
 * AOI「数据集」工作台（注入点注册；契约 §4.1，D5）。
 *
 * D5 收尾第四轮 · 重设计（frontend-design）：
 * 页面从"三张同款卡片 + tab"改成**一张连续工作台**——页头一句话说明 + 一条工序轨道
 * （① 建数据集 → ② 传图 → ③ 发布字典，编号是真序列，同时充当 tab 切换与状态摘要）
 * + 当前工序的工作区。颜色全部留给数据（缺陷类别 8 色 / 质检状态），chrome 只用宿主
 * 中性 token；唯一"大胆"之处是上传台面（常暗，见 Datasets.prefix.css 顶部说明）。
 *
 * 门控：`datasets.view`（Menubar 入口同码，见 CHANGES.md 注入点 3）。
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Spinner } from "../../components/Spinner/Spinner";
import { aoiFetch } from "../../aoi/api";
import { usePerms } from "../../aoi/usePerms";
import { AoiButton } from "./AoiButton";
import { DefectsPanel } from "./DefectsPanel";
import { ImagesPanel } from "./ImagesPanel";
import { DatasetsPanel } from "./DatasetsPanel";
import "./Datasets.css";

const STEP_KEYS = ["datasets", "images", "defects"];

export const DatasetsPage = () => {
  const { has, isLoading: permsLoading } = usePerms();
  // 缺省落在「传图片」：这是本页最常做的事（上传是主角），没有数据集时面板内会引导去建
  const [activeTab, setActiveTab] = useState("images");
  const [preselectedDatasetId, setPreselectedDatasetId] = useState("");
  const [wizardSignal, setWizardSignal] = useState(0);

  // 轨道上的状态摘要：三处都用与面板相同的 queryKey，react-query 会自动复用缓存，不额外发请求
  const datasetsQuery = useQuery({
    queryKey: ["aoi", "datasets"],
    queryFn: () => aoiFetch("/api/datasets?page_size=200"),
  });
  const imagesCountQuery = useQuery({
    queryKey: ["aoi", "images", "count"],
    queryFn: () => aoiFetch("/api/datasets/images?page_size=1"),
  });
  const latestDictQuery = useQuery({
    queryKey: ["aoi", "defect-versions", "latest"],
    queryFn: () => aoiFetch("/api/datasets/defects/versions?page_size=1"),
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

  if (!has("datasets.view")) {
    return (
      <div className="aoi-ds">
        <div className="aoi-ds__wrap">
          <div className="aoi-ds__empty">无权访问此页面（需要数据集查看权限）。</div>
        </div>
      </div>
    );
  }

  const datasetCount = datasetsQuery.data?.items?.length ?? 0;
  const imageCount = imagesCountQuery.data?.total ?? 0;
  const latestVersion = latestDictQuery.data?.items?.[0] ?? null;

  const stepMeta = {
    datasets: datasetCount ? `${datasetCount} 个` : "还没有",
    images: imageCount ? `${imageCount} 张` : "还没有",
    defects: latestVersion ? `最新 ${latestVersion.version}` : "未发布",
  };

  const handleDatasetReady = (datasetId) => {
    setPreselectedDatasetId(String(datasetId));
    setActiveTab("images");
  };

  const openWizard = () => {
    setActiveTab("datasets");
    setWizardSignal((value) => value + 1);
  };

  return (
    <div className="aoi-ds">
      <div className="aoi-ds__wrap">
        <header className="aoi-ds__head">
          <div>
            <h1 className="aoi-ds__title">数据集</h1>
            <p className="aoi-ds__lede">
              把产线图片导进一个数据集，交给标注；数据集创建时会自动生成对应的标注项目。
              缺陷字典决定标注时可选的类别，可以边收集数据边定版。
            </p>
          </div>
          {has("datasets.create") ? (
            <AoiButton kind="primary" onClick={openWizard}>
              新建数据集
            </AoiButton>
          ) : null}
        </header>

        <nav className="aoi-ds__rail" aria-label="数据集工序">
          {STEP_KEYS.map((key, index) => {
            const active = key === activeTab;
            const label = { datasets: "建数据集", images: "传图片", defects: "发布缺陷字典" }[key];
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
          {activeTab === "datasets" ? (
            <DatasetsPanel onDatasetReady={handleDatasetReady} openSignal={wizardSignal} />
          ) : activeTab === "images" ? (
            <ImagesPanel initialDatasetId={preselectedDatasetId} onNeedDataset={openWizard} />
          ) : (
            <DefectsPanel />
          )}
        </div>
      </div>
    </div>
  );
};

DatasetsPage.title = "Datasets";
DatasetsPage.path = "/datasets";
