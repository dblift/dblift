import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import type { Project } from "../api/types";
import Sidebar from "./Sidebar";

const api = vi.hoisted(() => ({ removeProject: vi.fn() }));
vi.mock("../api/projects", () => api);

const shop: Project = { id: "p1", name: "shop-api", config_path: "/work/shop/dblift.yaml", last_environment: "", environments: [], engine: "sqlite", error: null, missing: false, repository: "shop", repository_path: "/work/shop" };
const billing: Project = { ...shop, id: "p2", name: "billing", engine: "postgresql" };

function wrap(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  api.removeProject.mockReset();
});

it("lists projects and marks the selected one", () => {
  render(wrap(<Sidebar projects={[shop, billing]} selectedId="p2" onSelect={() => {}} onAdd={() => {}} />));

  expect(screen.getByRole("button", { name: /^shop-api/ })).not.toHaveAttribute("aria-current");
  expect(screen.getByRole("button", { name: /^billing/ })).toHaveAttribute("aria-current", "true");
  expect(screen.getByText("postgresql")).toBeInTheDocument();
});

it("selects a project on click", async () => {
  const onSelect = vi.fn();
  render(wrap(<Sidebar projects={[shop, billing]} selectedId="p1" onSelect={onSelect} onAdd={() => {}} />));

  await userEvent.click(screen.getByRole("button", { name: /^billing/ }));

  expect(onSelect).toHaveBeenCalledWith("p2");
});

it("asks to open the add-project dialog", async () => {
  const onAdd = vi.fn();
  render(wrap(<Sidebar projects={[shop]} selectedId="p1" onSelect={() => {}} onAdd={onAdd} />));

  await userEvent.click(screen.getByRole("button", { name: "Add project" }));

  expect(onAdd).toHaveBeenCalledTimes(1);
  expect(screen.queryByLabelText("Config file path")).not.toBeInTheDocument();
});

it("groups the projects of one repository under its name", () => {
  const billing = { ...shop, id: "p2", name: "billing", repository: "platform", repository_path: "/work/platform" };
  const reporting = { ...shop, id: "p3", name: "reporting", repository: "platform", repository_path: "/work/platform" };
  render(wrap(<Sidebar projects={[shop, billing, reporting]} selectedId="p1" onSelect={() => {}} onAdd={() => {}} />));

  const group = screen.getByRole("group", { name: "platform" });
  expect(within(group).getAllByRole("button", { name: /^(billing|reporting)/ })).toHaveLength(2);
  expect(screen.queryByRole("group", { name: shop.repository })).not.toBeInTheDocument();
});

it("says when a project's config is not on this branch", () => {
  render(wrap(<Sidebar projects={[{ ...shop, missing: true, error: "…" }]} selectedId="p1" onSelect={() => {}} onAdd={() => {}} />));

  expect(screen.getByRole("button", { name: /^shop-api/ })).toHaveTextContent("not on this branch");
});

it("removes a project after a confirmation in place", async () => {
  api.removeProject.mockResolvedValue(undefined);
  render(wrap(<Sidebar projects={[shop]} selectedId="p1" onSelect={() => {}} onAdd={() => {}} />));

  await userEvent.click(screen.getByRole("button", { name: "Remove shop-api" }));
  expect(api.removeProject).not.toHaveBeenCalled();

  const confirm = screen.getByRole("button", { name: "Remove" });
  expect(confirm).toHaveAccessibleDescription(/only from this list.*No file is deleted/);
  await userEvent.click(confirm);

  expect(api.removeProject).toHaveBeenCalledWith("p1");
});

it("keeps the project when the removal is cancelled or the user clicks elsewhere", async () => {
  render(wrap(<Sidebar projects={[shop]} selectedId="p1" onSelect={() => {}} onAdd={() => {}} />));

  await userEvent.click(screen.getByRole("button", { name: "Remove shop-api" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Remove shop-api" }));
  await userEvent.click(screen.getByText("Projects"));
  expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Remove shop-api" })).toBeInTheDocument();

  expect(api.removeProject).not.toHaveBeenCalled();
});

it("shows the server's reason when removing fails", async () => {
  api.removeProject.mockRejectedValue(new Error("registry file is read-only"));
  render(wrap(<Sidebar projects={[shop]} selectedId="p1" onSelect={() => {}} onAdd={() => {}} />));

  await userEvent.click(screen.getByRole("button", { name: "Remove shop-api" }));
  await userEvent.click(screen.getByRole("button", { name: "Remove" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("registry file is read-only");
});
