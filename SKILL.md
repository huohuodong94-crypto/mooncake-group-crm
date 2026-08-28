---
name: mooncake-group-crm
description: 月饼哥哥门店团购客户与商机台账助手。用于登记或更新团购线索、记录跟进、调整阶段、查询到期商机、生成周月复盘、导出或同步客户商机双表到指定飞书多维表格，以及委派内部组盒报价；将店长的文字输入抽取为结构化记录，经校验和明确确认后写入台账。不用于语音识别、自动联系客户或面向客户生成正式报价。
---

# 门店团购客户与商机管理助手

## 核心约束

- 新增商机必须具备客户名称、联系人、联系电话/微信、所属门店、客户需求、公司地址（联系人所在地址，不是配送地址）、线索来源、需求类别和意向等级；缺失或含糊时每次只追问一项，不猜测、不落库。
- `store` 允许 6 个标准归属值：月湖店、体验中心店、国金店、五一店、花样汇店、市场部；旧名称“体验店”仍归一为“体验中心店”。“市场部”按独立归属单位参与录入、查询、导出和汇总。
- 意向等级只允许 A/B/C/D；阶段只允许“初次接触 → 需求确认 → 方案报价 → 谈判中 → 已签约 → 已回款”，任一未成交阶段可进入“已流失”，且流失原因必填。不得使用旧的“已成交”“暂缓跟进”等阶段。
- 需求类别只允许散装、68礼盒、98礼盒、138礼盒、定制礼盒、待定。单盒预算命中 68/98/138 元档时用对应枚举；未命中时建议“定制礼盒”并确认；无法判断时用“待定”并追问。客户原话中的产品名不能直接当需求类别。
- 提醒按 A=3 天、B=5 天、C=7 天计算；“方案报价”统一按 2 天并优先于意向等级。口述日期只写入跟进内容，不覆盖提醒；仅 D 级无默认天数时可采用经确认的口述日期。
- 只抽取语音/文字来源字段；编号由引擎生成，门店和跟进人优先由账号上下文带入，总部维护字段首次留空。
- 金额、数量、电话和日期必须逐项回读并得到明确确认；未确认时不得添加 `--confirmed`，不得绕过引擎返回的 `needs_confirmation`。
- 所有写入先通过校验，再展示预览并等待确认。组盒报价必须委派给 `mooncake-brother-quote-tool`，本 Skill 不自行计算价格。
- 飞书双表的固定目标是：`https://ccn3dhq4y5he.feishu.cn/base/FjMNbdLI1ab87Us3fTmcmROWnJb?table=tblJgewTBFUQx8Mm&view=vewjFD8466`。目标类型是飞书多维表格；在线同步通过 `scripts/sync_feishu_bitable.py`（或 `crm.py --mode sync-feishu`）调用 lark-cli 执行，需 lark-cli 已登录且当前账号对目标 Base 有编辑权限。联系人、电话、地址、金额等数据写入飞书前必须在动作发生前再次明确确认。

## 概述

把门店店长的语音或文字(语音已由微信自动转成文字,本 Skill 只接收文本)抽取成结构化记录,串成一条可运转的团购作业闭环:随手录入 → 持续跟进 → 到期提醒 → 成交/流失 → 周月复盘。台账对齐《月饼哥哥_团购客户管理双表模板_语音字段标注版》,字段按来源三分:**绿色=店长语音自动提取**、**蓝色=系统自动生成/按账号带出**、**橙色=总部补充确认**(逐字段映射见 `references/crm-rules.json` 的 `field_provenance`)。双表为:

- **门店客户商机表**:一条团购需求/商机一行,含联系人、意向、阶段、最近跟进、下次跟进日期、成交/流失等内联字段。
- **总部客户档案表**:一家客户一行,沉淀历史成交次数、累计/本年度成交金额与客户偏好,供总部维护。

设计原则:

