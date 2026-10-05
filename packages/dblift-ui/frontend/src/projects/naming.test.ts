import { expect, it } from "vitest";

import type { Discovery } from "../api/types";
import { defaultNames } from "./naming";

const discovery = (name: string): Discovery => ({
  root: `/work/${name}`, name, repository: true, branch: "main", configs: [], flyway: [], script_folders: [], truncated: false,
});

it("names a single project after its folder", () => {
  expect(defaultNames(discovery("shop-api"), ["dblift.yaml"])).toEqual({ "dblift.yaml": "shop-api" });
  expect(defaultNames(discovery("shop-api"), ["db/dblift.yaml"])).toEqual({ "db/dblift.yaml": "shop-api" });
});

it("tells several projects of one folder apart", () => {
  expect(
    defaultNames(discovery("platform"), ["dblift.yaml", "dblift-reporting.yml", "services/billing/dblift.yaml", "services/shop/db/dblift.yaml"]),
  ).toEqual({
    "dblift.yaml": "platform · dblift",
    "dblift-reporting.yml": "platform · dblift-reporting",
    "services/billing/dblift.yaml": "platform · services/billing",
    "services/shop/db/dblift.yaml": "platform · services/shop/db",
  });
});

it("tells a single project apart from one of the list that has the folder's name", () => {
  expect(defaultNames(discovery("gitapp"), ["reporting/dblift.yaml"], ["shop", "gitapp"])).toEqual({
    "reporting/dblift.yaml": "gitapp · reporting",
  });
  expect(defaultNames(discovery("gitapp"), ["reporting/dblift.yaml"], ["shop"])).toEqual({ "reporting/dblift.yaml": "gitapp" });
});

it("returns nothing for no selection", () => {
  expect(defaultNames(discovery("x"), [])).toEqual({});
});
