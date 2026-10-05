import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import type { Discovery, Project } from "../api/types";
import AddProject from "./AddProject";

const discoveryApi = vi.hoisted(() => ({ getDefaults: vi.fn(), discoverFolder: vi.fn(), cloneRepository: vi.fn() }));
vi.mock("../api/discovery", () => discoveryApi);
const projectsApi = vi.hoisted(() => ({ addProject: vi.fn() }));
vi.mock("../api/projects", () => projectsApi);
const flywayApi = vi.hoisted(() => ({ readFlyway: vi.fn() }));
vi.mock("../api/flyway", () => flywayApi);

const found: Discovery = {
  root: "/work/platform", name: "platform", repository: true, branch: "main", truncated: false,
  configs: [
    { path: "dblift.yaml", kind: "named", problem: null, registered: false },
    { path: "services/billing/dblift.yaml", kind: "named", problem: null, registered: true },
    { path: "config/database.yaml", kind: "content", problem: null, registered: false },
    { path: "dblift-broken.yaml", kind: "named", problem: "line 3, column 9: mapping values are not allowed here", registered: false },
    { path: "dblift.yaml.template", kind: "template", problem: null, registered: false },
  ],
  flyway: ["legacy/flyway.conf"],
  script_folders: ["legacy/sql"],
};
const project = (id: string, name: string, repositoryPath: string): Project => ({
  id, name, config_path: `${repositoryPath}/dblift.yaml`, last_environment: "", environments: [], engine: "sqlite",
  error: null, missing: false, repository: repositoryPath.split("/").pop()!, repository_path: repositoryPath,
  flyway_table: null,
});

function dialog(overrides: Partial<Parameters<typeof AddProject>[0]> = {}) {
  const props = { projects: [] as Project[], onAdded: vi.fn(), onConfigure: vi.fn(), onClose: vi.fn(), ...overrides };
  const wrap = (children: ReactNode) => <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
  render(wrap(<AddProject {...props} />));
  return props;
}
const box = (path: string) => screen.getByRole("checkbox", { name: path });

beforeEach(() => {
  discoveryApi.getDefaults.mockReset();
  discoveryApi.getDefaults.mockResolvedValue({ clone_parent: "/home/dev/dblift-projects", git: true });
  discoveryApi.discoverFolder.mockReset();
  discoveryApi.discoverFolder.mockResolvedValue(found);
  discoveryApi.cloneRepository.mockReset();
  projectsApi.addProject.mockReset();
  projectsApi.addProject.mockImplementation(async (name: string) => ({ ...project(`id-${name}`, name, "/work/platform") }));
  flywayApi.readFlyway.mockReset();
});

it("is a dialog that Escape closes", async () => {
  const props = dialog();
  expect(screen.getByRole("dialog", { name: "Add project" })).toBeInTheDocument();

  await userEvent.keyboard("{Escape}");

  expect(props.onClose).toHaveBeenCalledTimes(1);
});

it("keeps keyboard focus inside the dialog", async () => {
  render(<button>Before the dialog</button>);
  dialog();
  render(<button>After the dialog</button>);
  expect(screen.getByLabelText("Folder path")).toHaveFocus();
  const close = screen.getByRole("button", { name: "Close" });
  const look = screen.getByRole("button", { name: "Look for configs" });

  look.focus();
  await userEvent.tab();
  expect(close).toHaveFocus();

  await userEvent.tab({ shift: true });
  expect(look).toHaveFocus();
});

it("lists what a folder holds, with the usable configs selected", async () => {
  dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/platform");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));

  expect(discoveryApi.discoverFolder).toHaveBeenCalledWith("/work/platform");
  expect(await screen.findByText("/work/platform")).toBeInTheDocument();
  expect(screen.getByText("main")).toBeInTheDocument();
  expect(box("dblift.yaml")).toBeChecked();
  expect(box("config/database.yaml")).toBeChecked();
  expect(box("services/billing/dblift.yaml")).not.toBeChecked();
  expect(box("services/billing/dblift.yaml")).toBeDisabled();
  expect(box("dblift-broken.yaml")).toBeDisabled();
  expect(box("dblift.yaml.template")).not.toBeChecked();
  expect(box("dblift.yaml.template")).toBeEnabled();
  expect(screen.getByText("already added")).toBeInTheDocument();
  expect(screen.getByText("detected by its content")).toBeInTheDocument();
  expect(screen.getByText(/mapping values are not allowed here/)).toBeInTheDocument();
  expect(screen.getByText("legacy/flyway.conf")).toBeInTheDocument();
  expect(screen.getByText("legacy/sql")).toBeInTheDocument();
});