- **Skill 是编排者,脚本全确定性**。抽取与分类由当前 Agent 按契约完成;`scripts/` 下的脚本绝不调用模型,只做校验、台账读写、提醒计算、汇总、导出与报价委派。
- **带检查点的流水线 + 反猜(Inversion)**。缺必填字段先追问、不猜;校验是硬闸口;写库前给店长预览并等确认。
- **契约优先(Contract-First)**。抽取记录的结构唯一真相源是 `references/output-schema.json`,校验脚本读它把关。
- **报价复用**。组盒报价委派给同目录的 `mooncake-brother-quote-tool`,价格规则不在本 Skill 内复制。

## 何时使用

店长或管理者需要:登记团购线索/新增客户、记录一次跟进、修改商机阶段或下次跟进日期、标记成交或流失、按预算组盒报价、查本周未跟进/逾期客户、做周月复盘、把台账导出成双表 Excel 时使用。

当用户说“同步双表到飞书”“更新飞书多维表格”或明确提供上述固定链接时，读取 `references/feishu-bitable-sync.md` 并执行在线同步工作流。

不要用于:语音识别(输入须是文字)、自动抓取微信聊天、自动联系客户、销售额预测、自动审批报价、定时主动推送、以及面向客户的团购阶梯报价单(本 Skill 的报价是内部组盒成本核算)。

## 使用示例

- “今天拜访了八方金服的王总，对方计划采购 300 盒经典礼盒，预算大概 4.5 万元，已经发了报价方案，下周一再联系，我是国金店张店长。” → 抽成新增记录；意向等级未说清时先追问 A/B/C/D；**“经典礼盒”是产品原话不是需求类别，单盒预算 45000÷300=150 元不落在 68/98/138 档 → 需求类别判「定制礼盒」并向店长确认**；公司地址/线索来源缺失时追问补齐。注意：**客户说“下周一再联系”不覆盖 ABCD 提醒**，下次跟进仍按规则推算（方案报价 2 天），口述时间记入跟进内容。
- "八方金服王总说这周内给答复。" → 定位该商机,追加一条跟进,按规则重算下次跟进日期。
- "八方金服签约了" → 标记"已签约"(不需金额,关闭普通回访)。"已回款 4.5 万" → 标记"已回款",必填回款日期+回款金额。
- "把那个地产客户标成流失,预算被砍了。" → 标记"已流失",记录流失原因。
- "这周有哪些客户该跟进了?" → 输出逾期/今日到期/将到期清单,附跟进话术。
- "出一下本周复盘。" → 先读复盘方法论,再汇总成文本 + 自包含 HTML 周报。
- "客户单盒预算 70、要 500 盒、长沙市内、不要点心,先给 3 套方案。" → 委派报价工具出候选组合。

推荐语音模板（店长照此口述，抽取最稳）：“今天联系了【客户名称】的【联系人】，地址【公司地址】，【线索来源】，客户需要【产品/用途/需求类别】，预计【数量】，预算【金额】，目前进展到【阶段】，沟通情况是【结果】，计划【日期】再次跟进（注：口述日期只记录，提醒仍按 A/B/C 天数）。"

## 参数列表

引擎入口 `scripts/crm.py`,`--mode/-m` 必填,`--json` 输出 JSON,`--data` 指定台账路径(默认 `data/ledger.json`),`--today` 指定基准日期(默认系统日期)。写入类模式(`add/update/log/close/apply`)只要含**金额/数量/电话/日期**就须加 `--confirmed`(店长已逐项确认),否则引擎拒写并返回 `needs_confirmation`;仅改阶段等不含这四类的更新无需该标志。

