import { Roles } from "../../constants/roles.js";
import { el } from "../../utils/dom.js";

export function shell(config, user, route, page, signOut) {
  const navigation = [
    ["overview", config.modules[0]],
    ["cases", config.modules[1]],
    ["shipments", "出货单配货"],
    ["runs", config.modules[2]],
    ["evidence", config.modules[3]],
  ];
  const links = navigation.map(([name, label]) => el("a", {
    href: `#${name}`, "aria-current": route.name === name ? "page" : null,
  }, label));
  return el("div", {class: "shell"},
    el("aside", {class: "rail"},
      el("a", {class: "brand", href: "#overview"}, config.title),
      el("p", {class: "rail-direction"}, config.direction),
      el("nav", {"aria-label": "业务模块"}, links),
      el("div", {class: "rail-user"}, el("span", {}, Roles[user.role]),
        el("button", {class: "quiet", onclick: signOut, type: "button"}, "退出"))),
    el("main", {id: "content", class: "workspace", "data-route": route.id ? `${route.name}/${route.id}` : route.name}, page));
}