it("proposes names and adds the selected configs", async () => {
  const props = dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/platform");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));
  await screen.findByText("/work/platform");

  expect(screen.getByLabelText("Name for dblift.yaml")).toHaveValue("platform · dblift");
  expect(screen.getByLabelText("Name for config/database.yaml")).toHaveValue("platform · config");
  await userEvent.clear(screen.getByLabelText("Name for dblift.yaml"));
  await userEvent.type(screen.getByLabelText("Name for dblift.yaml"), "platform");
  await userEvent.click(screen.getByRole("button", { name: "Add 2 projects" }));

  await waitFor(() => expect(props.onAdded).toHaveBeenCalledWith(["id-platform", "id-platform · config"]));
  expect(projectsApi.addProject).toHaveBeenCalledWith("platform", "/work/platform/dblift.yaml");
  expect(projectsApi.addProject).toHaveBeenCalledWith("platform · config", "/work/platform/config/database.yaml");
  expect(props.onClose).toHaveBeenCalledTimes(1);
});

it("renames to the plain folder name when one config is left selected", async () => {
  dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/platform");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));
  await screen.findByText("/work/platform");

  await userEvent.click(box("config/database.yaml"));

  expect(screen.getByLabelText("Name for dblift.yaml")).toHaveValue("platform");
  expect(screen.getByRole("button", { name: "Add 1 project" })).toBeEnabled();
});

