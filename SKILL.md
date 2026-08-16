---
name: sap-billing-validator
description: SAP 3PL 账单校验系统，支持上传费率卡、发票校验、查询账单状态和提交审批
version: 1.0.0
triggers:
  - 上传账单
  - 上传发票
  - 账单校验
  - 费率卡
  - billing
  - invoice
  - rate card
  - 提交审批
---

# SAP Billing Validator

## 描述

这个技能连接 SAP 3PL 账单校验系统，让你通过自然语言完成以下操作：
- 上传费率卡 CSV 文件
- 上传发票 PDF 并自动完成 AI 校验（对比费率卡）
- 查询历史账单状态和校验结果
- 提交账单审批

## 触发条件

当用户提到以下任一场景时自动触发：
- 上传账单、发票、invoice、billing、PDF
- 上传费率卡、rate card、CSV
- 账单校验、validate billing、validation
- 查询账单、billing status、历史账单
- 提交审批、submit approval
- 3PL 物流账单相关问题

## 使用步骤

### 上传费率卡
1. 用户提供 CSV 文件和费率卡名称
2. 调用 ask_billing_agent，说明要上传费率卡，包含 base64 编码的 CSV 内容
3. 返回创建成功的费率卡 ID 和行项目数量

### 上传并校验发票 PDF
1. 用户提供 PDF 文件和对应费率卡
2. 调用 ask_billing_agent，说明要上传并校验发票
3. 系统自动完成：OCR 提取 → 规则校验 → AI 语义匹配
4. 返回校验结果：整体状态、金额对比、具体 findings

### 查询历史账单
1. 用户描述查询需求
2. 调用 ask_billing_agent 传入问题
3. 返回结构化的账单数据和分析

### 提交审批
1. 用户指定要审批的账单和审批人邮箱
2. 调用 ask_billing_agent
3. SAP BPA 工作流自动触发，审批人收到邮件通知

## 注意事项

- 上传文件前需要将文件转为 base64 编码
- 费率卡 CSV 格式：包含 serviceCode, serviceDesc, unit, unitPrice, currency 列
- 发票 PDF 通过 SAP Document Intelligence 做 OCR，支持中英文发票
- 所有写操作都通过 SAP AI Core（Claude）做 orchestration 决策
- 对话支持中英文切换
