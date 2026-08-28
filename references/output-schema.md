# 抽取记录契约说明（output-schema）

本文件是 `output-schema.json` 的人可读版。店长的一句话经 Agent 抽取后，**必须**产出符合本契约的 JSON；`scripts/validate_mooncake-group-crm_output.py` 校验通过、店长确认后，引擎才写台账。字段名与《月饼哥哥_团购客户管理双表模板》的列一一对应（英文键 → 中文列，映射见 `crm-rules.json` 的 `export` 段）。

## 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `intent` | enum | 是 | `add_customer`/`update_opportunity`/`log_followup`/`close_deal`/`set_next`/`query` |
| `recorded_at` | date | 否 | 话语日期，默认今天 |
| `store` | string | 否 | 所属门店/归属单位；标准值为月湖店、体验中心店、国金店、五一店、花样汇店、市场部 |
| `owner` | string | 否 | 跟进人 |
| `source` | enum | 否 | 线索来源（V1.2 三值）：`新获客/老客转介绍/老客续费`；历史数据的“主动开发”统一映射为“新获客” |
| `match` | object | 条件 | 定位目标；`update_opportunity`/`log_followup`/`close_deal`/`set_next` 必填其一 |
| `customer` | object | 条件 | 客户字段；`add_customer` 必填 `customer.name` |
| `opportunity` | object | 条件 | 商机字段；`add_customer` 必填 |
| `follow_up` | object | 条件 | 跟进记录；`log_followup` 必填 `follow_up.content` |
| `deal` | object | 条件 | 成交/流失；`close_deal` 必填 |

## match（定位目标）

`opp_id`（`MO-YYYY-NNNN`）或 `cust_id`（`KH-YYYY-NNNN`）或 `customer_name` 或 `contact_phone`。`add_customer` 时可带 `customer_name`/`contact_phone` 供引擎做去重预检。

## customer（客户档案）

`name`(1–30)、`short_name`、`contact`(主联系人)、`contact_phone`(联系电话/微信，手机号或微信号均可)、`customer_type`(枚举)、`industry`、`customer_level`(枚举：核心/重点/一般/潜在客户)、`region`、`address`、`title`(职务)、`other_contacts`、`preference`、`tags`、`customer_status`(枚举：活跃/待激活/沉睡/流失)、`notes`。

## opportunity（商机）

`customer_address`(公司地址，新增必填：联系人所在地址，不是配送地址)、`customer_need`(客户需求，新增必填：用途/预算/规格/交期/定制要求原始摘要)、`product`(意向产品，自由文本)、`demand_category`(需求类别，V1.2 枚举6选1：**散装/68礼盒/98礼盒/138礼盒/定制礼盒/待定**；判定规则：单盒预算=预计金额÷意向数量，命中68/98/138元档→对应礼盒；不命中→默认“定制礼盒”并向店长确认；无法判定→“待定”+追问；禁止用客户原话自由填写)、`quantity`(整数≥1，单位盒)、`intent_level`(枚举 **A/B/C/D**，展示“代码-中文”：A-必成/B-高潜/C-跟进/D-观望)、`expected_amount`(数字≥0，保留两位小数)、`stage`(枚举，**V1.2 七态：初次接触/需求确认/方案报价/谈判中/已签约/已回款/已流失**，线性流转不可跳级不可回退，已流失为终态)、`next_follow_date`(date，条件必填：按意向等级/阶段规则计算；口述日期只写入跟进内容，D 级无默认天数时例外)。

## follow_up（跟进）

`followed_at`(date)、`content`(本次跟进，必填)、`customer_feedback`、`next_action`。最新一条会回写到商机表“最近跟进情况”。

## deal（成交/流失）

`deal_date`(date)、`deal_amount`(数字≥0)、`payment_status`(枚举：未回款/部分回款/已回款；**仅引擎内部与复盘使用，不是双表列**)、`lost_reason`(阶段=已流失 时必填)。双表列中回款字段为 `payment_date`(回款日期)/`payment_amount`(回款金额)，阶段=已回款 时二者必填；`delivery_date`(交货日期) 选填。

## 字段来源标注（语音字段标注版）

模板第 3 行给每个字段标了来源，抽取时按此分工（机器读版见 `crm-rules.json` 的 `field_provenance`）：

- **语音自动提取（voice）**：客户名称、公司地址、联系人、联系电话/微信、线索来源、客户需求、需求类别、意向产品、意向数量、意向等级、预计金额、当前阶段、最近跟进情况、下次跟进日期、回款日期/回款金额、交货日期、流失原因，以及档案表的所在区域、详细地址、客户偏好。——只有这些从话语里抽。
- **系统自动生成/带出（system）**：商机编号、客户编号、所属门店、跟进人、最后更新时间，以及档案表的首次开发门店、首次/最近合作日期、历史购买产品、历史成交次数、累计/本年度成交金额、客户状态、档案更新时间。——**不要从话语抽取、不要猜**；`store`/`owner` 默认取账号上下文，话语明确提及时可用。编号一律由引擎生成，记录里不出现。
- **总部补充/确认（hq）**：客户简称、客户类型、所属行业、客户级别、职务、其他关键联系人、当前归属门店、客户负责人、重要客户标签、备注。——门店首次不录，话语没说到就留空，由总部建长期档案时补。

