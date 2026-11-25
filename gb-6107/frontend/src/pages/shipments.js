import { api } from "../api/workbench.js";
import { errorText, field } from "../components/common/fields.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { resultTable } from "../components/common/table.js";
import { submit } from "../hooks/submit.js";
import { el } from "../utils/dom.js";

const STATUS_TEXT = {
  pending: "待配货",
  allocated: "已配货",
  confirmed: "已确认占用",
  active: "已占用",
  shortage: "缺货·未占板",
  revoked: "已撤销·板件已释放",
  cancelled: "已取消·板件已释放",
};

export function shipmentStatus(status) {
  return STATUS_TEXT[status] || status;
}

function watts(cw) {
  return typeof cw === "number" ? (cw / 100).toFixed(2).replace(/\.00$/, "") : "—";
}

function orderCard(order, {onChanged, detailed = true, readOnly = false} = {}) {
  const message = errorText();
  const retry = el("button", {
    type: "button", "data-action": "retry-shipment", "data-shipment-id": order.id,
    "aria-label": "重试已配货出货单", title: "重试已配货出货单，不重复占板",
    onclick: async () => {
      retry.disabled = true;
      message.textContent = "";
      try {
        await api.allocateShipment(order.id);
        await onChanged?.();
      } catch (error) {
        message.textContent = error.message;
        retry.disabled = false;
      }
    },
  }, "重试");
  const revoke = el("button", {
    type: "button", class: "quiet", "data-action": "revoke-shipment", "data-shipment-id": order.id,
    "aria-label": "撤销出货单并释放板件", title: "撤销后释放板件",
    onclick: async () => {
      revoke.disabled = true;
      message.textContent = "";
      try {
        await api.revokeShipment(order.id, {reason: "页面撤销"});
        await onChanged?.();
      } catch (error) {
        message.textContent = error.message;
        revoke.disabled = false;
      }
    },
  }, "撤销");

  const active = ["allocated", "confirmed", "active"].includes(order.status);
  const terminalRelease = ["revoked", "cancelled", "canceled"].includes(order.status);
  const serials = order.allocated_serials || order.serials || [];
  const card = el("article", {
    class: `shipment-card status-${order.status}`,
    "data-testid": "shipment-order",
    "data-shipment-id": order.id,
    "data-status": order.status,
  },
    el("header", {},
      el("strong", {"data-testid": "shipment-code"}, order.code || order.order_no || `出货单 #${order.id}`),
      el("span", {
        class: "status", "data-testid": "shipment-status", "data-status": order.status,
      }, shipmentStatus(order.status))),
    el("p", {
      class: "revocation-state",
      "data-testid": "revocation-status",
      "data-revoked": terminalRelease ? "true" : "false",
    }, terminalRelease ? "撤销状态：已撤销（板件已释放，分板快照保留）" : "撤销状态：未撤销"),
    el("p", {class: "muted"}, `闪测质保批 #${order.case_id}`),
    el("p", {},
      `瓦数 ${watts(order.low_cw ?? order.low)}–${watts(order.high_cw ?? order.high)} W；`,
      `需求 ${order.quantity} 块；当时分到 ${serials.length} 块。`),
    el("p", {
      class: "shipment-serials",
      "data-testid": "shipment-serials",
      "data-field": "allocated_serials",
      "data-allocated-serials": serials.join(","),
    },
      serials.length ? serials.join("、") : "暂无占用板件"),
    order.revoke_reason ? el("p", {class: "muted"}, `撤销原因：${order.revoke_reason}`) : null,
    detailed && order.receipt?.summary ? el("p", {class: "muted", "data-testid": "shipment-summary"}, order.receipt.summary) : null,
    detailed && order.receipt?.rows?.length ? el("details", {},
      el("summary", {}, "查看本单页段裁剪回执"),
      resultTable(order.receipt.rows)) : null,
    !readOnly ? el("div", {class: "actions"},
      !terminalRelease ? retry : null,
      active || order.status === "pending" || order.status === "shortage" ? revoke : null,
      message) : null);
  return card;
}

