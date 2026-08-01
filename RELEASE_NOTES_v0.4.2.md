# InsightFlow Pro v0.4.2 Release Notes

v0.4.2 是一次 Executive UI & Design System 升级，保留 v0.4.1 的业务逻辑、只读安全、行动持久化和分析能力，重点提升管理层阅读效率、视觉一致性和招聘演示效果。

## 主要变化

- 新增完整 Streamlit Design System：颜色、字体、间距、阴影、圆角、按钮、Tabs、表格和提示框统一管理。
- 侧边栏改为深海军蓝品牌导航，并采用 Material Symbols 页面图标。
- 所有业务页面新增统一英文眉题、中文主标题和业务说明。
- 管理层总览重新设计为五张主KPI卡和三张辅助指标卡，降低同屏拥挤。
- 管理层提示改为分级问题卡片，P0—P3使用克制的状态色和证据化表述。
- Plotly注册全局专业模板，统一色板、网格、字体、悬浮提示和图例位置。
- 销售趋势改用中文指标名，主图线宽、标记和交互提示统一。
- 利润页面的六张KPI改为两行三列，提高笔记本屏幕可读性。
- 经营分析助手改为输入区和结果区两块独立卡片，并强化可验证查询信息。
- 信任中心将数据质量与四类数据状态合并为同一KPI层级。
- 新增 `.streamlit/config.toml` 主题配置。
- 新增静态界面预览 HTML 和 PNG，便于README、简历和作品集展示。

## 验证

- Python编译检查通过。
- 19项后端测试全部通过。
- 核心业务逻辑未改变。
- 静态UI预览在1600×1050视口完成渲染检查。

## 使用

```powershell
pip install -r requirements.txt
insightflow bootstrap
insightflow run
```
