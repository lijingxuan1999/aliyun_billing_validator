---
name: sap-billing-validator
description: SAP 3PL 账单校验系统，支持费率卡上传、发票校验、驳回发票并生成供应商通知邮件草稿
version: 1.1.0
triggers:
  - 上传账单
  - 上传发票
  - 账单校验
  - 费率卡
  - billing
  - invoice
  - rate card
  - 提交审批
  - 驳回发票
  - reject invoice
---

# SAP Billing Validator

## 描述

这个技能连接 SAP 3PL 账单校验系统，让你通过自然语言完成以下操作：
- 使用服务端预置的费率卡和发票（无需手动上传文件）
- 上传费率卡 CSV 文件并校验发票 PDF
- 查询历史账单状态和校验结果
- 驳回问题发票并生成供应商通知邮件草稿

## 触发条件

当用户提到以下任一场景时自动触发：
- 上传账单、发票、invoice、billing、PDF
- 上传费率卡、rate card、CSV
- 账单校验、validate billing、validation
- 查询账单、billing status、历史账单
- 提交审批、submit approval
- 驳回发票、reject invoice、供应商通知
- 3PL 物流账单相关问题

## 使用步骤

### 使用服务端预置文件校验（推荐，无需上传）
1. 用户直接说"用 billing doc 和费率卡进行校验"
2. 系统自动调用 list_staged_files 列出可用文件
3. 调用 upload_staged_rate_card 上传预置费率卡
4. 调用 validate_staged_billing_pdf 校验预置发票
5. 返回校验结果

### 上传费率卡（手动）
1. 用户提供 CSV 文件和费率卡名称
2. 调用 ask_billing_agent，说明要上传费率卡，包含 base64 编码的 CSV 内容
3. 返回创建成功的费率卡 ID 和行项目数量

### 上传并校验发票 PDF（手动）
1. 用户提供 PDF 文件和对应费率卡
2. 调用 ask_billing_agent，说明要上传并校验发票
3. 系统自动完成：OCR 提取 → 规则校验 → AI 语义匹配
4. 返回校验结果：整体状态、金额对比、具体 findings

### 驳回问题发票
1. 校验发现差异后，用户确认要驳回该发票
2. 调用 reject_invoice_and_draft_email，传入发票号、差异描述、供应商邮箱
3. 系统生成审批流编号并返回邮件草稿（草稿不自动发送）
4. 用户确认草稿内容后再手动发送

### 查询历史账单
1. 用户描述查询需求
2. 调用 ask_billing_agent 传入问题
3. 返回结构化的账单数据和分析

## 注意事项

- 服务端已预置 HZL-2026-003 合同相关的费率卡和发票，可直接使用无需上传
- 手动上传文件时需要将文件转为 base64 编码
- 费率卡 CSV 格式：包含 serviceCode, serviceDesc, unit, unitPrice, currency 列
- 发票 PDF 通过 SAP Document Intelligence 做 OCR，支持中英文发票
- 驳回邮件为草稿，需用户确认后手动发送
- 对话支持中英文切换