| 模式 | 用途 | 关键参数 |
|---|---|---|
| `add` | 新增客户+商机(find-or-create 客户) | 必填 `--name --contact --contact-phone --store --need --customer-address --source --demand-category --intent-level`；可选 `--product --quantity --amount --stage --next-date --follow-content --owner` |
| `update` | 改商机字段/阶段 | `--opp-id` + `--stage/--amount/--quantity/--intent-level/--product/--need/--next-date/--owner` |
| `log` | 追加跟进 | `--opp-id --content`(可选 `--feedback --next-action --stage --next-date`) |
| `close` | 签约/回款/流失 | `--opp-id --stage`(`已签约`/`已回款`/`已流失`);已回款必填 `--payment-date --payment-amount`;已流失必填 `--lost-reason` |
| `report` | 按归属单位横向汇总 | 无参；输出 6 个归属单位+合计的团单数/ABCD/预计金额/签约/回款/流失/转化率 |
| `show` | 查单条 | `--opp-id` 或 `--cust-id` |
| `due` | 到期/逾期清单+话术 | `--today` |
| `query` | 过滤查询 | `--stage/--intent-level/--owner/--store/--overdue/--cust-id` |
| `summary` | 周期汇总 | `--period daily\|weekly\|monthly` |
| `review` | 文本复盘 | `--period` |
| `export-xlsx` | 导出双表 | `--out 路径.xlsx` |
| `sync-feishu` | 飞书多维表格双表增量同步（V1.2.9） | 默认 dry-run 预览；`--yes` 实际写入；可选 `--base-token --table-opp --table-cust --batch-size`；依赖 lark-cli 已登录且对目标 Base 有权限 |
| `quote` | 委派组盒报价 | `--customer --order-quantity`,`--budget-per-box` 或 `--amount --quantity`,`--notes --delivery-area --invoice --box --list-plans N` 或 `--plan-index K --out` |
| `apply` | 吃一条已校验的抽取记录写库 | `--record record.json`(含金额/数量/电话/日期时加 `--confirmed`) |

编号规则:客户 `KH-年份-序号`、商机 `MO-年份-序号`,引擎自动生成;去重键为客户名称+联系电话,名称相近时交人工确认,不自动合并。

## 工作流

周期性复盘(周/月)必须先阅读 `references/review-methodology.md` 再下结论;单条录入与查询可跳过该文件。

### 抽取闭环(登记/更新/成交/改期)

一条话语走完整条流水线,任一检查点不过都不落库:

1. 打包抽取载荷:`scripts/prepare_extraction.py --text "店长原话" --today YYYY-MM-DD`,输出含完整契约、正确示例与禁止别名清单的载荷。
2. Agent 按载荷里的 `_output_schema` 产出单条 JSON 记录(`record.json`)。只抽"语音提取"字段;编号/门店/跟进人等系统字段不抽不猜(`store`/`owner` 由账号上下文经 `--store`/`--owner` 带入);总部维护字段首次留空。必填缺失或含糊时,先向店长追问(每次一项),补齐后重抽,不要猜。
3. 校验(硬闸口):`scripts/validate_mooncake-group-crm_output.py record.json`,退出码 0 才继续;非 0 时按报错路径改正。
4. 给店长看抽取预览,其中**金额、数量、电话、日期四类必须逐一回读并等显式确认**,其余字段确认后一并落库。
5. 写库:拿到确认后 `scripts/crm.py --mode apply --record record.json --confirmed --json`。`--confirmed` 是硬闸口--记录含上述四类字段而未带该标志时引擎拒写并回 `needs_confirmation`(不落库),此时回到第 4 步补齐确认,不要绕过。回显落库结果读给店长。

串联脚本:`scripts/run_mooncake-group-crm.sh extract|validate|apply|report|due ...`(`apply` 已内置"先校验、通过才写库")。

### 提醒、查询与导出

```bash
python3 scripts/crm.py --mode due --json                    # 逾期/今日/将到期 + 话术
python3 scripts/crm.py --mode query --overdue --json         # 仅逾期商机
python3 scripts/crm.py --mode export-xlsx --out 双表.xlsx    # 导出对齐模板的双表
```

