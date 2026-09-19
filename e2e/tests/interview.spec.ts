import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';

/**
 * A person is one isolated browser context (its own cookies and storage), as if
 * on a separate machine: the interviewer and the candidate never share state
 * except through the app.
 */
async function newPerson(browser: Browser, baseURL: string | undefined) {
  const context = await browser.newContext({ baseURL });
  const page = await context.newPage();
  const uncaughtErrors: string[] = [];
  page.on('pageerror', (error) => uncaughtErrors.push(String(error)));
  return { context, page, uncaughtErrors };
}

/**
 * Capture what the "Copy invite link" button writes to the clipboard. Reading
 * the real clipboard needs a permission only Chromium can grant; recording the
 * write works in every browser and still proves what would be shared.
 */
async function captureClipboardWrites(context: BrowserContext) {
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (text: string) => {
          (window as unknown as { __copiedText?: string }).__copiedText = text;
        },
      },
    });
  });
}

const canvasOf = (page: Page) => page.getByLabel('System design canvas');

async function placeShape(page: Page, tool: string, at: { x: number; y: number }) {
  await page.getByRole('button', { name: tool, exact: true }).click();
  await canvasOf(page).click({ position: at });
}

test('the interviewer sees a change the candidate makes to the canvas', async ({ browser, baseURL }) => {
  const interviewer = await newPerson(browser, baseURL);
  const candidate = await newPerson(browser, baseURL);
  await captureClipboardWrites(interviewer.context);

  try {
    let sessionId = '';
    let joinLink = '';

    // The app has no login: access is link-based, and whoever creates a session
    // is the interviewer. So "logging in" is simply opening the app.
    await test.step('1. The interviewer opens the app', async () => {
      await interviewer.page.goto('/');
      await expect(interviewer.page.getByRole('heading', { level: 1 })).toContainText(
        'shared canvas for system design interviews',
      );
    });

    await test.step('2. The interviewer creates an interview session', async () => {
      await interviewer.page.getByRole('button', { name: 'Start a session' }).click();
      await expect(interviewer.page).toHaveURL(/\/session\/[^/?]+\?host=1$/);
      sessionId = new URL(interviewer.page.url()).pathname.split('/').pop()!;
      await expect(interviewer.page.getByText(`Interviewer · ${sessionId}`)).toBeVisible();
      await expect(canvasOf(interviewer.page)).toBeVisible();
    });

    await test.step('3. The interviewer shares the join link', async () => {
      await interviewer.page.getByRole('button', { name: 'Copy invite link' }).click();
      await expect(interviewer.page.getByRole('button', { name: 'Link copied' })).toBeVisible();

      joinLink = await interviewer.page.evaluate(
        () => (window as unknown as { __copiedText?: string }).__copiedText ?? '',
      );
      // The invite is the session URL without ?host=1, so the joiner is a candidate.
      expect(joinLink).toBe(`${new URL(interviewer.page.url()).origin}/session/${sessionId}`);
    });

    await test.step('4. The candidate joins from a separate client using that link', async () => {
      await candidate.page.goto(joinLink);
      await expect(candidate.page.getByText(`Candidate · ${sessionId}`)).toBeVisible();
      await expect(canvasOf(candidate.page)).toBeVisible();

      // Both are connected to each other before anyone draws.
      await expect(candidate.page.getByText('2 here')).toBeVisible();
      await expect(interviewer.page.getByText('2 here')).toBeVisible();
    });

    await test.step('5. The candidate changes the canvas', async () => {
      await placeShape(candidate.page, 'Database', { x: 400, y: 300 });
      await expect(canvasOf(candidate.page).getByText('Database')).toBeVisible();
    });

    await test.step('6. The interviewer sees the change', async () => {
      const seenByInterviewer = canvasOf(interviewer.page).getByText('Database');
      await expect(seenByInterviewer).toBeVisible();

      // In the same place, not merely somewhere: both start with the same view.
      const [theirs, mine] = await Promise.all([
        canvasOf(candidate.page).getByText('Database').boundingBox(),
        seenByInterviewer.boundingBox(),
      ]);
      expect(Math.abs(theirs!.x - mine!.x)).toBeLessThan(2);
      expect(Math.abs(theirs!.y - mine!.y)).toBeLessThan(2);
    });

    expect(interviewer.uncaughtErrors, 'interviewer page errors').toEqual([]);
    expect(candidate.uncaughtErrors, 'candidate page errors').toEqual([]);
  } finally {
    await interviewer.context.close();
    await candidate.context.close();
  }
});

test('a change is stored, so someone who joins later sees it too', async ({ browser, baseURL }) => {
  // The first test proves live relay between two connected people. This one
  // proves the other path: the drawing is written to Postgres and read back
  // out for anyone who arrives afterwards, or reloads.
  const interviewer = await newPerson(browser, baseURL);
  const lateJoiner = await newPerson(browser, baseURL);

  try {
    await interviewer.page.goto('/');
    await interviewer.page.getByRole('button', { name: 'Start a session' }).click();
    await expect(interviewer.page).toHaveURL(/\/session\/[^/?]+\?host=1$/);
    const sessionId = new URL(interviewer.page.url()).pathname.split('/').pop()!;

    await placeShape(interviewer.page, 'Queue', { x: 500, y: 250 });
    await expect(canvasOf(interviewer.page).getByText('Queue')).toBeVisible();

    // Arrives after the edit, so it can only come from the database. Reloading
    // covers the brief window before the server has written the edit.
    await lateJoiner.page.goto(`/session/${sessionId}`);
    await expect(async () => {
      await lateJoiner.page.reload();
      await expect(canvasOf(lateJoiner.page).getByText('Queue')).toBeVisible({ timeout: 3_000 });
    }).toPass({ timeout: 20_000 });

    // The original author reloading gets the same board back.
    await interviewer.page.reload();
    await expect(canvasOf(interviewer.page).getByText('Queue')).toBeVisible();

    expect(interviewer.uncaughtErrors).toEqual([]);
    expect(lateJoiner.uncaughtErrors).toEqual([]);
  } finally {
    await interviewer.context.close();
    await lateJoiner.context.close();
  }
});
