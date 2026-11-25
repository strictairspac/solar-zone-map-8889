const routes = ["overview", "cases", "runs", "evidence", "shipments"];
const aliases = {
  shipment: "shipments",
  "shipment-orders": "shipments",
  "shipment-order": "shipments",
  orders: "shipments",
  allocations: "shipments",
  allocation: "shipments",
};

export function activeRoute() {
  const [rawName, id] = (location.hash.slice(1) || "overview").split("/");
  const name = aliases[rawName] || rawName;
  return {name: routes.includes(name) ? name : "overview", id: /^\d+$/.test(id || "") ? Number(id) : null};
}

export function navigate(route) {
  location.hash = route;
}

export { routes };
