/**
 * AOI 二开占位页（注入点，见 CHANGES.md）。
 * 仅注册路由与最小空壳，正式页面在 D4+ 实现；不侵入上游组件树。
 */
export const DatasetsPage = () => (
  <div style={{ padding: 24 }}>
    <h2 style={{ marginBottom: 8 }}>Datasets</h2>
    <p style={{ color: "#8c8c8c" }}>AOI 数据集页面占位（D4+ 实现）。</p>
  </div>
);

DatasetsPage.title = "Datasets";
DatasetsPage.path = "/datasets";
