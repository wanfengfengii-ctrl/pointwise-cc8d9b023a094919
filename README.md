# 澄浦河口监测日仓

Python 3.11 标准库与 SQLite。早班值班员验收测站源批并开立站日，计量员修正站日读数，换区经办员转交承办，交班员核对逐笔净差，审计员按冻结号领取当时的观测和来历。

## 运行

在项目根目录运行完整回归。

```sh
python3 -B check_project.py
```

运行临时数据目录中的完整工作剧本。

```sh
python3 -B -m warehouse demo
```

`.pointwise-runtime.json` 登记该命令行项目的运行入口，`verify` 执行完整回归，`demo` 运行上述工作剧本并核对实际账目。样例可用 `python3 -B -m warehouse init-sample ./sample-data` 持久受理并开户。重复初始化领取原受理件和初账。业务更正、当前承办及既有冻结成果继续保留。`examples/shift.json` 保存样例源批，目录默认配置 `east` 和 `west`。

## Python 接口

从 `warehouse` 导入 `Warehouse` 和下表业务函数。`Warehouse(path)` 是可关闭、可重开的存储句柄，支持 `with`。从 `intake.stations` 导入 `StationDay(station, date)` 和 `SourceReference(station, record, locator)`。日期用 `YYYY-MM-DD`。站号、区域、批号及办理号使用 1 至 64 个 ASCII 字母、数字、下划线或连字符，首字符为字母或数字。`SourceBatch(batch_id, day, measurements)` 的有序明细使用 `Measurement(litres, source)`，从 `intake.batches` 和 `intake.measurements` 导入。出处站号须与站日一致，原记录及定位字段须为非空白文本。

| 函数 | 返回值与规则 |
| --- | --- |
| `admit(w, batch)` | `AcceptedBatch`，含受理号、原序源批和 `valid_measurements`。批号绑定整批内容和出处。 |
| `open_day(w, batch_id, region)` | `OpenedDay`，含站日、批号、初始区及初值。按原批及原初始区重投领取初账。 |
| `post(w, day, correction_id, region, litres)` | `PostingReceipt`，含实际旧值、新值、净差、正式序号和原签发区及代次。办理号在更正业务内唯一，绑定站日和升数。已有首执从当前正式账领取。新办理要求所传区拥有本站日的正式入账资格。 |
| `move(w, day, move_id, target)` | `MoveResult`，含新旧承办区及代次和已交接正式分录数。同号同参可续办或复领，每个站日同时最多一笔在办换区。 |
| `reconcile_day(w, day)` | `ShiftReport`，含承办区、初值、现值、按提交次序排列的分录及净差合计。 |
| `freeze(w, day)` | `FreezeResult`，含冻结号、站日及冻结升数。每次成功冻结分配独立编号。 |
| `get_frozen(w, number)` | `FrozenFacts`，含原序源批、初值、冻结时现值、承办区代次及所见正式分录。 |

计量和差额均为精确整数升数。布尔值无计量资格。`None` 表示有出处的缺测，`0` 是有效观测。零差更正也占一个正式序号。分别保存目录、各区账、源批和冻结档案。初始化先登记待发布承办，再写区域初账，接着发布。换区准备可暂停，旧区仍能为本站日办理，其他站日也可以继续入账。新区完整实收已成立的分录和首执后方可公布承办。实收完成至目录发布之间，旧账仍可领取，旧区的正式写入资格已经结束。换区新增计量分录数为零。目录发布后可用 `w.close_region('east')` 关闭旧区句柄，西区仍可继续办理。冻结档案提交后可独立领取。

`storage` 定义 `InvalidInput`、`Conflict`、`NotFound`、`NotOwner`、`Unavailable` 和 `InconsistentBook`。`reconcile.discrepancies.ReconciliationError` 报告不完整或不一致的正式账。存储失败保留 SQLite 异常供调用者区分。跨库操作中断可能留下合法的待办，按原参数重投继续处理。`Warehouse(events=callback)` 可接收本地事务结束后的 `(event, payload)`，用于按明确顺序观察和暂停操作。

## 样例与事故复核

早班两条有效采样 3 L 和 4 L 合计 7 L，夹在其中的缺测仍有出处。开户后冻结 7 L。换区准备暂停时，东区 C1 已正式更正到 11 L，提交后回包丢失。西区接办后，C2 更正到 16 L 却记录了 +9 L。正确的两笔分录分别为 +4 L 和 +5 L，共计 +9 L。西区应能复领 C1 的原首执，冻结号仍领取 7 L 和原序出处。

```sh
python3 -B -m unittest -v tests.test_transfer.TransferTests.test_receipt_after_move
```

另一轮让 C1 停在仅准备阶段，等西区生效后才恢复东区调用。东区迟到调用应报 `NotOwner`，东区账仍为 7 L 且无分录和首执，西区 C2 应从 7 L 记 +9 L。

```sh
python3 -B -m unittest -v tests.test_transfer.TransferTests.test_prepared_is_not_posted
```

完整回归同时核对实收后重开续办、目标写入失败后续投、源批冲突、零升、负净差、冻结写入回滚及账链断裂。演示用样例源批从开户走到关闭东区后的西区核账及冻结领取。
