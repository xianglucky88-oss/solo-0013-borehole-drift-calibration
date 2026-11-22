# 钻孔温度探头漂移校准

**数据工程 · 数据分析与数据应用。** 将探头原始温度与参考点对齐，产出分深度校准剖面和拒收证据，并冻结可复读的数据版本。该仓库不负责现场设备控制。

在仓库根目录以 Python 3.9+ 运行：

```sh
python3 -B -m borecal --db demo.sqlite publish examples/boring.json
python3 -B -m borecal --db demo.sqlite read basalt-17 winter-c01
python3 -B examples/smoke.py
```

示例有 3 个计划深度，只有前两层形成有效中位数。更正单探头参考点后重新发布，只改变受影响深度的校准结果，旧版可复核。

## 共址联测证书与停用假设

进不了温槽的探头通过共址联测证书接到直接标准。两张相互矛盾的证书分别停用其一会得到自洽但不同的条件剖面：

```sh
python3 -B -m borecal --db demo.sqlite publish examples/certified.json
python3 -B -m borecal --db demo.sqlite read basalt-17 winter-c03
python3 -B -m borecal --db demo.sqlite delivery basalt-17 winter-c03
python3 -B examples/certified_smoke.py
```

- 每张证书的共用误差是一个有界变量，耦合其全部行；所有中位范围与联合温差都在该误差变量的同一可行域上用精确有理数线性规划求极值，不会把各层边际极值拼成不存在的温差。
- 无条件剖面对所有可行假设取交集；条件剖面标注假设、覆盖时段与证书范围，受限结果只作为条件交付，不能当普通温度。
- 连不到直接标准的分量只交相对值；两层各持不同假设时不发联合温差。
- 后补证书只覆盖部分时段时不扩到整孔、不改写原版本，见 `borecal/supplement.py` 与 `examples/supplement.json`。

详见 [PROJECT_SPEC.md](PROJECT_SPEC.md)。
