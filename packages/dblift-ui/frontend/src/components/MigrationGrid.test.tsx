import { render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { Migration, Script } from "../api/types";
import MigrationGrid from "./MigrationGrid";

const A = "V1_0_0__create_accounts.sql";
const B = "V1_0_1__create_orders.sql";
const C = "V1_0_2__add_phone.sql";

function migration(script: string): Migration {
  const [version, name] = script.slice(1).replace(".sql", "").split("__");
  return { script, version: version.replaceAll("_", "."), description: name, type: "SQL", status: "PENDING", installed_on: "", installed_by: "", execution_time: 0 };
}
function script(name: string, change: string): Script {
  const [version, description] = name.slice(1).replace(".sql", "").split("__");
  return { name, kind: "versioned", version: version.replaceAll("_", "."), description, language: "sql", directory: "migrations", has_undo: false, change };
}

it("marks the migrations whose script is not committed as it is, with the git state as title", () => {
  render(
    <MigrationGrid
      migrations={[A, B, C].map(migration)}
      scripts={[script(A, ""), script(B, "modified"), script(C, "untracked")]}
      openScript={null}
      onOpen={vi.fn()}
    />,
  );
  const grid = screen.getByRole("table", { name: "Migrations" });

  expect(within(grid).getByRole("row", { name: /create accounts/ })).not.toHaveTextContent("Uncommitted");
  expect(within(within(grid).getByRole("row", { name: /create orders/ })).getByText("Uncommitted")).toHaveAttribute("title", "modified");
  expect(within(within(grid).getByRole("row", { name: /add phone/ })).getByText("Uncommitted")).toHaveAttribute("title", "untracked");
  expect(within(grid).getAllByText("Uncommitted")).toHaveLength(2);
});

it("puts the mark in the description cell", () => {
  render(<MigrationGrid migrations={[migration(B)]} scripts={[script(B, "modified")]} openScript={null} onOpen={vi.fn()} />);

  expect(screen.getByText("Uncommitted").closest("td")).toHaveTextContent("create orders");
});
