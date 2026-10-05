import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import type { Project } from "../api/types";
import Sidebar from "./Sidebar";

const api = vi.hoisted(() => ({ addProject: vi.fn(), removeProject: vi.fn() }));
vi.mock("../api/projects", () => api);

const shop: Project = { id: "p1", name: "shop-api", config_path: "/work/shop/dblift.yaml", last_environment: "", environments: [], engine: "sqlite", error: null };
const billing: Project = { ...shop, id: "p2", name: "billing", engine: "postgresql" };

function wrap(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  api.addProject.mockReset();
  api.removeProject.mockReset();
});

it("lists projects and marks the selected one", () => {
  render(wrap(<Sidebar projects={[shop, billing]} selectedId="p2" onSelect={() => {}} />));

  expect(screen.getByRole("button", { name: /^shop-api/ })).not.toHaveAttribute("aria-current");
  expect(screen.getByRole("button", { name: /^billing/ })).toHaveAttribute("aria-current", "true");
  expect(screen.getByText("postgresql")).toBeInTheDocument();
});

it("selects a project on click", async () => {
  const onSelect = vi.fn();
  render(wrap(<Sidebar projects={[shop, billing]} selectedId="p1" onSelect={onSelect} />));

  await userEvent.click(screen.getByRole("button", { name: /^billing/ }));

  expect(onSelect).toHaveBeenCalledWith("p2");
});

it("adds a project from a name and a config path", async () => {
  api.addProject.mockResolvedValue({ ...shop, id: "p3", name: "analytics" });
  const onSelect = vi.fn();
  render(wrap(<Sidebar projects={[shop]} selectedId="p1" onSelect={onSelect} />));

  await userEvent.click(screen.getByRole("button", { name: "Add project" }));
  await userEvent.type(screen.getByLabelText("Name"), "analytics");
  await userEvent.type(screen.getByLabelText("Config file path"), "/work/analytics/dblift.yaml");
  await userEvent.click(screen.getByRole("button", { name: "Add" }));

  expect(api.addProject).toHaveBeenCalledWith("analytics", "/work/analytics/dblift.yaml");
  expect(onSelect).toHaveBeenCalledWith("p3");
});

it("shows the server's reason when adding fails", async () => {
  api.addProject.mockRejectedValue(new Error("config file not found: /nope.yaml"));
  render(wrap(<Sidebar projects={[]} selectedId={null} onSelect={() => {}} />));

  await userEvent.click(screen.getByRole("button", { name: "Add project" }));
  await userEvent.type(screen.getByLabelText("Name"), "x");
  await userEvent.type(screen.getByLabelText("Config file path"), "/nope.yaml");
  await userEvent.click(screen.getByRole("button", { name: "Add" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("config file not found: /nope.yaml");
});

it("removes a project", async () => {
  api.removeProject.mockResolvedValue(undefined);
  render(wrap(<Sidebar projects={[shop]} selectedId="p1" onSelect={() => {}} />));

  await userEvent.click(screen.getByRole("button", { name: "Remove shop-api" }));

  expect(api.removeProject).toHaveBeenCalledWith("p1");
});
