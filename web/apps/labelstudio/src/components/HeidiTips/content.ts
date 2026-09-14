import type { TipsCollection } from "./types";

/**
 * AOI 平台提示文案（D4 素材更换）。
 *
 * - 文案与 `label_studio/aoi/core/heidi_tips.py` 保持一致：服务端 `/heidi-tips` 已遮蔽上游的
 *   GitHub 代理路由，联网时返回的也是同一套文案；这里保留一份作为离线/首次加载的默认值。
 * - `link.url` **必须是绝对地址**：`utils.ts::createURL` 内部是 `new URL(base)`，相对路径会抛错。
 */
const origin = () => window.location.origin;

export const defaultTipsCollection: TipsCollection = {
  projectCreation: [
    {
      title: "先建数据集，再进标注",
      content:
        "AOI 流程是：数据集 → 缺陷字典 → 导入图片 → 训练 → 发布模型。直接从「新建项目」建的项目不会纳入 AOI 数据集管理。",
      closable: true,
      link: {
        label: "前往数据集",
        url: `${origin()}/datasets`,
      },
    },
    {
      title: "图片从这里导入",
      content: "在「数据集」页上传的图片会自动去重并做坏图质检，导入完成后标注页才会出现任务。",
      closable: true,
      link: {
        label: "打开数据集",
        url: `${origin()}/datasets`,
      },
    },
  ],
  organizationPage: [
    {
      title: "平台有三个角色",
      content: "操作员负责标注与复审；管理员负责数据集、训练与模型发布；超级管理员额外管理角色授权与审计。",
      closable: true,
      link: {
        label: "权限说明",
        url: `${origin()}/system`,
      },
    },
    {
      title: "权限在平台内管理",
      content: "AOI 的权限不依赖 Label Studio 组织设置，请在「系统」页分配角色。",
      closable: true,
      link: {
        label: "打开系统页",
        url: `${origin()}/system`,
      },
    },
  ],
  projectSettings: [
    {
      title: "标签来自缺陷字典",
      content: "标注界面的标签由缺陷字典渲染；改字典请到「数据集 → 缺陷字典」，发布新版本后生效。",
      closable: true,
      link: {
        label: "打开缺陷字典",
        url: `${origin()}/datasets`,
      },
    },
    {
      title: "OK 图也要标",
      content: "没有缺陷的图片请提交空标注；训练需要负样本，否则模型会倾向漏检。",
      closable: true,
      link: {
        label: "查看标注规范",
        url: `${origin()}/datasets`,
      },
    },
  ],
};