export function shipmentReceiptsSection(orders) {
  return section("出货单分板回执", el("div", {
    class: "stack", "data-testid": "shipment-receipts",
  }, orders.length ? orders.map(order => orderCard(order, {readOnly: true, detailed: true})) :
    empty("同一质保批还没有出货单；配货后这里保留每单当时分到的板件和撤销状态。")));
}

function shipmentForm(cases, selectedId, onCreated) {
  const form = el("form", {id: "shipment-form", class: "shipment-form"},
    field("闪测质保批", el("select", {name: "case_id", required: true},
      cases.map(item => el("option", {value: item.id, selected: item.id === selectedId}, `${item.code} · ${item.title}`)))),
    el("div", {class: "split"},
      field("瓦数范围下限（W）", el("input", {name: "low", "aria-label": "瓦数范围下限", type: "number", min: "0", max: "5000", step: "0.01", required: true, value: "419"})),
      field("瓦数范围上限（W）", el("input", {name: "high", "aria-label": "瓦数范围上限", type: "number", min: "0", max: "5000", step: "0.01", required: true, value: "421"}))),
    el("div", {class: "split"},
      field("配货数量（整单）", el("input", {name: "quantity", "aria-label": "配货数量", type: "number", min: "1", max: "4096", step: "1", required: true, value: "2"})),
      field("每页闪测条数", el("input", {name: "page_size", "aria-label": "每页闪测条数", type: "number", min: "1", max: "256", step: "1", value: "4"}))),
    field("出货单号（可选，重试可复用）", el("input", {name: "code", maxlength: "64", placeholder: "留空自动生成"})),
    errorText(),
    el("button", {type: "submit", "data-testid": "create-shipment", "aria-label": "创建出货单并配货"}, "配货"));
  submit(form, async values => {
    const lowW = Number(values.get("low"));
    const highW = Number(values.get("high"));
    const payload = {
      low_cw: Math.round(lowW * 100),
      high_cw: Math.round(highW * 100),
      quantity: Number(values.get("quantity")),
      page_size: Number(values.get("page_size") || 4),
    };
    const code = values.get("code")?.trim();
    if (code) payload.code = code;
    try {
      const created = await api.createShipment(Number(values.get("case_id")), payload);
      await onCreated?.(created);
      form.reset();
    } catch (error) {
      // 缺货单也会以 shortage 状态落库；先刷新列表，再由统一表单错误区显示原因。
      await onCreated?.();
      throw error;
    }
  });
  return form;
}

export async function shipmentsPage(_config, user, route) {
  const [cases, orders] = await Promise.all([api.cases(), api.shipments()]);
  if (!cases.length) {
    return el("div", {class: "page"}, pageHeading("出货单分板配货", "同一闪测质保批向不同出货单分配板件"),
      empty("请先在试板质保批中登记资料。"));
  }
  const selectedId = route.id && cases.some(item => item.id === route.id) ? route.id : cases[0].id;
  const operator = user.role === "operator";
  let currentOrders = route.id ? orders.filter(item => item.case_id === route.id) : orders;

  async function refresh() {
    const latest = await api.shipments(route.id || undefined);
    currentOrders = route.id ? latest.filter(item => item.case_id === route.id) : latest;
    const list = el("div", {"data-testid": "shipment-list", class: "stack"},
      currentOrders.length ? currentOrders.map(order => orderCard(order, {onChanged: refresh, readOnly: !operator})) :
        empty("还没有出货单；创建后将按瓦数范围和整单数量占用板件。"));
    listSection.replaceChildren(list);
  }

  const listSection = section("出货单与占用", el("div", {id: "shipment-list", "data-testid": "shipment-list", class: "stack"},
    currentOrders.length ? currentOrders.map(order => orderCard(order, {onChanged: refresh, readOnly: !operator})) :
      empty("还没有出货单；创建后将按瓦数范围和整单数量占用板件。")));

  return el("div", {class: "page shipments-page"},
    pageHeading("出货单分板配货", "同一闪测质保批按各单瓦数范围和整单数量配货；页段裁剪选板，唯一占用保证一板不二主。"),
    el("div", {class: "split shipment-layout"},
      operator ? section("新建出货单", shipmentForm(cases, selectedId, refresh)) :
        section("出货单与占用（只读）", empty("当前账号可查看配货和撤销状态。")),
      listSection));
}

export { orderCard as shipmentOrderCard };
