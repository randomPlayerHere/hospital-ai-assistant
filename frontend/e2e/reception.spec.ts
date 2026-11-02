import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("reception registers a patient, finds them, books and cancels via the calendar", async ({ page }) => {
  const last = `Walkin${Date.now()}`;
  await login(page, "staff@hospital.example.com");
  await expect(page.getByRole("heading", { name: "Patients", exact: true })).toBeVisible();

  await page.getByLabel("First name").fill("Reception");
  await page.getByLabel("Last name").fill(last);
  await page.getByLabel("Date of birth").fill("1980-01-02");
  await page.getByLabel("Phone").first().fill("5550100");
  await page.getByLabel("Insurance ID").fill("INS-98765");
  await page.getByRole("button", { name: "Register patient" }).click();
  await expect(page.getByText(`Registered Reception ${last}`)).toBeVisible();

  await page.getByLabel("Name, phone or patient ID").fill(last);
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByRole("link", { name: new RegExp(`Open Reception ${last}`) })).toBeVisible();
  await page.getByRole("link", { name: new RegExp(`Open Reception ${last}`) }).click();
  await expect(page.getByText("INS-98765")).toBeVisible();

  await page.getByRole("link", { name: "Calendar & booking" }).click();
  await page.getByLabel("Doctor").selectOption({ label: "Dr. Vikram Shah (General Medicine)" });
  await page.getByLabel("Find patient (name, phone)").fill(last);
  await page.getByLabel("Patient", { exact: true }).selectOption({ index: 1 });
  // switch to Day view and advance day-by-day until a day with free slots exists (weekends have none)
  await page.getByRole("button", { name: "Day" }).click();
  for (let i = 0; i < 8; i++) {
    const slot = page.getByRole("button", { name: /^\d\d:\d\d$/ }).first();
    const noSlots = page.getByText("No free slots this day.");
    await expect(slot.or(noSlots)).toBeVisible();
    if (await slot.isVisible()) break;
    await page.getByRole("button", { name: "Next day" }).click();
  }
  await page
    .getByRole("button", { name: /^\d\d:\d\d$/ })
    .first()
    .click();
  await expect(page.getByText(/^Booked /)).toBeVisible();
  await page.getByRole("button", { name: new RegExp(`Reception ${last}`) }).click();
  await page.getByRole("button", { name: "Cancel appointment" }).click();
  await expect(page.getByText("Appointment cancelled.")).toBeVisible();
});
