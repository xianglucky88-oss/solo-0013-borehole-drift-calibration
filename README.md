# 钻孔温度探头漂移校准

**数据工程 · 数据分析与数据应用。** 将探头原始温度与参考点对齐，产出分深度校准剖面和拒收证据，并冻结可复读的数据版本。该仓库不负责现场设备控制。

在仓库根目录以 Python 3.9+ 运行：

```sh
python3 -B -m borecal --db demo.sqlite publish examples/boring.json
python3 -B -m borecal --db demo.sqlite read basalt-17 winter-c01
python3 -B examples/smoke.py
```

示例有 3 个计划深度，只有前两层形成有效中位数。更正单探头参考点后重新发布，只改变受影响深度的校准结果，旧版可复核。

## 停留计划、签发窗口与迟到参考

带 `dwells` 的资料按停留管理稳定窗口与交付事实：

```sh
python3 -B -m borecal --db demo.sqlite publish examples/dwell.json
python3 -B -m borecal --db demo.sqlite read basalt-18 dwell-c01
python3 -B -m borecal --db demo.sqlite publish examples/review-1.json
python3 -B -m borecal --db demo.sqlite publish examples/review-2.json
python3 -B -m borecal --db demo.sqlite review basalt-19 dwell-r02
python3 -B examples/dwell_smoke.py
```

- `first_window` 在首个完整可证窗口达标时即可签发并提前提起探头；`dwell_end` 等到停留结束换取更长连续证据，等待代价由 `first_signable_at_s`、`signed_at_s`、`wait_used_s`、`extra_wait_s` 体现。
- 缺右侧参考的尾段、拒收读数、互相冲突的停留都不能被前后点跨过；计划层只有被签窗口能确认，中位温度按时间（而非行数）加权，窗口外更密读数不能挤掉已签结果。
- 迟到参考只能在带 `review_of` 的新版本中体现：可能证伪旧窗口或另证新窗口，`review` 子命令给出受影响深度和原因；旧版本冻结，`read` 仍复读原签剖面。
- 没有停留计划的旧资料沿用原有逐行中位数口径。

详见 [PROJECT_SPEC.md](PROJECT_SPEC.md)。