提醒只计算清单与话术,定时推送交给平台。下次跟进日期按规则自动推算:方案报价 2 天,否则按意向等级 A=3/B=5/C=7 天,D 不自动排;逾期后再跟进按 1 天复跟(天数可配置)。已签约/已回款/已流失停止普通回访。

### 飞书多维表格双表同步

同步目标固定为上述飞书 Base。通过 `scripts/sync_feishu_bitable.py` 或 `crm.py --mode sync-feishu` 执行：

```bash
# 预览（默认 dry-run，不写入）
python3 scripts/crm.py --mode sync-feishu
# 或独立脚本
python3 scripts/sync_feishu_bitable.py

# 确认无误后实际写入
python3 scripts/crm.py --mode sync-feishu --yes
python3 scripts/sync_feishu_bitable.py --yes
```

脚本自动完成：读取本地台账生成双表记录集 → 列出 Base 中数据表并按名称匹配 → 读取字段校验 → 拉取远程已有记录建立主键映射 → 按「商机编号」/「客户编号」增量 upsert（新增用 batch-create，更新用 batch-update）→ 输出新增/更新/失败统计。默认不删除在线独有记录；字段缺失或类型冲突时停止该表同步并报告。同步前需确认 lark-cli 已登录且当前账号对目标 Base 有编辑权限（错误码 91403 表示无权限，需 Base 所有者共享）。

### 复盘与周报

```bash
python3 scripts/crm.py --mode summary --period weekly --json | python3 scripts/gen_review_report.py --out 复盘周报.html --title 体验中心店
python3 scripts/run_mooncake-group-crm.sh report --period weekly --out 复盘周报.html
```

周报是自包含 HTML,可离线打开、可打印。复盘口径(漏斗/跟进健康度/成交归因证据等级/质量门槛)见复盘方法论。

### 组盒报价(委派)

```bash
python3 scripts/crm.py --mode quote --customer "客户名称" --budget-per-box 70 --order-quantity 500 \
  --notes "不要点心" --delivery-area "长沙市内" --list-plans 3 --json     # 候选方案
python3 scripts/crm.py --mode quote --customer "客户名称" --amount 15000 --quantity 300 \
  --order-quantity 300 --notes "员工福利" --plan-index 1 --out 报价.xlsx  # 出 Excel
```

`--amount` 与 `--quantity` 同时给出时,引擎按"预计金额/数量"推算单盒预算。产物是内部成本核算 Excel,不是发给客户的报价单。

## 数据契约(Contract-First)

输入是店长的原始文字，以及可选的基准日期、账号门店和跟进人上下文。输出记录必须符合机器契约；金额、数量、电话和日期必须显式确认。校验失败时按错误路径修正后重新校验；台账损坏或报价委派失败时停止并报告，不覆盖数据、不自行补值。

抽取记录的结构唯一真相源是 `references/output-schema.json`(draft-07,所有对象 `additionalProperties:false`)。五件配套:

- `references/output-schema.json`:字段定义与枚举(意向等级 A/B/C/D;当前阶段 7 态;线索来源/客户类型/客户级别/客户状态均取模板下拉值)。
- `references/output-schema.md`:人可读字段说明、正确示例与 ❌ 禁止别名清单(如 `level/status/amount/phone_number` 等一律改用规范字段)。
- `scripts/validate_mooncake-group-crm_output.py`:校验器,退出码 0 通过 / 1 失败并打印具体错误路径;跨字段规则(新增需客户名+商机+意向等级,更新/跟进/成交/改期需定位目标,成交需阶段为已签约/已回款/已流失且已回款需回款信息)在此实现。
- `scripts/prepare_extraction.py`:producer 垫片,把原话+契约+示例+禁止清单打包成抽取载荷。
- `tests/fixture_valid.json` / `tests/fixture_invalid.json`:分别应通过 / 应失败。

