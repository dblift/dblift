import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import CommandBar from "./CommandBar";

function bar(overrides: Partial<Parameters<typeof CommandBar>[0]> = {}) {
  const props = {
    counts: { applied: 2, pending: 1, failed: 0 },
    hasVersion: true,
    busy: false,
    onMigrate: vi.fn(),
    onCommand: vi.fn(),
    ...overrides,
  };
  render(<CommandBar {...props} />);
  return props;
}

it("enables migrate only when something is pending and nothing failed", () => {
  bar();
  expect(screen.getByRole("button", { name: "Migrate" })).toBeEnabled();
});

it("disables migrate when nothing is pending", () => {
  bar({ counts: { applied: 3, pending: 0, failed: 0 } });
  expect(screen.getByRole("button", { name: "Migrate" })).toBeDisabled();
});

it("disables migrate and offers repair when a migration failed", async () => {
  const props = bar({ counts: { applied: 2, pending: 0, failed: 1 } });
  expect(screen.getByRole("button", { name: "Migrate" })).toBeDisabled();

  await userEvent.click(screen.getByRole("button", { name: "Repair" }));
  expect(props.onCommand).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Confirm repair" }));
  expect(props.onCommand).toHaveBeenCalledWith("repair");
});

it("hides repair when nothing failed", () => {
  bar();
  expect(screen.queryByRole("button", { name: "Repair" })).not.toBeInTheDocument();
});

it("asks twice before undoing", async () => {
  const props = bar();

  await userEvent.click(screen.getByRole("button", { name: "Undo last migration" }));
  expect(props.onCommand).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Confirm undo" }));

  expect(props.onCommand).toHaveBeenCalledWith("undo");
});

it("lets the user back out of an undo", async () => {
  const props = bar();

  await userEvent.click(screen.getByRole("button", { name: "Undo last migration" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

  expect(props.onCommand).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Undo last migration" })).toBeInTheDocument();
});

it("disables undo when nothing is applied", () => {
  bar({ counts: { applied: 0, pending: 2, failed: 0 }, hasVersion: false });
  expect(screen.getByRole("button", { name: "Undo last migration" })).toBeDisabled();
});

it("validates at once", async () => {
  const props = bar();
  await userEvent.click(screen.getByRole("button", { name: "Validate" }));
  expect(props.onCommand).toHaveBeenCalledWith("validate");
});

it("offers a baseline only on a database with no history, and asks for a version", async () => {
  const props = bar({ counts: { applied: 0, pending: 2, failed: 0 }, hasVersion: false });

  await userEvent.click(screen.getByRole("button", { name: "Baseline…" }));
  await userEvent.type(screen.getByLabelText("Baseline version"), "1.0.0");
  await userEvent.type(screen.getByLabelText("Description"), "existing schema");
  await userEvent.click(screen.getByRole("button", { name: "Record baseline" }));

  expect(props.onCommand).toHaveBeenCalledWith("baseline", { version: "1.0.0", description: "existing schema" });
});

it("does not offer a baseline once history exists", () => {
  bar();
  expect(screen.queryByRole("button", { name: "Baseline…" })).not.toBeInTheDocument();
});

it("disables everything while a command runs", () => {
  bar({ busy: true });
  for (const name of ["Migrate", "Undo last migration", "Validate"]) {
    expect(screen.getByRole("button", { name })).toBeDisabled();
  }
});

it("calls onMigrate for the migrate button", async () => {
  const props = bar();
  await userEvent.click(screen.getByRole("button", { name: "Migrate" }));
  expect(props.onMigrate).toHaveBeenCalledTimes(1);
});

it("puts focus on Cancel when it asks to confirm, and back on the button when cancelled", async () => {
  bar({ counts: { applied: 2, pending: 0, failed: 1 } });

  for (const [ask, confirm] of [["Undo last migration", "Confirm undo"], ["Repair", "Confirm repair"]]) {
    await userEvent.click(screen.getByRole("button", { name: ask }));
    expect(screen.getByRole("button", { name: confirm })).not.toHaveFocus();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();

    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: ask })).toHaveFocus();
  }
});

it("offers New change first when asked, as a normal button disabled while a command runs", async () => {
  const onNewChange = vi.fn();
  const { rerender } = render(
    <CommandBar counts={{ applied: 2, pending: 1, failed: 0 }} hasVersion busy={false} onMigrate={vi.fn()} onCommand={vi.fn()} onNewChange={onNewChange} />,
  );

  const button = screen.getByRole("button", { name: "New change" });
  expect(screen.getAllByRole("button")[0]).toBe(button);
  expect(button).not.toHaveClass("button--primary");
  await userEvent.click(button);
  expect(onNewChange).toHaveBeenCalledTimes(1);

  rerender(<CommandBar counts={{ applied: 2, pending: 1, failed: 0 }} hasVersion busy onMigrate={vi.fn()} onCommand={vi.fn()} onNewChange={onNewChange} />);
  expect(screen.getByRole("button", { name: "New change" })).toBeDisabled();
});

it("offers no New change without a handler", () => {
  bar();
  expect(screen.queryByRole("button", { name: "New change" })).not.toBeInTheDocument();
});
