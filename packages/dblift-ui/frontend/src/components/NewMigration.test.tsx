import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import NewMigration from "./NewMigration";

const api = vi.hoisted(() => ({ createScripts: vi.fn() }));
vi.mock("../api/scripts", () => api);

beforeEach(() => {
  api.createScripts.mockReset();
});

it("creates a versioned SQL migration by default", async () => {
  api.createScripts.mockResolvedValue({ created: ["V1_0_2__add_invoices.sql", "U1_0_2__add_invoices.sql"] });
  const onCreated = vi.fn();
  render(<NewMigration projectId="p1" onCreated={onCreated} onCancel={() => {}} />);

  await userEvent.type(screen.getByLabelText("What does it change?"), "add invoices");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));

  expect(api.createScripts).toHaveBeenCalledWith("p1", { kind: "versioned", language: "sql", description: "add invoices" });
  expect(onCreated).toHaveBeenCalledWith(["V1_0_2__add_invoices.sql", "U1_0_2__add_invoices.sql"]);
});

it("creates a repeatable Python migration when asked", async () => {
  api.createScripts.mockResolvedValue({ created: ["R__refresh.py"] });
  render(<NewMigration projectId="p1" onCreated={() => {}} onCancel={() => {}} />);

  await userEvent.click(screen.getByRole("radio", { name: /Repeatable/ }));
  await userEvent.click(screen.getByRole("radio", { name: "Python" }));
  await userEvent.type(screen.getByLabelText("What does it change?"), "refresh");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));

  expect(api.createScripts).toHaveBeenCalledWith("p1", { kind: "repeatable", language: "python", description: "refresh" });
});

it("explains what will be created", async () => {
  render(<NewMigration projectId="p1" onCreated={() => {}} onCancel={() => {}} />);

  expect(screen.getByText(/next version number/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("radio", { name: /Repeatable/ }));
  expect(screen.getByText(/runs again whenever its content changes/i)).toBeInTheDocument();
});

it("shows the server's reason when creation fails", async () => {
  api.createScripts.mockRejectedValue(new Error("R__refresh.sql already exists"));
  const onCreated = vi.fn();
  render(<NewMigration projectId="p1" onCreated={onCreated} onCancel={() => {}} />);

  await userEvent.type(screen.getByLabelText("What does it change?"), "refresh");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("R__refresh.sql already exists");
  expect(onCreated).not.toHaveBeenCalled();
});

it("can be cancelled", async () => {
  const onCancel = vi.fn();
  render(<NewMigration projectId="p1" onCreated={() => {}} onCancel={onCancel} />);

  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

  expect(onCancel).toHaveBeenCalledTimes(1);
});

it("cannot create while a change runs or the SQL preview is open, and says why", () => {
  const { rerender } = render(<NewMigration projectId="p1" onCreated={() => {}} onCancel={() => {}} locked />);
  expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
  expect(screen.getByText(/A change is running/)).toBeInTheDocument();

  rerender(<NewMigration projectId="p1" onCreated={() => {}} onCancel={() => {}} previewing />);
  expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
  expect(screen.getByText(/Close the SQL preview before creating/)).toBeInTheDocument();
});
