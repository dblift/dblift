import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import NewConfigsNotice from "./NewConfigsNotice";

it("counts one configuration that is not a project yet", () => {
  render(<NewConfigsNotice count={1} onAdd={vi.fn()} onDismiss={vi.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent("1 configuration on this branch is not a project yet.");
});

it("counts several configurations that are not projects yet", () => {
  render(<NewConfigsNotice count={3} onAdd={vi.fn()} onDismiss={vi.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent("3 configurations on this branch are not projects yet.");
});

it("offers to add them or to dismiss the notice", async () => {
  const onAdd = vi.fn();
  const onDismiss = vi.fn();
  render(<NewConfigsNotice count={2} onAdd={onAdd} onDismiss={onDismiss} />);

  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  expect(onAdd).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(onDismiss).toHaveBeenCalledTimes(1);
});
