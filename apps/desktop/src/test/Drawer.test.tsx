import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Drawer } from "../ui/Drawer";

function Page() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open</button>
      {open && (
        <Drawer title="Kim Lee" onClose={() => setOpen(false)}>
          <label>Name<input /></label>
          <button type="button">Save</button>
        </Drawer>
      )}
    </>
  );
}

describe("the drawer", () => {
  it("takes focus, keeps it, closes on Escape and gives it back", async () => {
    render(<Page />);
    const opener = screen.getByRole("button", { name: "Open" });
    await userEvent.click(opener);
    expect(screen.getByRole("dialog", { name: "Kim Lee" })).toHaveAttribute("aria-modal", "true");
    expect(screen.getByLabelText("Name")).toHaveFocus();

    // Tab goes round inside it, never back out to the page
    const close = screen.getByRole("button", { name: "Close" });
    const save = screen.getByRole("button", { name: "Save" });
    await userEvent.tab();
    expect(save).toHaveFocus();
    await userEvent.tab();
    expect(close).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(save).toHaveFocus();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});
