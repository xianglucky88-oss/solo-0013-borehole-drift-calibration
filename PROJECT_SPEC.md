# 校准剖面数据契约

- 输入按 `borehole`、`version` 标识，计划层 `depths_mm` 是不重复的非负整数，`max_reference_span_s` 为正整数秒。参考行含 `probe`、`at_s`、`observed_mc`、`certified_mc`，观测行含 `probe`、`at_s`、`depth_mm`、`observed_mc`。温度使用整数毫摄氏度；每种行的数组分别从 1 开始提供来源序号。
- 以同探头的 `observed_mc - certified_mc` 计算参考漂移。命中参考时刻直接校正，否则用紧邻时间点线性插值，不跨过最大参考跨度、不外推，也不跨探头借用参考。重复的探头参考时刻是输入冲突。对有效观测减去漂移，保留精确分数及参考行。
- 按实际计划深度产出有序事实。每个深度只用有效校正值求中位数，没有有效值则留 `null`。观测拒收原因依次为 `unplanned_depth`、`no_probe_reference`、`outside_reference_range`、`reference_span_exceeded`（以适用的第一项为准）；拒收数据保留原始测量和可用参考证据。
- SQLite 同事务冻结来源、摘要、深度事实与拒收行。同版本同摘要幂等；参考点更正需使用不同 `version`，不能重写旧版本。

`borecal/contract.py` 解析输入，`borecal/drift.py` 维护时间索引，`borecal/profile.py` 输出分深度事实，`borecal/archive.py` 负责发布和读取。
