export const States = Object.freeze({
  queued: "等待执行", done: "已完成", failed: "执行失败",
});

export const Actions = Object.freeze({
  create_case: "登记资料", enqueue: "提交执行", done: "执行完成", failed: "执行失败", review: "复核签署",
  create_shipment: "创建出货单", allocate_shipment: "出货配货", shipment_shortage: "缺货未占板", revoke_shipment: "撤销出货单",
});