it("keeps the dialog open and shows which one failed", async () => {
  projectsApi.addProject.mockImplementation(async (name: string) => {
    if (name === "platform · config") {
      throw new Error("config file not found: /work/platform/config/database.yaml");
    }
    return project("id-ok", name, "/work/platform");
  });
  const props = dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/platform");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));
  await screen.findByText("/work/platform");

  await userEvent.click(screen.getByRole("button", { name: "Add 2 projects" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("config file not found");
  expect(props.onAdded).toHaveBeenCalledWith(["id-ok"]);
  expect(props.onClose).not.toHaveBeenCalled();
  expect(box("dblift.yaml")).toBeDisabled();
});

it("has nothing to add when nothing usable was found", async () => {
  discoveryApi.discoverFolder.mockResolvedValue({ ...found, configs: [], flyway: [], script_folders: ["migrations"] });
  dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/empty");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));

  expect(await screen.findByText("No config file was found in this folder.")).toBeInTheDocument();
  expect(screen.getByText("migrations")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Add \d/ })).not.toBeInTheDocument();
});

it("offers to create a configuration for a migration folder without one", async () => {
  const props = dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/platform");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));
  await screen.findByText("/work/platform");

  const orphans = screen.getByRole("region", { name: "Migration folders no config points at" });
  await userEvent.click(within(orphans).getByRole("button", { name: "Create configuration" }));

  expect(props.onConfigure).toHaveBeenCalledWith({ folder: "/work/platform", migrations: "./legacy/sql", name: "platform" });
});

it("offers to create a configuration when none was found", async () => {
  discoveryApi.discoverFolder.mockResolvedValue({ ...found, configs: [], flyway: [], script_folders: [] });
  const props = dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/empty");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));

  await userEvent.click(await screen.findByRole("button", { name: "Create a configuration" }));

  expect(props.onConfigure).toHaveBeenCalledWith({ folder: "/work/platform", migrations: "./migrations", name: "platform" });
});

it("converts a Flyway project into a pre-filled configuration", async () => {
  const form = { engine: "sqlite", migrations_directory: "./sql" };
  flywayApi.readFlyway.mockResolvedValue({ folder: "/work/platform/legacy", form, table: "flyway_schema_history", notes: ["Check it."] });
  const props = dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/platform");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));
  await screen.findByText("/work/platform");

  await userEvent.click(screen.getByRole("button", { name: "Convert legacy/flyway.conf" }));

  expect(flywayApi.readFlyway).toHaveBeenCalledWith("/work/platform", "legacy/flyway.conf");
  await waitFor(() =>
    expect(props.onConfigure).toHaveBeenCalledWith({
      folder: "/work/platform/legacy", migrations: "./sql", name: "legacy", initial: form, notes: ["Check it."],
    }),
  );
});

it("says why a Flyway project cannot be converted", async () => {
  flywayApi.readFlyway.mockRejectedValue(new Error("the file is too large to read"));
  const props = dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/platform");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));
  await screen.findByText("/work/platform");

  await userEvent.click(screen.getByRole("button", { name: "Convert legacy/flyway.conf" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("too large");
  expect(props.onConfigure).not.toHaveBeenCalled();
});

it("says when the folder was too large to scan entirely", async () => {
  discoveryApi.discoverFolder.mockResolvedValue({ ...found, truncated: true });
  dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/platform");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));

  expect(await screen.findByText(/too many files/i)).toBeInTheDocument();
});

it("shows the server's reason when a folder cannot be scanned, and lets the user retry", async () => {
  discoveryApi.discoverFolder.mockRejectedValueOnce(new Error("/nope is not a folder"));
  dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/nope");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("/nope is not a folder");
  expect(screen.getByLabelText("Folder path")).toHaveValue("/nope");
});

it("clones, then lists what the clone holds", async () => {
  let finish: (value: { path: string }) => void = () => {};
  discoveryApi.cloneRepository.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
  dialog();
  await userEvent.click(screen.getByRole("radio", { name: "Clone a repository" }));
  expect(await screen.findByLabelText("Clone into")).toHaveValue("/home/dev/dblift-projects");
  await userEvent.type(screen.getByLabelText("Repository address"), "git@github.com:acme/platform.git");
  await userEvent.click(screen.getByRole("button", { name: "Clone and look for configs" }));

  expect(await screen.findByText(/Cloning/)).toBeInTheDocument();
  expect(discoveryApi.cloneRepository).toHaveBeenCalledWith("git@github.com:acme/platform.git", "/home/dev/dblift-projects");
  finish({ path: "/home/dev/dblift-projects/platform" });

  await waitFor(() => expect(discoveryApi.discoverFolder).toHaveBeenCalledWith("/home/dev/dblift-projects/platform"));
  expect(await screen.findByText("/work/platform")).toBeInTheDocument();
});

it("shows why a clone was refused", async () => {
  discoveryApi.cloneRepository.mockRejectedValue(new Error("use an https:// or ssh:// address, git@host:path, or the full path of a local repository"));
  dialog();
  await userEvent.click(screen.getByRole("radio", { name: "Clone a repository" }));
  await userEvent.type(screen.getByLabelText("Repository address"), "http://example.com/x.git");
  await userEvent.click(screen.getByRole("button", { name: "Clone and look for configs" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("use an https:// or ssh:// address");
});

it("explains that cloning needs git", async () => {
  discoveryApi.getDefaults.mockResolvedValue({ clone_parent: "/home/dev/dblift-projects", git: false });
  dialog();
  await userEvent.click(screen.getByRole("radio", { name: "Clone a repository" }));

  expect(await screen.findByText(/git is not installed/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Clone and look for configs" })).toBeDisabled();
});

it("offers the repositories of existing projects for a new scan", async () => {
  dialog({ projects: [project("p1", "a", "/work/platform"), project("p2", "b", "/work/platform"), project("p3", "c", "/work/other")] });

  const shortcuts = screen.getByRole("group", { name: "Scan again" });
  expect(within(shortcuts).getAllByRole("button").map((b) => b.textContent)).toEqual(["/work/other", "/work/platform"]);
  await userEvent.click(within(shortcuts).getByRole("button", { name: "/work/platform" }));

  expect(discoveryApi.discoverFolder).toHaveBeenCalledWith("/work/platform");
});

it("goes back to the source step", async () => {
  dialog();
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/platform");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));
  await screen.findByText("/work/platform");

  await userEvent.click(screen.getByRole("button", { name: "Back" }));

  expect(screen.getByLabelText("Folder path")).toHaveValue("/work/platform");
});
