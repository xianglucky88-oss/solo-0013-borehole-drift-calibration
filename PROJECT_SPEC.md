# 校准剖面数据契约

## 基础契约

- 输入按 `borehole`、`version` 标识，计划层 `depths_mm` 是不重复的非负整数，`max_reference_span_s` 为正整数秒。参考行含 `probe`、`at_s`、`observed_mc`、`certified_mc`，观测行含 `probe`、`at_s`、`depth_mm`、`observed_mc`。温度使用整数毫摄氏度；每种行的数组分别从 1 开始提供来源序号。
- 以同探头的 `observed_mc - certified_mc` 计算参考漂移。命中参考时刻直接校正，否则用紧邻时间点线性插值，不跨过最大参考跨度、不外推，也不跨探头借用参考。重复的探头参考时刻是输入冲突。对有效观测减去漂移，保留精确分数及参考行。
- 按实际计划深度产出有序事实。每个深度只用有效校正值求中位数，没有有效值则留 `null`。观测拒收原因依次为 `unplanned_depth`、`no_probe_reference`、`outside_reference_range`、`reference_span_exceeded`（以适用的第一项为准）；拒收数据保留原始测量和可用参考证据。
- SQLite 同事务冻结来源、摘要、深度事实与拒收行。同版本同摘要幂等；参考点更正需使用不同 `version`，不能重写旧版本。

`borecal/contract.py` 解析输入，`borecal/drift.py` 维护时间索引，`borecal/profile.py` 输出分深度事实，`borecal/archive.py` 负责发布和读取。

## 停留计划与签发窗口（`borecal/dwell.py`）

- 输入可选 `stability`（`stable_duration_s`、`tolerance_mc`、`sampling_interval_s`）、`dwells`（`dwell_id`、`probe`、`depth_mm`、`order`、`start_s`、`end_s`）与 `sign_policy`。有停留计划时稳定性参数必填，停留深度必须在 `depths_mm` 内；同一探头的停留时间区间不得重叠，否则双方标记 `conflicting_dwell`，其读数不能被相邻停留借用。
- 只使用**签发当时已经收到**的参考（`at_s <= 签发时刻`）校正。线性插值区间内若参考斜率变化，整个区间仍按最大跨度与温差整体判定；缺右侧参考而未确认的尾段产生 `outside_reference_range`，拒收记录与冲突停留都不能被前后点跨过补足。同一探头在停留内出现重复时刻读数属于输入冲突。
- 稳定窗口要求窗口内连续（相邻读数间隔不超过 `sampling_interval_s`）、跨度至少 `stable_duration_s`、校正温差不超过 `tolerance_mc`。拒收读数天然打断连续性。
- 两种签发策略：
  - `first_window`：在首个完整可证窗口达标时签发，`extra_wait_s=0`，窗口后的更密读数不再纳入。
  - `dwell_end`：按预案等到停留结束，选取停留内最长窗口；`first_signable_at_s`、`signed_at_s`、`wait_used_s`、`extra_wait_s` 同时给出，等待代价可直接读出。
- 每个签发窗口冻结 `reference_snapshot`（当时参考行及漂移量），使旧窗口可脱离后来参考精确复读。

## 交付与迟到参考复核

- 有停留计划的深度只交付被签窗口及其依据的有效参考；中位温度按**时间加权**（时间而非行数）计算，并给出 `min_mc`/`max_mc` 范围。窗口之外后来一串更密读数不能挤掉已签结果。无可信签发的计划层 `median_mc=null`、`status=unconfirmed`，不得作为已确认温度交付。
- 停留之外的读数进 `unused_readings`（`outside_dwell` 或 `unplanned_depth`），不进入任何深度事实。
- 迟到参考通过带 `review_of` 的新版本体现，旧版本保持冻结。复核对每个旧停留给出 `falsified`（新参考下旧窗口失效）、`supported`、`alternative_also_supported`、`alternative_supported`（旧未签发，新参考另证一个窗口）等状态，并列出 `affected_depths_mm`、受影响深度事实与原因；`replay_with_original_view_holds` 用冻结快照复读原签剖面。复核结论只出现在新版本中，`read` 旧版本仍返回原剖面。
- 没有停留计划的旧资料走原有口径（逐行中位数、原字段），行为与输出保持不变。
