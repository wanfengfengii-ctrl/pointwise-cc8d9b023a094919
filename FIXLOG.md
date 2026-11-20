# 日仓换区修复记录

## 根因

`handoff/resume.py` 的换区续办只在 `candidate_copied` 前读取一次旧区账像作为候选，
之后既不结算旧区，也不把最终账像重新装入新区，直接对过期候选验收并发布目录。导致：

1. 准备暂停期间旧区正式入账的分录（如东区 C1：7 L → 11 L，回包丢失）被换区整体丢弃，
   西区接办后 C2 从 7 L 记成 +9 L，而非自 11 L 计 +5 L。
2. 旧区账没有任何封存标记，仅完成准备的迟到调用在换区发布后仍能在旧区补签正式分录。
3. `RegionStore.stage_day` 已有的 `final=True` 重装路径从未被调用。

## 修复

- `ledger/region_store.py`：`books` 增加 `settled_move` 列（含对既有库的
  `ALTER TABLE` 迁移）；新增 `settle_day`，在同一写事务内原子封存旧区账并返回最终账像，
  同号换区幂等，异号拒绝。
- `handoff/resume.py`：候选拷贝后先 `settle_day` 结算旧区（`source_settled` 事件携带
  最终账像），再以 `final=True` 把最终账像重装新区，然后验收、发布。各步均可按原参数重投。
- `ledger/postings.py`、`ledger/preparations.py`：已封存账上的新准备与正式提交报
  `NotOwner`；既有首执仍从当前正式账复领，旧账在目录发布前仍可读取。

修复后行为：准备暂停期间旧区仍可为本站日及其他站日正式入账；结算点之后旧区写入资格
结束；新区完整实收已成立分录与首执（C1 +4 L）后才发布目录，C2 自 11 L 计 +5 L，净差
合计 +9 L；换区本身不新增计量分录；C1 仅准备时换区移交 frontier 为 0，迟到调用报
`NotOwner`，西区 C2 自 7 L 计 +9 L；关闭东区后仍可复领 C1 原首执，原冻结账仍为 7 L。

## 实测

- `python3 -B check_project.py`：31 项全部通过（原 28 项 + 新增
  `tests/test_settlement.py` 3 项回归：结算后旧区封存拒写、仅准备更正在新区续办、
  目标装入失败后旧区保持封存且重投完成）。
- `python3 -B -m warehouse demo`：输出与预期一致（C1 +4 L、C2 +5 L、净 +9 L、
  冻结 7 L、原序出处完整）。
- `python3 -B -m warehouse init-sample <目录>` 重复执行领取原受理件与初账；
  旧版（无 `settled_move` 列）区域库打开后自动迁移并可正常结算。
