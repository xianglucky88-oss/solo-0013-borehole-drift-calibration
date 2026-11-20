# 钻孔温度探头漂移校准

**数据工程 · 数据分析与数据应用。** 将探头原始温度与参考点对齐，产出分深度校准剖面和拒收证据，并冻结可复读的数据版本。该仓库不负责现场设备控制。

在仓库根目录以 Python 3.9+ 运行：

```sh
python3 -B -m borecal --db demo.sqlite publish examples/boring.json
python3 -B -m borecal --db demo.sqlite read basalt-17 winter-c01
python3 -B examples/smoke.py
```

示例有 3 个计划深度，只有前两层形成有效中位数。更正单探头参考点后重新发布，只改变受影响深度的校准结果，旧版可复核。详见 [PROJECT_SPEC.md](PROJECT_SPEC.md)。
