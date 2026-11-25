import { api } from "../api/workbench.js";
import { errorText, field } from "../components/common/fields.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { resultTable } from "../components/common/table.js";
import { submit } from "../hooks/submit.js";
import { shipmentReceiptsSection } from "./shipments.js";
import { el } from "../utils/dom.js";
import { cell, download, time } from "../utils/format.js";

function reviewForm(id, saved) {
  const form = el("form", {id: "review-form"},
    field("复核意见", el("textarea", {name: "note", required: true, minlength: 3, maxlength: 500, rows: 3})),
    errorText(), el("button", {type: "submit"}, "签署复核"));
  submit(form, async values => saved(await api.submitReview(id, {note: values.get("note")})));
  return form;
}

function signature(review) {
  return el("div", {"data-testid": "reviewed", class: "signature"},
    el("strong", {}, `已签署 · ${review.actor}`), el("p", {}, review.note), el("time", {}, time(review.created_at)));
}

export async function evidencePage(config, user, route) {
  const runs = (await api.runs()).filter(item => item.status === "done");
  const run = route.id ? await api.run(route.id) : runs[0];
  const allShipments = await api.shipments();
  // 回执页保留所有出货单的冻结分板快照；下方 run 明细仍只展示所选执行批次。
  const shipments = allShipments;

  const heading = pageHeading(config.modules[3], run?.case_title || "页段裁剪与出货分板回执", run?.result ? (() => {
    const button = el("button", {type: "button"}, "导出证据");
    const issue = errorText();
    button.addEventListener("click", async () => {
      button.disabled = true;
      issue.textContent = "";
      try {
        await download(await api.export(run.id), `evidence-${run.id}.json`);
      } catch (error) {
        issue.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
    return el("div", {class: "actions"}, button, issue);
  })() : null);

  if (!run?.result) {
    return el("div", {class: "page evidence"},
      heading,
      shipmentReceiptsSection(shipments),
      section("页段裁剪回执", empty("成功执行一个批次后可以查看、签核和下载裁剪证据。")),
      el("a", {href: "#runs"}, config.modules[2]));
  }

  const review = await api.review(run.id);
  const signing = el("div", {});
  signing.append(review ? signature(review) : user.role === "reviewer" ?
    reviewForm(run.id, data => signing.replaceChildren(signature(data))) : empty("待复核员签署。"));
  const options = el("select", {"aria-label": "选择已完成的批次", onchange: event => {
    location.hash = `evidence/${event.target.value}`;
  }}, runs.map(item => el("option", {value: item.id, selected: item.id === run.id}, `#${item.id} ${item.case_title}`)));

  return el("div", {class: "page evidence"},
    heading,
    options,
    shipmentReceiptsSection(shipments),
    el("section", {class: "feature evidence-summary"}, el("div", {}, el("h2", {}, "批次判定"), el("p", {}, run.result.summary)),
      el("details", {}, el("summary", {}, "证据摘要"), el("code", {}, run.digest))),
    el("dl", {class: "metrics"}, Object.entries(run.result.metrics).map(([label, value]) =>
      el("div", {}, el("dt", {}, label), el("dd", {}, cell(value))))),
    section("业务结果明细", run.result.rows.length ? resultTable(run.result.rows) : empty("此批次无明细。")),
    section("复核签署", signing));
}
