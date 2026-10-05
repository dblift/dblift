import { render } from "@testing-library/react";
import { expect, it } from "vitest";

import EngineLogo, { logoFor } from "./EngineLogo";

it("finds the mark of a known engine", () => {
  expect(logoFor("postgresql")).toContain("postgresql");
  expect(logoFor("SQLite")).toContain("sqlite");
});

it("understands common aliases", () => {
  expect(logoFor("postgres")).toBe(logoFor("postgresql"));
  expect(logoFor("mssql")).toBe(logoFor("sqlserver"));
  expect(logoFor("mongo")).toBe(logoFor("mongodb"));
});

it("falls back to the generic mark", () => {
  expect(logoFor("")).toContain("generic");
  expect(logoFor("some-new-engine")).toBe(logoFor(""));
});

it("renders a decorative image", () => {
  const { container } = render(<EngineLogo engine="mysql" />);
  const image = container.querySelector("img")!;
  expect(image).toHaveAttribute("alt", "");
  expect(image.getAttribute("src")).toContain("mysql");
});
