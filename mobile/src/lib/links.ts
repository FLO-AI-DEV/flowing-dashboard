/* Where a "Needs action" line leads, the same as on the web: a caller's POs, a sales person's orders, or the orders
   waiting at one step. */
import type { Href } from "expo-router";
import type { Action } from "./types";

export function actionHref(a: Action): Href {
  if (a.stage === "Payments") return { pathname: "/po-person", params: { role: "crm", name: a.who } };
  if (a.stage === "Sales") return { pathname: "/orders-all", params: { sales_person: a.who } };
  return { pathname: "/orders-all", params: { stage: a.stage } };
}