## 确认控制（关键控制·代码硬闸口）

**金额、数量、电话号码、日期**四类字段抽取后必须由店长显式确认才写入，预览时逐一回读，不得自动落库。对应字段：`opportunity.expected_amount`、`deal.deal_amount`、`opportunity.quantity`、`customer.contact_phone`、`recorded_at`、`opportunity.next_follow_date`、`deal.deal_date`、`follow_up.followed_at`。

这条控制在引擎里是**硬闸口**：写入类模式（`add/update/log/close/apply`）只要命中上述字段而未带 `--confirmed`，`crm.py` 一律拒写并返回 `{"status":"needs_confirmation","reason":"confirm_required","fields":[…]}`（不落库）。仅改阶段等不含这四类的操作不受影响。系统按规则推算的下次跟进日期不算"抽取值"，不触发闸口。

## 推荐语音模板

> 今天联系了【客户名称】的【联系人】，公司地址【地址】，【线索来源】，客户需要【产品/用途/需求类别】，预计【数量】，预算【金额】，目前进展到【阶段】，沟通情况是【结果】，计划【日期】再次跟进（口述日期只记录，提醒按规则计算）。

## 跟进提醒规则（V1.2.4）

严格按意向等级 ABCD 天数提醒：A=3天、B=5天、C=7天、D级无默认天数；当前阶段=方案报价 时 2 天优先于等级规则（含D级）。**即使客户/店长口述了下次联系时间，也仍按 ABCD 天数提醒**，口述时间只记入跟进内容；仅 D 级且口述了时间时才按口述时间排提醒。到期未完成按 1 天复跟；已签约/已回款/已流失停止普通回访。

## 跨字段规则（validate 脚本强制）

- `add_customer` ⇒ 需 `customer.name` + `customer.contact_phone` + `source`（线索来源） + `opportunity`（含 `intent_level`、`customer_need`、`customer_address`、`demand_category`；`stage` 缺省=初次接触）。V1.2.4 必填：公司地址/线索来源/需求类别缺失时应先追问，不猜。
- `update_opportunity` / `log_followup` / `close_deal` / `set_next` ⇒ 需 `match`（至少一项）。
- `close_deal` ⇒ 需 `deal`，且 `opportunity.stage ∈ {已签约, 已回款, 已流失}`；已回款 必填 `payment_date`+`payment_amount`，已流失 必填 `lost_reason`。
- `set_next` ⇒ 需 `opportunity.next_follow_date`。
- `log_followup` ⇒ 需 `follow_up.content`。
- 所有对象 `additionalProperties:false`，出现未定义字段即报错。

## ✅ 正确示例（新增一条商机）

```json
{
  "intent": "add_customer",
  "recorded_at": "2026-07-31",
  "store": "体验中心店",
  "owner": "张店长",
  "source": "老客转介绍",
  "customer": {
    "name": "深圳八方科技有限公司",
    "contact": "王经理",
    "contact_phone": "13800000000",
    "customer_type": "企业客户"
  },
  "opportunity": {
    "customer_address": "深圳市南山区科技园",
    "customer_need": "员工中秋福利，采购300盒，单盒预算约150元",
    "product": "经典礼盒",
    "demand_category": "定制礼盒",
    "quantity": 300,
    "intent_level": "A",
    "expected_amount": 45000,
    "stage": "方案报价",
    "next_follow_date": "2026-08-02"
  },
  "follow_up": {
    "content": "已发送报价方案，客户内部确认中"
  }
}
```

## ❌ 禁止字段 / 别名（出现即校验失败）

不要用下列别名替代规范字段名：

- `nickname` / `customer_name`(顶层) / `company` → 用 `customer.name`
- `phone_number` / `mobile` / `tel` / `wechat_id` → 用 `customer.contact_phone`
- `level` / `grade` / `意向` / `intent` (表示等级时) → 用 `opportunity.intent_level`（值 A/B/C/D，**不是** 高/中/低）
- `state` / `status` / `阶段` / `step` → 用 `opportunity.stage`（值只能是 V1.2 七态；**不是** 新增线索/已报价/跟进中/已成交/暂缓跟进/谈判跟进 等废弃旧态）
- `category` / `type` / `类别`（表示需求类别时） → 用 `opportunity.demand_category`（值只能是 散装/68礼盒/98礼盒/138礼盒/定制礼盒/待定 六选一；**不是** 客户原话如“经典礼盒”“月如意”“59.8元简装”）
- `amount` / `price` / `money` / `budget`(顶层) → 商机预计金额用 `opportunity.expected_amount`；成交金额用 `deal.deal_amount`
- `need` / `demand` / `requirement` → 用 `opportunity.customer_need`
- `next_date` / `follow_date` / `remind_at` → 用 `opportunity.next_follow_date`
- `remark` / `memo` → 客户备注用 `customer.notes`；跟进备注并入 `follow_up.content`
- 任何未在上表列出的键 → 一律禁止（`additionalProperties:false`）