机器读规则在 `references/crm-rules.json`:状态机与合法迁移、意向分级、提醒天数、终态、成交口径、报价委派配置、双表导出列映射(英文字段 → 中文列、列序与模板一致),以及语音标注版新增的 `field_provenance`(字段来源三分)、`system_auto_fields`(系统生成/带出清单)、`confirm_required`(金额/数量/电话/日期确认控制)、`voice_template`(推荐语音模板)。

## 错误处理

| 场景 | 处理 |
|---|---|
| 必填字段缺失/含糊 | 每次只追问一项,补齐重抽,不猜值落库 |
| 校验报非法枚举 | 按报错路径列出可选值(如阶段 7 态、意向 A/B/C/D)让店长选 |
| 非法阶段迁移 | 引擎拒绝并返回当前阶段的合法目标,向店长说明 |
| 写入含金额/数量/电话/日期但无 `--confirmed` | 引擎拒写并回 `needs_confirmation`(`reason=confirm_required`,`fields` 列出待确认项);向店长逐项回读确认后,加 `--confirmed` 重跑 |
| 同名客户电话不同 | 引擎返回 `needs_confirmation`,由店长确认是同一客户(加 `--cust-id`)还是新客户(加 `--new-customer`) |
| 成交无金额 / 流失无原因 | 拒绝落库,提示补齐 |
| 报价工具返回非零 | 读其 stderr 反馈店长;缺单盒预算时先追问或让其给总金额+盒数 |
| 导出报缺 openpyxl | 先 `pip install -r requirements.txt` |
| 台账 JSON 损坏 | 停止并报错,不覆盖写入 |

## 边界与局限

- 一期为单库,不做门店间权限隔离;提醒只产出清单与话术,不做定时推送;不做语音识别、不自动抓微信、不自动联系客户、不做销售预测、不自动审批报价。
- V1.2:签约与回款为独立阶段分开统计(已签约数采用累计里程碑口径,依赖 stage_history);门店客户商机表导出22列,列序与桌面模板一致;门店/跟进人/金额/日期修改写入 operation_log 留痕。
- 报价委派产出的是内部组盒成本 Excel(含税运、无利润),不是客户-facing 的团购阶梯报价单。
- D 类意向不自动排下次跟进;提醒天数取纪要示例值(A3/B5/C7、报价后 2),最终以业务确认为准。
- 复盘里的归因须按方法论标注证据等级,缺口(缺意向/缺下次跟进/缺流失原因/重复嫌疑客户)交店长补,不替店长编。

## 存储后端

本地台账仍是写入和去重的唯一数据源；指定飞书多维表格是双表交付镜像，不替代本地事务、幂等和审计逻辑。在线同步不可用或权限不足时保留本地结果并报告“未同步”，不得伪装成功，也不得读取、展示或猜测部署凭据。

## 手机端适配与性能基线(V1.2.2)

- **手机端**:`scripts/gen_mobile_page.py --data payload.json --out 页面.html` 生成移动优先(375px)自包含页面,含确认卡(金额/数量/电话/日期黄色高亮+确认/取消按钮)与门店报表(横向滑动表格)。确定性拼装:数据JSON替换模板 `assets/mobile-template.html` 的 `__MOBILE_DATA__` 占位符。
- **性能基线(2026-08-10 实测,VM-0-36-ubuntu)**:
  | 操作 | 中位耗时 | SLA |
  |---|---|---|
  | validate 校验(子进程) | 20ms | ≤2s |
  | apply 写入(引擎内存) | <1ms | ≤500ms |
  | 报表生成(15条商机) | 0.1ms | ≤1s |
  | 报表生成(100条商机) | 0.2ms | ≤1s |
  | CLI 端到端(含进程启动) | 39ms | ≤3s |
  实际瓶颈在微信语音转文字(外部能力),引擎层不构成延迟。基线回归:超出SLA 3倍即告警。

## 附加资源

