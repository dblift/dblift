import { expect, it } from "vitest";

import { slug } from "./slug";

it("lower-cases the words and joins them with dashes", () => {
  expect(slug("Add Invoices table")).toBe("add-invoices-table");
});

it("keeps ASCII letters and digits only, any other character separating words", () => {
  expect(slug("orders: v2 / phone_number & e-mail!")).toBe("orders-v2-phone-number-e-mail");
});

it("turns accented letters into their plain letters", () => {
  expect(slug("Ajouter la référence")).toBe("ajouter-la-reference");
});

it("never starts or ends with a dash", () => {
  expect(slug("  --Add invoices--  ")).toBe("add-invoices");
});

it("keeps at most 40 characters, without a dash at the cut", () => {
  const long = slug("add the invoices table with its lines and the payments of each invoice");
  expect(long.length).toBeLessThanOrEqual(40);
  expect(long).toBe("add-the-invoices-table-with-its-lines-an");
  expect(slug("a".repeat(39) + " b")).toBe("a".repeat(39));
});

it("is never empty", () => {
  expect(slug("")).toBe("change");
  expect(slug("   ")).toBe("change");
  expect(slug("日本語 !!")).toBe("change");
});

it("reads the whole description, line breaks included", () => {
  expect(slug("Add invoices\nwith lines")).toBe("add-invoices-with-lines");
});
