import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ConfigDocument, ConfigFormData, EngineSpec, Project } from "../api/types";
import { emptyConnection, emptyForm } from "../config/defaults";
import ConfigForm from "./ConfigForm";

const api = vi.hoisted(() => ({
  getEngines: vi.fn(), previewConfig: vi.fn(), createConfig: vi.fn(), readConfig: vi.fn(), updateConfig: vi.fn(),
}));
vi.mock("../api/configs", () => api);

const server = ["host", "port", "database", "username", "password"];
const engines: EngineSpec[] = [
  { id: "postgresql", label: "PostgreSQL", scheme: "postgresql", port: 5432, fields: [...server, "schema"] },
  { id: "oracle", label: "Oracle", scheme: "oracle", port: 1521, fields: ["host", "port", "service_name", "username", "password", "schema"] },
  { id: "sqlite", label: "SQLite", scheme: "sqlite", port: null, fields: ["path"] },
  { id: "snowflake", label: "Snowflake", scheme: "snowflake", port: null, fields: ["account", "database", "warehouse", "schema", "username", "password"] },
];
const project: Project = {
  id: "p1", name: "shop-api", config_path: "/work/shop/dblift.yaml", last_environment: "", environments: [],
  engine: "postgresql", error: null, missing: false, repository: "shop", repository_path: "/work/shop",
};
const good = { yaml: "database:\n  url: postgresql://db:5432/shop\n", problems: [], warnings: [] };

function open(target: Parameters<typeof ConfigForm>[0]["target"]) {
  const props = { target, onSaved: vi.fn(), onClose: vi.fn() };
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ConfigForm {...props} />
    </QueryClientProvider>,
  );
  return props;
}
const create = { kind: "create" as const, folder: "/work/shop", migrations: "./db/migrations", name: "shop" };
const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const settle = () => act(() => vi.advanceTimersByTimeAsync(450));

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  Object.values(api).forEach((mock) => mock.mockReset());
  api.getEngines.mockResolvedValue(engines);
  api.previewConfig.mockResolvedValue(good);
});
afterEach(() => vi.useRealTimers());

it("offers the engines and shows the fields of the chosen one", async () => {
  open(create);
  expect(await screen.findByRole("dialog", { name: "New configuration" })).toBeInTheDocument();
  const picker = screen.getByRole("radiogroup", { name: "Engine" });
  expect(within(picker).getAllByRole("radio").map((r) => r.getAttribute("aria-label") ?? r.parentElement?.textContent)).toHaveLength(4);
  expect(screen.getByLabelText("Port")).toHaveValue(5432);
  expect(screen.getByLabelText("Migrations folder")).toHaveValue("./db/migrations");
  expect(screen.getByLabelText("Project name")).toHaveValue("shop");
  expect(screen.getByLabelText("File name")).toHaveValue("dblift.yaml");

  await user().click(within(picker).getByRole("radio", { name: "Oracle" }));
  expect(screen.getByLabelText("Service name")).toBeInTheDocument();
  expect(screen.queryByLabelText("Database")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Port")).toHaveValue(1521);

  await user().click(within(picker).getByRole("radio", { name: "SQLite" }));
  expect(screen.getByLabelText("Database file")).toBeInTheDocument();
  expect(screen.queryByLabelText("Host")).not.toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "Password" })).not.toBeInTheDocument();

  await user().click(within(picker).getByRole("radio", { name: "Snowflake" }));
  expect(screen.getByLabelText("Account")).toBeInTheDocument();
  expect(screen.getByLabelText("Warehouse")).toBeInTheDocument();
  expect(screen.queryByLabelText("Port")).not.toBeInTheDocument();
});

it("defaults the password to a variable and warns about a typed one", async () => {
  open(create);
  const password = await screen.findByRole("group", { name: "Password" });
  expect(within(password).getByRole("radio", { name: "Environment variable" })).toBeChecked();
  expect(within(password).getByLabelText("Variable name")).toHaveValue("DBLIFT_DB_PASSWORD");
  expect(within(password).queryByRole("radio", { name: "Keep the saved one" })).not.toBeInTheDocument();

  await user().click(within(password).getByRole("radio", { name: "Type it here" }));

  expect(within(password).getByLabelText("Password value")).toHaveAttribute("type", "password");
  expect(within(password).getByText(/written in the file in clear text/)).toBeInTheDocument();
});

