# 校准剖面数据契约

## 直接标准基线（保持不变）

- 输入按 `borehole`、`version` 标识，计划层 `depths_mm` 是不重复的非负整数，`max_reference_span_s` 为正整数秒。参考行含 `probe`、`at_s`、`observed_mc`、`certified_mc`，观测行含 `probe`、`at_s`、`depth_mm`、`observed_mc`。温度使用整数毫摄氏度；每种行的数组分别从 1 开始提供来源序号。
- 以同探头的 `observed_mc - certified_mc` 计算参考漂移。命中参考时刻直接校正，否则用紧邻时间点线性插值，不跨过最大参考跨度、不外推，也不跨探头借用参考。重复的探头参考时刻是输入冲突。对有效观测减去漂移，保留精确分数及参考行。
- 按实际计划深度产出有序事实。每个深度只用有效校正值求中位数，没有有效值则留 `null`。观测拒收原因依次为 `unplanned_depth`、`no_probe_reference`、`outside_reference_range`、`reference_span_exceeded`（以适用的第一项为准）；拒收数据保留原始测量和可用参考证据。
- SQLite 同事务冻结来源、摘要、深度事实与拒收行。同版本同摘要幂等；参考点更正需使用不同 `version`，不能重写旧版本。

## 共址联测证书与停用假设（扩展）

进不了温槽的探头没有直接标准，只能通过共址联测证书接到直接标准。

- `certificates[]`：每张证书含整张共用的 `common_error_mc_min/max`（一个共用误差变量，耦合该证书全部行）、`valid_from_s/valid_to_s` 有效时段，以及多行 `rows`（两个不同探头在同一 `at_s` 的共址原始读数）。联测行落在有效时段之外即输入冲突；证书多行必须共同成立。
- `hypotheses[]`：两张证书相互矛盾时，每个允许假设用 `suspended_certificates` 停用其中一张。停用不同证书会得到各自自洽但不同的剖面；假设下系统不可行（`feasible=false`）时该假设不产事实。
- 漂移沿“直接标准探头 → 证书方程 → 间接探头”传播，方程为 `d_a - d_b = observed_a - observed_b + e_cert`。间接探头在自己的派生时间轴上插值，同样受 `max_reference_span_s` 约束，必须夹住观测时刻，不能对开口时段外推。连不到直接标准的连通分量只持有自由锚点，只能交相对值。
- `temperature_width_limit_mc`：温度宽度限额；条件中位范围超宽时 `within_width_limit=false`。

## 联合可行域（关键约束）

共用误差变量把同一张证书的所有行耦合起来。所有范围都在误差变量的**同一个联合可行域**上用精确有理数线性规划（`linsolve.py`，两阶段单纯形）求极值：

- 每个可签深度的中位温度范围、以及要与已签参考层一起使用的温差范围，都来自该假设下整组证据的可行取值，禁止把各层分别取到的边际极值拼成一个并不存在的温差。
- 温差是对“浅层中位数 − 深层中位数”的单一联合优化，两层共享同一误差赋值；同号共误差会在温差中精确抵消。
- 两层各只持有一份不同假设的核验时，即使两层边际范围恰好相同，也不产出联合温差；无条件剖面里该温差标记为不可签。
- 未连到直接标准的分量，绝对中位数拒收（`relative_only_component`）；同一自由锚点在温差中抵消时可交相对温差，跨自由分量拒收。

## 条件剖面、无条件剖面与交付

- 主管可交一份对所有可行假设都成立的**无条件**范围（各假设范围取交集；不相交则该层/温差不可签），更多人能用但有些深度会超宽或不可签。
- 也可签更窄的**条件**剖面，标注其 `hypothesis`、覆盖观测时段 `coverage_window_s` 与生效/停用证书范围，供证书核验结论对应得上的用户先用。
- `delivery_requests[]`：交付方用日常剖面读取一组深度和温差。条件读回（带 `hypothesis`）必须拿出覆盖这些观测时段的同一假设依据；拿不出时返回 `pending` 与待核原因，受限结果绝不作为普通温度交付。
- 后补证书（`supplement.supplement`）只确认部分时段时，现行交付不把它扩到整孔：报告逐层 `fully_covered`，指出哪些层或温差已可用、哪些仍不可读为已签；`scope_rewritten=false`，原版本及原有条件凭据的作用域不随之改写。

## 模块

`borecal/contract.py` 解析输入；`borecal/drift.py` 维护直接标准时间索引；`borecal/certmodel.py` 在假设下传播证书漂移并区分有锚/自由分量；`borecal/linsolve.py` 是精确有理数两阶段单纯形；`borecal/affineexpr.py` 提供仿射表达式；`borecal/ranges.py` 在联合可行域上求中位与联合温差范围；`borecal/assess.py` 评估假设并组装条件/无条件剖面；`borecal/delivery.py` 做覆盖核验与交付台账；`borecal/supplement.py` 处理部分覆盖的后补证书；`borecal/profile.py` 输出事实；`borecal/archive.py` 负责发布和读取。
