/**
 * AOI「数据集」页（注入点注册；契约 §4.1，D5）。
 * 三块：缺陷字典（DefectsPanel）/ 图片导入与列表（ImagesPanel）/ 数据集与版本（DatasetsPanel）。
 * 页面入口门控：`datasets.view`（Menubar 入口同码，见 CHANGES.md 注入点 3）。
 * 样式：Tailwind 语义 token（@humansignal/ui），暗色随 data-color-scheme 自动翻转。
 */
import { useState } from "react";
import { Spinner } from "../../components/Spinner/Spinner";
import { usePerms } from "../../aoi/usePerms";
import { PAGE, LOADING } from "../../aoi/uiTokens";
import { DefectsPanel } from "./DefectsPanel";
import { ImagesPanel } from "./ImagesPanel";
import { DatasetsPanel } from "./DatasetsPanel";

const TABS = [
  { key: "defects", label: "缺陷字典", component: DefectsPanel },
  { key: "images", label: "图片", component: ImagesPanel },
  { key: "datasets", label: "数据集", component: DatasetsPanel },
];

const TAB_ITEM_ACTIVE = "bg-neutral-surface text-neutral-content shadow-sm";
const TAB_ITEM_IDLE = "text-neutral-content-subtle hover:text-neutral-content";

export const DatasetsPage = () => {
  const { has, isLoading: permsLoading } = usePerms();
  const [activeTab, setActiveTab] = useState("defects");

  if (permsLoading) {
    return (
      <div className={`${PAGE} flex items-center justify-center`}>
        <div className={LOADING}>
          <Spinner /> 加载中…
        </div>
      </div>
    );
  }

  if (!has("datasets.view")) {
    return (
      <div className={PAGE}>
        <div className="mx-auto max-w-6xl px-10 py-10">
          <div className={LOADING}>无权访问此页面（需要数据集查看权限）。</div>
        </div>
      </div>
    );
  }

  const ActivePanel = TABS.find((tab) => tab.key === activeTab)?.component ?? DefectsPanel;

  return (
    <div className={PAGE}>
      <div className="mx-auto max-w-6xl px-10 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold text-neutral-content">数据集</h1>
          <p className="mt-1 max-w-3xl text-sm text-neutral-content-subtle">
            维护缺陷字典、导入标注图片并管理数据集版本；创建数据集时自动生成对应的标注项目。
          </p>
        </header>

        <nav
          aria-label="数据集页签"
          className="mb-5 inline-flex items-center gap-1 rounded-lg border border-neutral-border-subtle bg-neutral-surface-inset p-1"
        >
          {TABS.map((tab) => {
            const active = tab.key === activeTab;
            return (
              <button
                key={tab.key}
                type="button"
                aria-selected={active}
                role="tab"
                onClick={() => setActiveTab(tab.key)}
                className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                  active ? TAB_ITEM_ACTIVE : TAB_ITEM_IDLE
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </nav>

        <div role="tabpanel">
          <ActivePanel />
        </div>
      </div>
    </div>
  );
};

DatasetsPage.title = "Datasets";
DatasetsPage.path = "/datasets";