- `scripts/crm.py`:确定性引擎(台账 CRUD、提醒、汇总、复盘、导出、报价委派、`apply` 消费抽取记录、`sync-feishu` 飞书双表同步)。
- `scripts/sync_feishu_bitable.py`:飞书多维表格双表同步脚本（V1.2.9），基于 lark-cli 做字段校验、按主键增量 upsert、结果核验；默认 dry-run。
- `scripts/prepare_extraction.py` / `scripts/validate_mooncake-group-crm_output.py`:契约 producer 与校验闸口。
- `scripts/gen_review_report.py` + `assets/review-template.html`:自包含 HTML 周报渲染。
- `scripts/run_mooncake-group-crm.sh`:抽取/校验/写库/周报的串联脚本。
- `references/output-schema.json` / `output-schema.md`:抽取契约与字段说明。
- `references/crm-rules.json`:状态机、提醒、成交口径、报价委派与双表列映射。
- `references/review-methodology.md`:复盘判断层方法论。
- `references/feishu-bitable-sync.md`:固定飞书多维表格的双表记录同步、字段类型、主键和安全边界。
- `tests/test_crm_engine.py`:引擎与契约单测。

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.2.9 | 2026-08-27 | 补上真正的飞书多维表格双表同步实现：新增 `scripts/sync_feishu_bitable.py`，`crm.py` 增加 `sync-feishu` 模式，基于 lark-cli 做字段校验、按主键增量 upsert 和结果核验；默认 dry-run，`--yes` 实际写入 |
| 1.2.8 | 2026-08-26 | 在线交付目标由飞书电子表格改为指定飞书多维表格 Base；双表按记录主键增量写入，并增加字段类型校验和数据表创建边界 |
| 1.2.7 | 2026-08-26 | 双表交付目标接入固定飞书电子表格“市场部客户信息”；按商机编号/客户编号增量同步，默认不删除在线数据，并增加敏感数据上传确认与同步核验 |
| 1.2.6 | 2026-08-26 | 归属单位新增“市场部”，参与新增校验、查询、导出和横向汇总；保留“体验店”到“体验中心店”的旧名归一逻辑 |
| 1.2.5 | 2026-08-26 | 维护性更新：修正复盘方法论的旧阶段口径；对齐 `add` 的实际必填参数；精简重复和未落地的运行契约；明确部署配置边界 |
| 1.2.4 | 2026-08-11 | 杰哥拍板三项:1"体验店"全部改为"体验中心店"(标准名反转,旧名归一入);2公司地址/线索来源/需求类别升级为新增商机必填硬闸口;3跟进提醒严格按 ABCD 天数,客户口述时间不覆盖 ABCD 提醒(仅D级+口述时间时兜底) |
| 1.2.3 | 2026-08-11 | 需求类别录入闸口固化进 Role Override:6 选 1 枚举+预算档位判定规则(不中 68/98/138 → 定制礼盒需确认);add 参数表补 --demand-category。教训:08-11 大成精密录入把客户原话"经典礼盒"误当类别 |
| 1.2.2 | 2026-08-10 | 可靠性三特性(TC-096任务实体化事务/TC-097乐观锁/TC-098幂等键+跟进去重);手机端适配页(gen_mobile_page.py+mobile-template.html);性能SLA基线实测固化;skill-aio 99/100 |
| 1.2.1 | 2026-08-10 | 测试用例对齐补丁:联系人/联系方式/门店/需求必填校验、微信号与前导零文本保留、数量正整数闸口、金额两位小数 |
| 1.2.0 | 2026-08-10 | V1.2变更:22列冻结表头、7态状态机(签约/回款分层)、5门店/3来源/6类别枚举+别名归一、stage_history累计里程碑、门店横向报表、operation_log、公司地址/回款/交货字段 |
| 1.1.0 | 2026-08-03 | 语音字段标注版:字段三分法+确认控制硬闸口+契约优先抽取 |