it("previews after a pause and shows the loader's verdict", async () => {
  api.previewConfig.mockResolvedValue({ yaml: "", problems: ["the host is required (letters, digits, dots and dashes)"], warnings: [] });
  open(create);
  await screen.findByRole("dialog");
  await settle();

  expect(await screen.findByRole("alert")).toHaveTextContent("the host is required");
  expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();

  api.previewConfig.mockResolvedValue({ ...good, warnings: ["The variable DBLIFT_DB_PASSWORD is not set where this interface runs; commands will fail until it is."] });
  const calls = api.previewConfig.mock.calls.length;
  await user().type(screen.getByLabelText("Host"), "db");
  expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
  await settle();

  expect(api.previewConfig.mock.calls.length).toBe(calls + 1);
  expect((api.previewConfig.mock.lastCall![0] as ConfigFormData).connection.host).toBe("db");
  expect(await screen.findByText(/postgresql:\/\/db:5432\/shop/)).toBeInTheDocument();
  expect(screen.getByText(/DBLIFT_DB_PASSWORD is not set/)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create" })).toBeEnabled();
});

it("ignores an older preview that arrives late", async () => {
  let first: (value: typeof good) => void = () => {};
  api.previewConfig.mockImplementationOnce(() => new Promise((resolve) => (first = resolve)));
  open(create);
  await screen.findByRole("dialog");
  await settle();
  api.previewConfig.mockResolvedValue({ ...good, yaml: "database:\n  url: postgresql://newer:5432/shop\n" });
  await user().type(screen.getByLabelText("Host"), "newer");
  await settle();
  expect(await screen.findByText(/newer:5432/)).toBeInTheDocument();

  await act(async () => first({ ...good, yaml: "database:\n  url: postgresql://older:5432/shop\n" }));

  expect(screen.queryByText(/older:5432/)).not.toBeInTheDocument();
});

it("creates the config and reports the new project", async () => {
  api.createConfig.mockResolvedValue({ ...project, id: "new" });
  const props = open(create);
  await screen.findByRole("dialog");
  await user().type(screen.getByLabelText("Host"), "db");
  await user().clear(screen.getByLabelText("File name"));
  await user().type(screen.getByLabelText("File name"), "dblift-shop.yaml");
  await settle();

  await user().click(screen.getByRole("button", { name: "Create" }));

  await waitFor(() => expect(props.onSaved).toHaveBeenCalledWith({ ...project, id: "new" }));
  const [folder, filename, name, form] = api.createConfig.mock.lastCall!;
  expect([folder, filename, name]).toEqual(["/work/shop", "dblift-shop.yaml", "shop"]);
  expect((form as ConfigFormData).connection.host).toBe("db");
});

it("keeps the dialog open when the server refuses", async () => {
  api.createConfig.mockRejectedValue(new Error("/work/shop/dblift.yaml already exists"));
  const props = open(create);
  await screen.findByRole("dialog");
  await settle();

  await user().click(screen.getByRole("button", { name: "Create" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  expect(props.onSaved).not.toHaveBeenCalled();
});

it("adds and removes environments", async () => {
  open(create);
  await screen.findByRole("dialog");

  await user().click(screen.getByRole("button", { name: "Add environment" }));
  const block = screen.getByRole("group", { name: "Environment 1" });
  await user().type(within(block).getByLabelText("Name"), "staging");
  await user().type(within(block).getByLabelText("Host"), "stg");
  await settle();

  const sent = api.previewConfig.mock.lastCall![0] as ConfigFormData;
  expect(sent.environments).toEqual([{ name: "staging", connection: { ...emptyConnection(engines[0], true), host: "stg" } }]);

  await user().click(within(block).getByRole("button", { name: "Remove" }));
  expect(screen.queryByRole("group", { name: "Environment 1" })).not.toBeInTheDocument();
});

it("edits an existing config, keeping the saved password by default", async () => {
  const form = emptyForm(engines[0], "./migrations");
  form.connection = { ...form.connection, host: "old-host", database: "shop", password: { mode: "keep", value: "" } };
  const document: ConfigDocument = { form, revision: "r".repeat(64), notes: ["A connection has options this form does not cover, so it is edited as one URL."] };
  api.readConfig.mockResolvedValue(document);
  api.updateConfig.mockResolvedValue(project);
  const props = open({ kind: "edit", project });

  expect(await screen.findByRole("dialog", { name: "Configuration of shop-api" })).toBeInTheDocument();
  expect(await screen.findByLabelText("Host")).toHaveValue("old-host");
  expect(screen.getByText(/edited as one URL/)).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: "Keep the saved one" })).toBeChecked();
  expect(screen.queryByLabelText("File name")).not.toBeInTheDocument();
  await settle();
  expect(api.previewConfig.mock.lastCall![1]).toBe("p1");

  await user().clear(screen.getByLabelText("Host"));
  await user().type(screen.getByLabelText("Host"), "new-host");
  await settle();
  await user().click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(props.onSaved).toHaveBeenCalledWith(project));
  const [id, sent, revision] = api.updateConfig.mock.lastCall!;
  expect([id, revision]).toEqual(["p1", "r".repeat(64)]);
  expect((sent as ConfigFormData).connection.host).toBe("new-host");
});

it("shows one URL field for a connection the form cannot express", async () => {
  const form = emptyForm(engines[0], "./migrations");
  form.connection = { ...form.connection, mode: "url", url: "postgresql+psycopg://app:********@h:5432/shop" };
  api.readConfig.mockResolvedValue({ form, revision: "r", notes: [] });
  open({ kind: "edit", project });

  expect(await screen.findByLabelText("Connection URL")).toHaveValue("postgresql+psycopg://app:********@h:5432/shop");
  expect(screen.queryByLabelText("Host")).not.toBeInTheDocument();
});

it("explains a config that cannot be opened", async () => {
  api.readConfig.mockRejectedValue(new Error("the file has no database section"));
  open({ kind: "edit", project });

  expect(await screen.findByRole("alert")).toHaveTextContent("no database section");
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
});
